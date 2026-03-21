from __future__ import annotations

from statistics import fmean

from _config import (
    COMPANY_CLUSTER_SIZE_THRESHOLD,
    COMPANY_PROMOTION_DISTANCE_THRESHOLD_KM,
    STABILITY_MARGIN_KM,
)
from _shared import (
    FINAL_STRUCTURE_CSV_PATH,
    FINAL_STRUCTURE_JSON_PATH,
    MATRIX_JSON_PATH,
    OUTPUT_DIR,
    SCENARIO_COMPARISON_JSON_PATH,
    build_logger,
    ensure_runtime_dirs,
    get_distance_km,
    load_json,
    now_iso,
    safe_float,
    write_csv,
    write_json,
)


SCENARIO_PATHS = {
    "cenario_atual": OUTPUT_DIR / "cenario_atual_avaliado.json",
    "cenario_eusebio": OUTPUT_DIR / "cenario_eusebio_avaliado.json",
    "cenario_horizonte": OUTPUT_DIR / "cenario_horizonte_avaliado.json",
}


def load_recommended_scenario():
    comparison = load_json(SCENARIO_COMPARISON_JSON_PATH)
    recommendation = comparison["recomendacao_final"]
    scenario_id = recommendation["scenario_id"]
    scenario_payload = load_json(SCENARIO_PATHS[scenario_id])
    return comparison, recommendation, scenario_payload


def choose_additional_company_seeds(
    batalhao: str,
    battalion_rows: list[dict[str, object]],
    matrix_lookup: dict[str, dict[str, dict[str, object]]],
    existing_seeds: set[str],
) -> set[str]:
    # Promove polos internos apenas quando a malha do batalhão fica extensa demais para operar direto da sede.
    distances_from_seat = [
        safe_float(row.get("distancia_rodoviaria_ao_batalhao_cenario_km")) or 0.0 for row in battalion_rows
    ]
    max_distance = max(distances_from_seat) if distances_from_seat else 0.0
    non_seat_existing = {seed for seed in existing_seeds if seed != batalhao}

    extra_needed = 0
    if (
        len(battalion_rows) >= COMPANY_CLUSTER_SIZE_THRESHOLD
        and not non_seat_existing
        and max_distance >= COMPANY_PROMOTION_DISTANCE_THRESHOLD_KM
    ):
        extra_needed = 1
    if (
        len(battalion_rows) >= COMPANY_CLUSTER_SIZE_THRESHOLD + 5
        and len(non_seat_existing) + extra_needed < 2
        and max_distance >= COMPANY_PROMOTION_DISTANCE_THRESHOLD_KM + 20
    ):
        extra_needed += 1

    if extra_needed <= 0:
        return set()

    candidates = [
        row["municipio"]
        for row in battalion_rows
        if row["municipio"] not in existing_seeds
    ]
    chosen: set[str] = set()

    for _ in range(extra_needed):
        ranked: list[tuple[float, float, str]] = []
        for candidate in candidates:
            if candidate in chosen:
                continue
            candidate_to_seat = get_distance_km(matrix_lookup, candidate, batalhao) or 0.0
            if max_distance >= COMPANY_PROMOTION_DISTANCE_THRESHOLD_KM and candidate_to_seat < (
                COMPANY_PROMOTION_DISTANCE_THRESHOLD_KM / 1.6
            ):
                continue
            peer_distances = []
            for row in battalion_rows:
                if row["municipio"] == candidate:
                    continue
                distance = get_distance_km(matrix_lookup, candidate, row["municipio"])
                if distance is not None:
                    peer_distances.append(distance)
            if not peer_distances:
                continue
            ranked.append((fmean(peer_distances), -candidate_to_seat, candidate))

        if not ranked:
            break
        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        chosen.add(ranked[0][2])

    return chosen


def choose_company_seed(
    municipio: str,
    *,
    batalhao: str,
    current_company: str | None,
    company_seeds: set[str],
    matrix_lookup: dict[str, dict[str, dict[str, object]]],
) -> tuple[str, str]:
    # Mantemos a companhia atual quando a diferença para a melhor opção é marginal.
    if municipio in company_seeds:
        return municipio, "municipio_definido_como_companhia"

    best_seed = None
    best_distance = None
    for seed in sorted(company_seeds):
        distance = get_distance_km(matrix_lookup, municipio, seed)
        if distance is None:
            continue
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_seed = seed

    if current_company and current_company in company_seeds:
        current_distance = get_distance_km(matrix_lookup, municipio, current_company)
        if (
            best_seed is not None
            and current_distance is not None
            and best_distance is not None
            and current_distance - best_distance <= STABILITY_MARGIN_KM
        ):
            return current_company, "companhia_mantida_por_estabilidade"

    if best_seed is None:
        return batalhao, "sem_distancia_companhia_valida"
    return best_seed, "companhia_mais_proxima_por_distancia_rodoviaria"


