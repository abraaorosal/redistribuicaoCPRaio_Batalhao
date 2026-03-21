from __future__ import annotations

from collections import Counter

from _config import (
    COHERENCE_MARGIN_KM,
    EXCESSIVE_DISTANCE_KM,
    NEIGHBOR_COUNT_FOR_COHERENCE,
    SIGNIFICANT_GAIN_KM,
    STABILITY_MARGIN_KM,
)
from _shared import (
    CURRENT_SCENARIO_PATH,
    EUSEBIO_SCENARIO_PATH,
    HORIZONTE_SCENARIO_PATH,
    MATRIX_JSON_PATH,
    SCENARIO_COMPARISON_CSV_PATH,
    SCENARIO_COMPARISON_JSON_PATH,
    build_battalion_summaries,
    build_logger,
    build_neighbor_map,
    build_record_index,
    classify_distance_band,
    ensure_runtime_dirs,
    get_distance_km,
    get_duration_min,
    load_json,
    load_normalized_records,
    load_scenarios,
    matrix_to_lookup,
    mean,
    now_iso,
    percentil,
    rank_scenario_tuple,
    safe_float,
    summarize_distance_series,
    write_csv,
    write_json,
)


SCENARIO_OUTPUTS = {
    "cenario_atual": CURRENT_SCENARIO_PATH,
    "cenario_eusebio": EUSEBIO_SCENARIO_PATH,
    "cenario_horizonte": HORIZONTE_SCENARIO_PATH,
}