def main() -> None:
    logger = build_logger("estruturar_hierarquia")
    ensure_runtime_dirs()
    comparison, recommendation, scenario_payload = load_recommended_scenario()
    matrix_lookup = load_json(MATRIX_JSON_PATH)["matrix"]

    active_battalions = scenario_payload["scenario"]["batalhoes_ativos"]
    rows = scenario_payload["municipios"]
    battalion_rows_map = {
        batalhao: [row for row in rows if row["batalhao_cenario"] == batalhao]
        for batalhao in active_battalions
    }

    company_seeds_by_battalion: dict[str, set[str]] = {}
    company_seed_origin: dict[tuple[str, str], str] = {}
    for batalhao, battalion_rows in battalion_rows_map.items():
        existing = {
            row["municipio"]
            for row in battalion_rows
            if row["municipio"] == batalhao
            or row["status_atual"] in {"companhia", "cia_independente"}
        }
        existing.add(batalhao)
        extra = choose_additional_company_seeds(batalhao, battalion_rows, matrix_lookup, existing)
        seeds = existing | extra
        company_seeds_by_battalion[batalhao] = seeds
        for seed in seeds:
            if seed == batalhao:
                company_seed_origin[(batalhao, seed)] = "sede_batalhao"
            elif seed in extra:
                company_seed_origin[(batalhao, seed)] = "companhia_sugerida_por_centralidade"
            else:
                company_seed_origin[(batalhao, seed)] = "companhia_preservada"

    final_rows: list[dict[str, object]] = []
    batalhoes_output: list[dict[str, object]] = []

    for batalhao in active_battalions:
        battalion_rows = battalion_rows_map[batalhao]
        company_seeds = company_seeds_by_battalion[batalhao]
        companies_map: dict[str, list[str]] = {seed: [] for seed in company_seeds if seed != batalhao}
        pelotoes_diretos: list[str] = []

        for row in sorted(battalion_rows, key=lambda item: item["municipio"]):
            municipio = row["municipio"]
            current_company = row.get("companhia_atual")
            company_seed, company_reason = choose_company_seed(
                municipio,
                batalhao=batalhao,
                current_company=current_company,
                company_seeds=company_seeds,
                matrix_lookup=matrix_lookup,
            )

            if municipio == batalhao:
                status_sugerido = "batalhao"
                companhia_sugerida = batalhao
                company_reason = "sede_batalhao"
            elif municipio in company_seeds:
                status_sugerido = "companhia"
                companhia_sugerida = municipio
            else:
                status_sugerido = "pelotao"
                companhia_sugerida = company_seed

            if status_sugerido == "pelotao":
                if companhia_sugerida == batalhao:
                    pelotoes_diretos.append(municipio)
                else:
                    companies_map.setdefault(companhia_sugerida, []).append(municipio)

            justificativa = row["justificativa_tecnica"]
            if status_sugerido == "companhia" and row["status_atual"] == "pelotao":
                justificativa += (
                    f" Município promovido a companhia para reduzir dispersão interna de {batalhao} "
                    f"com base na centralidade rodoviária."
                )
            elif status_sugerido == "pelotao":
                justificativa += f" Subordinação sugerida à companhia {companhia_sugerida} ({company_reason})."

            final_row = {
                "municipio": municipio,
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "status_atual": row["status_atual"],
                "status_sugerido": status_sugerido,
                "batalhao_atual": row["batalhao_atual"],
                "batalhao_sugerido": batalhao,
                "companhia_atual": row["companhia_atual"],
                "companhia_sugerida": companhia_sugerida,
                "distancia_rodoviaria_ao_batalhao_atual_km": row["distancia_rodoviaria_ao_batalhao_atual_km"],
                "distancia_rodoviaria_ao_batalhao_sugerido_km": row["distancia_rodoviaria_ao_batalhao_cenario_km"],
                "ganho_km": row["ganho_km"],
                "mudar_batalhao": "sim" if row["mudar_batalhao"] else "nao",
                "mudar_status": "sim" if row["status_atual"] != status_sugerido else "nao",
                "justificativa_tecnica": justificativa,
                "criterio_batalhao": row["criterio_decisao"],
                "criterio_companhia": company_reason,
                "classificacao_analitica": row["classificacao_analitica"],
                "ganho_significativo": row["ganho_significativo"],
            }
            final_rows.append(final_row)

        batalhoes_output.append(
            {
                "batalhao": batalhao,
                "municipio_sede": batalhao,
                "companhias": [
                    {
                        "companhia": companhia,
                        "origem_sugestao": company_seed_origin[(batalhao, companhia)],
                        "pelotoes": sorted(companies_map.get(companhia, [])),
                    }
                    for companhia in sorted(company for company in company_seeds if company != batalhao)
                ],
                "pelotoes_diretos_batalhao": sorted(pelotoes_diretos),
                "municipios_total": len(battalion_rows),
                "redistribuidos_recebidos": sum(
                    1 for row in battalion_rows if row["batalhao_atual"] != batalhao
                ),
            }
        )

    payload = {
        "metadata": {
            "generated_at": now_iso(),
            "scenario_id": recommendation["scenario_id"],
            "titulo": recommendation["titulo"],
            "batalhao_metropolitano_escolhido": recommendation["batalhao_metropolitano_escolhido"],
            "ganho_total_vs_atual_km": recommendation["ganho_total_vs_atual_km"],
        },
        "batalhoes": batalhoes_output,
        "municipios": sorted(final_rows, key=lambda item: item["municipio"]),
    }
    write_json(FINAL_STRUCTURE_JSON_PATH, payload)
    write_csv(FINAL_STRUCTURE_CSV_PATH, payload["municipios"])
    logger.info(
        "Estrutura final sugerida gerada para o cenário recomendado: %s",
        recommendation["titulo"],
    )


if __name__ == "__main__":
    main()