def build_candidate_distances(
    municipio: str,
    active_battalions: list[str],
    matrix_lookup: dict[str, dict[str, dict[str, object]]],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for batalhao in active_battalions:
        distance_km = get_distance_km(matrix_lookup, municipio, batalhao)
        duration_min = get_duration_min(matrix_lookup, municipio, batalhao)
        if distance_km is None:
            continue
        output.append(
            {
                "batalhao": batalhao,
                "distance_km": distance_km,
                "duration_min": duration_min,
            }
        )
    output.sort(key=lambda item: (item["distance_km"], item["batalhao"]))
    return output


def optimize_assignments(
    records: list[dict[str, object]],
    active_battalions: list[str],
    scenario: dict[str, object],
    matrix_lookup: dict[str, dict[str, dict[str, object]]],
    neighbor_map: dict[str, list[str]],
) -> tuple[dict[str, str], dict[str, str]]:
    # Primeiro minimizamos a distância rodoviária; depois aplicamos estabilidade e coerência territorial.
    assignments: dict[str, str] = {}
    reasons: dict[str, str] = {}
    active_set = set(active_battalions)
    fixed_set = set(scenario.get("batalhoes_fixos", []))
    promoted_set = set(scenario.get("batalhoes_promovidos", []))
    metro_choice = scenario.get("batalhao_metropolitano_escolhido")

    for record in records:
        municipio = str(record["nome"])
        current_battalion = str(record["batalhao_atual"])
        candidate_distances = build_candidate_distances(municipio, active_battalions, matrix_lookup)
        if not candidate_distances:
            assignments[municipio] = current_battalion
            reasons[municipio] = "sem_matriz_valida"
            continue

        best = candidate_distances[0]
        current_option = next(
            (item for item in candidate_distances if item["batalhao"] == current_battalion),
            None,
        )

        if municipio in active_set:
            assignments[municipio] = municipio
            if municipio in fixed_set:
                reasons[municipio] = "batalhao_fixo_obrigatorio"
            elif municipio in promoted_set:
                reasons[municipio] = "batalhao_promovido_obrigatorio"
            elif municipio == metro_choice:
                reasons[municipio] = "novo_batalhao_metropolitano"
            else:
                reasons[municipio] = "sede_ativa_no_cenario"
            continue

        if current_option and (
            safe_float(current_option["distance_km"]) - safe_float(best["distance_km"]) <= STABILITY_MARGIN_KM
        ):
            assignments[municipio] = current_battalion
            if current_battalion == best["batalhao"]:
                reasons[municipio] = "estrutura_atual_ja_eficiente"
            else:
                reasons[municipio] = "margem_estabilidade"
            continue

        assignments[municipio] = str(best["batalhao"])
        reasons[municipio] = "menor_distancia_rodoviaria"

    for _ in range(2):
        changed = False
        for record in records:
            municipio = str(record["nome"])
            if municipio in active_set:
                continue
            current_assignment = assignments[municipio]
            neighbors = neighbor_map.get(municipio, [])
            neighbor_assignments = [assignments[name] for name in neighbors if name in assignments]
            if len(neighbor_assignments) < 3:
                continue
            majority_battalion, majority_count = Counter(neighbor_assignments).most_common(1)[0]
            if majority_battalion == current_assignment or majority_count < 3:
                continue
            current_distance = get_distance_km(matrix_lookup, municipio, current_assignment)
            majority_distance = get_distance_km(matrix_lookup, municipio, majority_battalion)
            if current_distance is None or majority_distance is None:
                continue
            if majority_distance - current_distance <= COHERENCE_MARGIN_KM:
                assignments[municipio] = majority_battalion
                reasons[municipio] = "coerencia_territorial"
                changed = True
        if not changed:
            break

    return assignments, reasons


def classify_row(row: dict[str, object], best_distance_km: float | None) -> tuple[str, bool, bool]:
    current_distance = safe_float(row.get("distancia_rodoviaria_ao_batalhao_atual_km"))
    target_distance = safe_float(row.get("distancia_rodoviaria_ao_batalhao_cenario_km"))
    gain = safe_float(row.get("ganho_km"))
    changed = bool(row.get("mudar_batalhao"))

    mal_alocado = False
    if current_distance is not None and best_distance_km is not None:
        mal_alocado = (current_distance - best_distance_km) >= SIGNIFICANT_GAIN_KM

    ganho_forte = gain is not None and gain >= SIGNIFICANT_GAIN_KM
    if changed and ganho_forte:
        return "forte_ganho", mal_alocado, ganho_forte
    if changed:
        return "redistribuido", mal_alocado, ganho_forte
    if target_distance is not None and target_distance > EXCESSIVE_DISTANCE_KM:
        return "atencao_logistica", mal_alocado, ganho_forte
    if mal_alocado:
        return "sensivel", mal_alocado, ganho_forte
    return "estavel", mal_alocado, ganho_forte


def build_justification(
    row: dict[str, object],
    *,
    reason_code: str,
    best_battalion: str | None,
    best_distance_km: float | None,
) -> str:
    municipality = row["municipio"]
    current_battalion = row["batalhao_atual"]
    target_battalion = row["batalhao_cenario"]
    current_distance = safe_float(row.get("distancia_rodoviaria_ao_batalhao_atual_km"))
    target_distance = safe_float(row.get("distancia_rodoviaria_ao_batalhao_cenario_km"))
    gain = safe_float(row.get("ganho_km"))

    if reason_code == "batalhao_fixo_obrigatorio":
        return f"{municipality} permanece como sede de batalhão fixo obrigatório."
    if reason_code == "batalhao_promovido_obrigatorio":
        return f"{municipality} torna-se sede de batalhão promovido obrigatório."
    if reason_code == "novo_batalhao_metropolitano":
        return f"{municipality} foi selecionado como novo polo metropolitano do cenário."
    if reason_code == "estrutura_atual_ja_eficiente":
        return (
            f"A alocação atual em {current_battalion} já é a mais eficiente em distância rodoviária real "
            f"({target_distance:.1f} km)."
        )
    if reason_code == "margem_estabilidade":
        return (
            f"{municipality} foi mantido em {current_battalion} por estabilidade estrutural; a diferença para "
            f"{best_battalion} ficou dentro da margem configurada de {STABILITY_MARGIN_KM:.1f} km."
        )
    if reason_code == "coerencia_territorial":
        return (
            f"{municipality} foi ajustado para {target_battalion} para evitar fragmentação territorial, com "
            f"desempenho técnico dentro de {COHERENCE_MARGIN_KM:.1f} km do melhor concorrente."
        )
    if reason_code == "sem_matriz_valida":
        return f"{municipality} permaneceu em {current_battalion} por ausência de distância OSRM válida."
    if reason_code == "menor_distancia_rodoviaria":
        gain_text = f" com ganho de {gain:.1f} km" if gain is not None and gain > 0 else ""
        return (
            f"{municipality} foi redistribuído de {current_battalion} para {target_battalion} por menor "
            f"distância rodoviária real ({target_distance:.1f} km frente a {current_distance:.1f} km){gain_text}."
        )
    return f"{municipality} foi mantido em {target_battalion} por critério operacional do cenário."


def count_fragmented_cases(
    rows: list[dict[str, object]],
    assignments: dict[str, str],
    neighbor_map: dict[str, list[str]],
    matrix_lookup: dict[str, dict[str, dict[str, object]]],
) -> int:
    fragmented = 0
    active_set = {row["municipio"] for row in rows if row["municipio"] == row["batalhao_cenario"]}
    for row in rows:
        municipio = str(row["municipio"])
        if municipio in active_set:
            continue
        neighbors = neighbor_map.get(municipio, [])
        neighbor_assignments = [assignments[name] for name in neighbors if name in assignments]
        if len(neighbor_assignments) < 3:
            continue
        majority_battalion, majority_count = Counter(neighbor_assignments).most_common(1)[0]
        current_assignment = assignments[municipio]
        if majority_battalion == current_assignment or majority_count < 3:
            continue
        current_distance = get_distance_km(matrix_lookup, municipio, current_assignment)
        majority_distance = get_distance_km(matrix_lookup, municipio, majority_battalion)
        if (
            current_distance is not None
            and majority_distance is not None
            and majority_distance - current_distance <= COHERENCE_MARGIN_KM
        ):
            fragmented += 1
    return fragmented


def evaluate_scenario(
    *,
    scenario_id: str,
    scenario: dict[str, object],
    records: list[dict[str, object]],
    matrix_lookup: dict[str, dict[str, dict[str, object]]],
    neighbor_map: dict[str, list[str]],
) -> dict[str, object]:
    # O cenário atual é baseline preservado; Eusébio e Horizonte são recalculados com base na matriz OSRM.
    active_battalions = list(scenario.get("batalhoes_ativos", []))
    mode = scenario.get("modo_alocacao")
    assignments: dict[str, str] = {}
    reasons: dict[str, str] = {}

    if mode == "baseline_atual":
        for record in records:
            municipio = str(record["nome"])
            assignments[municipio] = str(record["batalhao_atual"])
            reasons[municipio] = "estrutura_atual_preservada"
    else:
        assignments, reasons = optimize_assignments(
            records,
            active_battalions,
            scenario,
            matrix_lookup,
            neighbor_map,
        )

    rows: list[dict[str, object]] = []
    for record in records:
        municipio = str(record["nome"])
        current_battalion = str(record["batalhao_atual"])
        scenario_battalion = assignments[municipio]
        candidate_distances = build_candidate_distances(municipio, active_battalions, matrix_lookup)
        best_option = candidate_distances[0] if candidate_distances else None
        current_distance = get_distance_km(matrix_lookup, municipio, current_battalion)
        scenario_distance = get_distance_km(matrix_lookup, municipio, scenario_battalion)
        duration_min = get_duration_min(matrix_lookup, municipio, scenario_battalion)
        gain = (
            round(current_distance - scenario_distance, 6)
            if current_distance is not None and scenario_distance is not None
            else None
        )
        row = {
            "municipio": municipio,
            "latitude": record.get("latitude"),
            "longitude": record.get("longitude"),
            "status_atual": record.get("status_atual"),
            "status_sugerido_pre_hierarquia": "batalhao"
            if municipio == scenario_battalion
            else record.get("status_atual"),
            "batalhao_codigo_atual": record.get("batalhao_codigo_atual"),
            "batalhao_atual": current_battalion,
            "companhia_atual": record.get("companhia_atual"),
            "batalhao_cenario": scenario_battalion,
            "distancia_rodoviaria_ao_batalhao_atual_km": current_distance,
            "distancia_rodoviaria_ao_batalhao_cenario_km": scenario_distance,
            "tempo_estimado_ao_batalhao_cenario_min": duration_min,
            "ganho_km": gain,
            "mudar_batalhao": current_battalion != scenario_battalion,
            "melhor_batalhao_disponivel": best_option["batalhao"] if best_option else None,
            "distancia_melhor_batalhao_disponivel_km": best_option["distance_km"] if best_option else None,
            "diferenca_para_melhor_batalhao_km": (
                round(scenario_distance - best_option["distance_km"], 6)
                if best_option and scenario_distance is not None
                else None
            ),
            "faixa_distancia": classify_distance_band(scenario_distance),
            "criterio_decisao": reasons.get(municipio),
            "observacoes": record.get("observacoes"),
        }
        label, mal_alocado, ganho_forte = classify_row(
            row,
            best_option["distance_km"] if best_option else None,
        )
        row["classificacao_analitica"] = label
        row["mal_alocado_no_cenario_atual"] = mal_alocado
        row["ganho_significativo"] = ganho_forte
        row["justificativa_tecnica"] = build_justification(
            row,
            reason_code=reasons.get(municipio, "estrutura_atual_preservada"),
            best_battalion=best_option["batalhao"] if best_option else None,
            best_distance_km=best_option["distance_km"] if best_option else None,
        )
        rows.append(row)

    distance_series = [
        float(row["distancia_rodoviaria_ao_batalhao_cenario_km"])
        for row in rows
        if safe_float(row.get("distancia_rodoviaria_ao_batalhao_cenario_km")) is not None
    ]
    distance_summary = summarize_distance_series(distance_series)
    battalion_summaries = build_battalion_summaries(
        rows,
        battalion_field="batalhao_cenario",
        distance_field="distancia_rodoviaria_ao_batalhao_cenario_km",
        changed_field="mudar_batalhao",
    )
    centrality_operacional = mean(
        [item["distancia_media_km"] for item in battalion_summaries if item["distancia_media_km"] is not None]
    )
    compactness = mean(
        [item["desvio_padrao_km"] for item in battalion_summaries if item["desvio_padrao_km"] is not None]
    )
    fragmented_cases = count_fragmented_cases(rows, assignments, neighbor_map, matrix_lookup)
    gains = [safe_float(row["ganho_km"]) or 0.0 for row in rows]
    total_gain_vs_current = sum(value for value in gains if value > 0)

    top_gains = sorted(
        [row for row in rows if safe_float(row.get("ganho_km")) is not None],
        key=lambda item: (safe_float(item["ganho_km"]) or 0.0),
        reverse=True,
    )[:10]
    sensitive_cases = sorted(
        rows,
        key=lambda item: (
            abs(safe_float(item.get("diferenca_para_melhor_batalhao_km")) or 9999),
            -(safe_float(item.get("ganho_km")) or 0.0),
        ),
    )[:10]

    summary = {
        "scenario_id": scenario_id,
        "titulo": scenario.get("titulo"),
        "descricao": scenario.get("descricao"),
        "modo_alocacao": mode,
        "batalhoes_ativos": active_battalions,
        "batalhao_metropolitano_escolhido": scenario.get("batalhao_metropolitano_escolhido"),
        "total_distance_km": round(distance_summary["total_km"] or 0.0, 3),
        "average_distance_km": round(distance_summary["media_km"] or 0.0, 3),
        "median_distance_km": round(distance_summary["mediana_km"] or 0.0, 3),
        "p90_distance_km": round(distance_summary["p90_km"] or 0.0, 3),
        "max_distance_km": round(distance_summary["max_km"] or 0.0, 3),
        "centralidade_operacional_km": round(centrality_operacional or 0.0, 3),
        "compactacao_territorial_km": round(compactness or 0.0, 3),
        "casos_fragmentados": fragmented_cases,
        "municipios_redistribuidos": sum(1 for row in rows if row["mudar_batalhao"]),
        "municipios_mantidos": sum(1 for row in rows if not row["mudar_batalhao"]),
        "ganho_total_vs_atual_km": round(total_gain_vs_current, 3),
        "ganhos_significativos": sum(1 for row in rows if row["ganho_significativo"]),
        "municipios_mal_alocados": sum(1 for row in rows if row["mal_alocado_no_cenario_atual"]),
        "distancias_criticas": sum(
            1
            for row in rows
            if (safe_float(row["distancia_rodoviaria_ao_batalhao_cenario_km"]) or 0.0) > EXCESSIVE_DISTANCE_KM
        ),
        "percentual_manutencao_estrutura": round(
            (sum(1 for row in rows if not row["mudar_batalhao"]) / len(rows)) * 100,
            3,
        )
        if rows
        else 0.0,
    }

    return {
        "metadata": {
            "generated_at": now_iso(),
            "stability_margin_km": STABILITY_MARGIN_KM,
            "significant_gain_km": SIGNIFICANT_GAIN_KM,
            "coherence_margin_km": COHERENCE_MARGIN_KM,
        },
        "scenario": summary,
        "batalhoes": battalion_summaries,
        "rankings": {
            "maiores_ganhos": top_gains,
            "casos_sensiveis": sensitive_cases,
        },
        "municipios": rows,
    }


def main() -> None:
    logger = build_logger("avaliar_cenarios")
    ensure_runtime_dirs()
    records = load_normalized_records()
    record_index = build_record_index(records)
    matrix_lookup = matrix_to_lookup(load_json(MATRIX_JSON_PATH))
    scenario_defs = load_scenarios()["cenarios"]
    neighbor_map = build_neighbor_map(records, NEIGHBOR_COUNT_FOR_COHERENCE)

    results: dict[str, dict[str, object]] = {}
    for scenario_id, scenario in scenario_defs.items():
        logger.info("Avaliando %s", scenario_id)
        result = evaluate_scenario(
            scenario_id=scenario_id,
            scenario=scenario,
            records=records,
            matrix_lookup=matrix_lookup,
            neighbor_map=neighbor_map,
        )
        results[scenario_id] = result
        write_json(SCENARIO_OUTPUTS[scenario_id], result)

    current_summary = results["cenario_atual"]["scenario"]
    candidate_summaries = {
        scenario_id: results[scenario_id]["scenario"]
        for scenario_id in ("cenario_eusebio", "cenario_horizonte")
    }
    ordered_candidates = sorted(candidate_summaries.values(), key=rank_scenario_tuple)
    winner_summary = ordered_candidates[0]
    winner_id = str(winner_summary["scenario_id"])
    winner_meta = scenario_defs[winner_id]
    alternate_summary = ordered_candidates[1]
    current_total = safe_float(current_summary["total_distance_km"]) or 0.0
    winner_total = safe_float(winner_summary["total_distance_km"]) or 0.0
    gain_vs_current = current_total - winner_total
    gain_pct = (gain_vs_current / current_total * 100) if current_total else 0.0

    comparison_rows: list[dict[str, object]] = []
    for scenario_id, result in results.items():
        summary = result["scenario"]
        comparison_rows.append(
            {
                "scenario_id": scenario_id,
                "titulo": summary["titulo"],
                "batalhao_metropolitano_escolhido": summary["batalhao_metropolitano_escolhido"],
                "total_distance_km": summary["total_distance_km"],
                "average_distance_km": summary["average_distance_km"],
                "p90_distance_km": summary["p90_distance_km"],
                "max_distance_km": summary["max_distance_km"],
                "centralidade_operacional_km": summary["centralidade_operacional_km"],
                "compactacao_territorial_km": summary["compactacao_territorial_km"],
                "casos_fragmentados": summary["casos_fragmentados"],
                "municipios_redistribuidos": summary["municipios_redistribuidos"],
                "ganho_total_vs_atual_km": summary["ganho_total_vs_atual_km"],
                "ganhos_significativos": summary["ganhos_significativos"],
                "distancias_criticas": summary["distancias_criticas"],
                "recomendado": scenario_id == winner_id,
            }
        )

    winner_centrality = safe_float(winner_summary["centralidade_operacional_km"]) or 0.0
    alternate_centrality = safe_float(alternate_summary["centralidade_operacional_km"]) or 0.0
    winner_total_distance = safe_float(winner_summary["total_distance_km"]) or 0.0
    alternate_total_distance = safe_float(alternate_summary["total_distance_km"]) or 0.0
    total_distance_delta = alternate_total_distance - winner_total_distance
    centrality_sentence = (
        f"Centralidade operacional também favoreceu o cenário vencedor ({winner_centrality:.1f} km)."
        if winner_centrality <= alternate_centrality
        else (
            "Centralidade operacional ficou tecnicamente próxima ao cenário alternativo "
            f"({winner_centrality:.1f} km no vencedor vs {alternate_centrality:.1f} km no cenário concorrente)."
        )
    )

    recommendation = {
        "scenario_id": winner_id,
        "titulo": winner_summary["titulo"],
        "batalhao_metropolitano_escolhido": winner_meta.get("batalhao_metropolitano_escolhido"),
        "ganho_total_vs_atual_km": round(gain_vs_current, 3),
        "ganho_percentual_vs_atual": round(gain_pct, 3),
        "justificativa": [
            (
                "Menor distância rodoviária total entre os cenários testados: "
                f"{winner_summary['total_distance_km']:.1f} km, com vantagem de {total_distance_delta:.1f} km "
                f"sobre {alternate_summary['titulo']}."
            ),
            centrality_sentence,
            f"Menor nível de fragmentação territorial relevante: {winner_summary['casos_fragmentados']} casos.",
            "Critério de desempate final: preservação estrutural quando o ganho rodoviário foi marginal.",
        ],
    }

    comparison_payload = {
        "metadata": {
            "generated_at": now_iso(),
            "stability_margin_km": STABILITY_MARGIN_KM,
            "significant_gain_km": SIGNIFICANT_GAIN_KM,
            "coherence_margin_km": COHERENCE_MARGIN_KM,
        },
        "cenarios": {scenario_id: result["scenario"] for scenario_id, result in results.items()},
        "ranking_operacional": sorted(comparison_rows, key=rank_scenario_tuple),
        "recomendacao_final": recommendation,
    }

    write_json(SCENARIO_COMPARISON_JSON_PATH, comparison_payload)
    write_csv(SCENARIO_COMPARISON_CSV_PATH, comparison_rows)
    logger.info("Cenário recomendado: %s", winner_summary["titulo"])


if __name__ == "__main__":
    main()
