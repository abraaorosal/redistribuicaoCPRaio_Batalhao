from __future__ import annotations

from statistics import fmean

from _config import (
    COMPANY_CENTRALITY_WEIGHT,
    COMPANY_CLUSTER_SIZE_THRESHOLD,
    COMPANY_DISTANCE_WEIGHT,
    COMPANY_EFETIVO_WEIGHT,
    COMPANY_POPULATION_WEIGHT,
    COMPANY_PROMOTION_DISTANCE_THRESHOLD_KM,
    COMPANY_TIE_COUNT_WEIGHT,
    COMPANY_TIE_COVERAGE_WEIGHT,
    COMPANY_TIE_DISTANCE_WEIGHT,
    COMPANY_TIE_EFETIVO_WEIGHT,
    COMPANY_TIE_MARGIN_KM,
    COMPANY_TIE_POPULATION_WEIGHT,
)
from _shared import (
    FINAL_STRUCTURE_CSV_PATH,
    FINAL_STRUCTURE_JSON_PATH,
    ISOLATED_BATTALION_TYPE,
    ISOLATED_BATTALION_FORMAL_COMPANIES,
    MATRIX_JSON_PATH,
    OUTPUT_DIR,
    SCENARIO_COMPARISON_JSON_PATH,
    build_logger,
    ensure_runtime_dirs,
    get_manual_company_overrides_for_battalion,
    get_distance_km,
    is_isolated_battalion,
    load_current_structure_company_keys,
    load_json,
    now_iso,
    safe_float,
    title_key,
    write_csv,
    write_json,
)


SCENARIO_PATHS = {
    "cenario_atual": OUTPUT_DIR / "cenario_atual_avaliado.json",
    "cenario_eusebio": OUTPUT_DIR / "cenario_eusebio_avaliado.json",
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

    row_index = {str(row["municipio"]): row for row in battalion_rows}
    candidates = [row["municipio"] for row in battalion_rows if row["municipio"] not in existing_seeds]
    chosen: set[str] = set()

    for _ in range(extra_needed):
        ranked_metrics: list[dict[str, object]] = []
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
            row_data = row_index.get(candidate, {})
            ranked_metrics.append(
                {
                    "candidate": candidate,
                    "peer_mean_distance": fmean(peer_distances),
                    "seat_distance": candidate_to_seat,
                    "population": safe_float(row_data.get("populacao_ibge")) or 0.0,
                    "efetivo": safe_float(row_data.get("efetivo")) or 0.0,
                }
            )

        if not ranked_metrics:
            break
        score_by_candidate = build_company_candidate_score_map(ranked_metrics)
        ranked_metrics.sort(
            key=lambda item: (
                -score_by_candidate[str(item["candidate"])],
                item["peer_mean_distance"],
                -item["seat_distance"],
                -item["population"],
                -item["efetivo"],
                str(item["candidate"]),
            )
        )
        chosen.add(str(ranked_metrics[0]["candidate"]))

    return chosen


def normalize_metric_map(metric_by_candidate: dict[str, float], *, reverse: bool = False) -> dict[str, float]:
    if not metric_by_candidate:
        return {}

    values = list(metric_by_candidate.values())
    metric_min = min(values)
    metric_max = max(values)
    if metric_max == metric_min:
        return {candidate: 1.0 for candidate in metric_by_candidate}

    output = {}
    for candidate, value in metric_by_candidate.items():
        normalized = (value - metric_min) / (metric_max - metric_min)
        output[candidate] = 1.0 - normalized if reverse else normalized
    return output


def build_company_candidate_score_map(metrics: list[dict[str, object]]) -> dict[str, float]:
    peer_centrality = normalize_metric_map(
        {str(item["candidate"]): float(item["peer_mean_distance"]) for item in metrics},
        reverse=True,
    )
    seat_distance = normalize_metric_map({str(item["candidate"]): float(item["seat_distance"]) for item in metrics})
    population = normalize_metric_map({str(item["candidate"]): float(item["population"]) for item in metrics})
    efetivo = normalize_metric_map({str(item["candidate"]): float(item["efetivo"]) for item in metrics})

    total_weight = (
        COMPANY_CENTRALITY_WEIGHT
        + COMPANY_DISTANCE_WEIGHT
        + COMPANY_POPULATION_WEIGHT
        + COMPANY_EFETIVO_WEIGHT
    ) or 1.0

    return {
        str(item["candidate"]): (
            (COMPANY_CENTRALITY_WEIGHT * peer_centrality.get(str(item["candidate"]), 0.0))
            + (COMPANY_DISTANCE_WEIGHT * seat_distance.get(str(item["candidate"]), 0.0))
            + (COMPANY_POPULATION_WEIGHT * population.get(str(item["candidate"]), 0.0))
            + (COMPANY_EFETIVO_WEIGHT * efetivo.get(str(item["candidate"]), 0.0))
        )
        / total_weight
        for item in metrics
    }


def choose_company_seed(
    municipio: str,
    *,
    batalhao: str,
    current_company: str | None,
    company_seeds: set[str],
    matrix_lookup: dict[str, dict[str, dict[str, object]]],
    row_data: dict[str, object],
    company_assignment_state: dict[str, dict[str, float]],
) -> tuple[str, str]:
    if municipio in company_seeds:
        return municipio, "municipio_definido_como_companhia"

    candidate_distances: list[tuple[str, float]] = []
    for seed in sorted(company_seeds):
        distance = get_distance_km(matrix_lookup, municipio, seed)
        if distance is None:
            continue
        candidate_distances.append((seed, distance))

    if not candidate_distances:
        return batalhao, "sem_distancia_companhia_valida"

    candidate_distances.sort(key=lambda item: (item[1], item[0]))
    best_seed, best_distance = candidate_distances[0]
    near_tie_candidates = [
        (seed, distance)
        for seed, distance in candidate_distances
        if distance - best_distance <= COMPANY_TIE_MARGIN_KM
    ]
    if len(near_tie_candidates) == 1:
        return best_seed, "companhia_mais_proxima_por_distancia_rodoviaria"

    municipio_populacao = safe_float(row_data.get("populacao_ibge")) or 0.0
    municipio_efetivo = safe_float(row_data.get("efetivo")) or 0.0
    tie_metrics: list[dict[str, object]] = []
    for seed, distance in near_tie_candidates:
        seed_state = company_assignment_state.get(seed, {})
        current_radius = safe_float(seed_state.get("coverage_radius_km")) or 0.0
        current_population = safe_float(seed_state.get("covered_population")) or 0.0
        current_efetivo = safe_float(seed_state.get("covered_efetivo")) or 0.0
        current_count = safe_float(seed_state.get("covered_count")) or 0.0
        tie_metrics.append(
            {
                "seed": seed,
                "distance": distance,
                "projected_radius": max(current_radius, distance),
                "projected_population": current_population + municipio_populacao,
                "projected_efetivo": current_efetivo + municipio_efetivo,
                "projected_count": current_count + 1.0,
            }
        )

    distance_score = normalize_metric_map({str(item["seed"]): float(item["distance"]) for item in tie_metrics})
    coverage_score = normalize_metric_map(
        {str(item["seed"]): float(item["projected_radius"]) for item in tie_metrics}
    )
    efetivo_score = normalize_metric_map(
        {str(item["seed"]): float(item["projected_efetivo"]) for item in tie_metrics}
    )
    population_score = normalize_metric_map(
        {str(item["seed"]): float(item["projected_population"]) for item in tie_metrics}
    )
    count_score = normalize_metric_map({str(item["seed"]): float(item["projected_count"]) for item in tie_metrics})

    total_weight = (
        COMPANY_TIE_DISTANCE_WEIGHT
        + COMPANY_TIE_COVERAGE_WEIGHT
        + COMPANY_TIE_EFETIVO_WEIGHT
        + COMPANY_TIE_POPULATION_WEIGHT
        + COMPANY_TIE_COUNT_WEIGHT
    ) or 1.0
    tie_score: dict[str, float] = {}
    for item in tie_metrics:
        seed = str(item["seed"])
        tie_score[seed] = (
            (COMPANY_TIE_DISTANCE_WEIGHT * distance_score.get(seed, 0.0))
            + (COMPANY_TIE_COVERAGE_WEIGHT * coverage_score.get(seed, 0.0))
            + (COMPANY_TIE_EFETIVO_WEIGHT * efetivo_score.get(seed, 0.0))
            + (COMPANY_TIE_POPULATION_WEIGHT * population_score.get(seed, 0.0))
            + (COMPANY_TIE_COUNT_WEIGHT * count_score.get(seed, 0.0))
        ) / total_weight

    tie_metrics.sort(
        key=lambda item: (
            tie_score[str(item["seed"])],
            item["distance"],
            item["projected_radius"],
            item["projected_efetivo"],
            item["projected_population"],
            item["projected_count"],
            str(item["seed"]),
        )
    )
    return str(tie_metrics[0]["seed"]), "companhia_desempate_tecnico_operacional"


def build_company_assignment_state(
    company_seeds: set[str],
    row_index: dict[str, dict[str, object]],
) -> dict[str, dict[str, float]]:
    state: dict[str, dict[str, float]] = {}
    for seed in company_seeds:
        row = row_index.get(seed, {})
        state[seed] = {
            "coverage_radius_km": 0.0,
            "covered_population": safe_float(row.get("populacao_ibge")) or 0.0,
            "covered_efetivo": safe_float(row.get("efetivo")) or 0.0,
            "covered_count": 1.0,
        }
    return state


def update_company_assignment_state(
    seed: str,
    municipio: str,
    *,
    company_assignment_state: dict[str, dict[str, float]],
    row_index: dict[str, dict[str, object]],
    matrix_lookup: dict[str, dict[str, dict[str, object]]],
) -> None:
    seed_state = company_assignment_state.setdefault(
        seed,
        {
            "coverage_radius_km": 0.0,
            "covered_population": 0.0,
            "covered_efetivo": 0.0,
            "covered_count": 0.0,
        },
    )
    distance = get_distance_km(matrix_lookup, municipio, seed) or 0.0
    row = row_index.get(municipio, {})
    seed_state["coverage_radius_km"] = max(safe_float(seed_state.get("coverage_radius_km")) or 0.0, distance)
    seed_state["covered_population"] = (safe_float(seed_state.get("covered_population")) or 0.0) + (
        safe_float(row.get("populacao_ibge")) or 0.0
    )
    seed_state["covered_efetivo"] = (safe_float(seed_state.get("covered_efetivo")) or 0.0) + (
        safe_float(row.get("efetivo")) or 0.0
    )
    seed_state["covered_count"] = (safe_float(seed_state.get("covered_count")) or 0.0) + 1.0


def company_seed_sort_key(
    batalhao: str,
    seed: str,
    matrix_lookup: dict[str, dict[str, dict[str, object]]],
) -> tuple[int, float, str]:
    if seed == batalhao:
        return (0, 0.0, seed)
    distance = get_distance_km(matrix_lookup, batalhao, seed)
    return (1, distance if distance is not None else float("inf"), seed)


def pelotao_sort_key(
    company_seed: str,
    pelotao: str,
    matrix_lookup: dict[str, dict[str, dict[str, object]]],
) -> tuple[float, str]:
    distance = get_distance_km(matrix_lookup, company_seed, pelotao)
    return (distance if distance is not None else float("inf"), pelotao)


def main() -> None:
    logger = build_logger("estruturar_hierarquia")
    ensure_runtime_dirs()
    comparison, recommendation, scenario_payload = load_recommended_scenario()
    matrix_lookup = load_json(MATRIX_JSON_PATH)["matrix"]
    current_structure_company_keys = load_current_structure_company_keys()

    active_battalions = scenario_payload["scenario"]["batalhoes_ativos"]
    rows = scenario_payload["municipios"]
    battalion_rows_map = {
        batalhao: [row for row in rows if row["batalhao_cenario"] == batalhao]
        for batalhao in active_battalions
    }

    company_seeds_by_battalion: dict[str, set[str]] = {}
    company_seed_origin: dict[tuple[str, str], str] = {}
    for batalhao, battalion_rows in battalion_rows_map.items():
        batalhao_isolado = is_isolated_battalion(batalhao)
        manual_company_overrides = get_manual_company_overrides_for_battalion(batalhao)
        existing = {
            row["municipio"]
            for row in battalion_rows
            if row["municipio"] == batalhao
            or row["status_atual"] in {"companhia", "cia_independente"}
            or title_key(row["municipio"]) in manual_company_overrides
            or title_key(row["municipio"]) in current_structure_company_keys
        }
        existing.add(batalhao)
        extra = (
            set()
            if batalhao_isolado
            else choose_additional_company_seeds(batalhao, battalion_rows, matrix_lookup, existing)
        )
        seeds = existing | extra
        company_seeds_by_battalion[batalhao] = seeds
        for seed in seeds:
            if seed == batalhao:
                company_seed_origin[(batalhao, seed)] = "sede_batalhao"
            elif title_key(seed) in manual_company_overrides:
                company_seed_origin[(batalhao, seed)] = "companhia_fixa_regra_manual"
            elif title_key(seed) in current_structure_company_keys:
                company_seed_origin[(batalhao, seed)] = "companhia_preservada_estrutura_atual"
            elif seed in extra:
                company_seed_origin[(batalhao, seed)] = "companhia_sugerida_por_score_operacional"
            else:
                company_seed_origin[(batalhao, seed)] = "companhia_preservada"

    final_rows: list[dict[str, object]] = []
    batalhoes_output: list[dict[str, object]] = []

    for batalhao in active_battalions:
        battalion_rows = battalion_rows_map[batalhao]
        company_seeds = company_seeds_by_battalion[batalhao]
        row_index = {str(row["municipio"]): row for row in battalion_rows}
        ordered_company_seeds = sorted(
            company_seeds,
            key=lambda seed: company_seed_sort_key(batalhao, seed, matrix_lookup),
        )
        companies_map: dict[str, list[str]] = {seed: [] for seed in company_seeds}
        company_assignment_state = build_company_assignment_state(company_seeds, row_index)
        pelotoes_diretos: list[str] = []
        batalhao_isolado = is_isolated_battalion(batalhao)
        manual_company_overrides = get_manual_company_overrides_for_battalion(batalhao)

        ordered_rows = sorted(
            battalion_rows,
            key=lambda item: (
                0
                if item["municipio"] in company_seeds
                or item["municipio"] == batalhao
                or title_key(item["municipio"]) in manual_company_overrides
                else 1,
                0
                if item["municipio"] in company_seeds
                or item["municipio"] == batalhao
                or title_key(item["municipio"]) in manual_company_overrides
                else -(
                    min(
                        (
                            get_distance_km(matrix_lookup, item["municipio"], seed)
                            for seed in company_seeds
                            if get_distance_km(matrix_lookup, item["municipio"], seed) is not None
                        ),
                        default=0.0,
                    )
                ),
                item["municipio"],
            ),
        )

        for row in ordered_rows:
            municipio = row["municipio"]
            current_company = row.get("companhia_atual")
            municipio_isolado = (
                bool(row.get("is_fortaleza"))
                or row.get("tipo_especial") == ISOLATED_BATTALION_TYPE
                or is_isolated_battalion(municipio)
            )
            company_seed, company_reason = choose_company_seed(
                municipio,
                batalhao=batalhao,
                current_company=current_company,
                company_seeds=company_seeds,
                matrix_lookup=matrix_lookup,
                row_data=row,
                company_assignment_state=company_assignment_state,
            )

            if municipio_isolado and municipio == batalhao:
                status_sugerido = "batalhao"
                companhia_sugerida = batalhao
                company_reason = "batalhao_isolado"
            elif municipio == batalhao:
                status_sugerido = "batalhao"
                companhia_sugerida = batalhao
                company_reason = "sede_batalhao"
            elif title_key(municipio) in manual_company_overrides:
                status_sugerido = "companhia"
                companhia_sugerida = municipio
                company_reason = "companhia_fixa_regra_manual"
            elif municipio in company_seeds:
                status_sugerido = "companhia"
                companhia_sugerida = municipio
            else:
                status_sugerido = "pelotao"
                companhia_sugerida = company_seed

            if status_sugerido == "pelotao":
                companies_map.setdefault(companhia_sugerida, []).append(municipio)
                update_company_assignment_state(
                    companhia_sugerida,
                    municipio,
                    company_assignment_state=company_assignment_state,
                    row_index=row_index,
                    matrix_lookup=matrix_lookup,
                )

            justificativa = row["justificativa_tecnica"]
            if status_sugerido == "companhia" and row["status_atual"] == "pelotao":
                if company_reason == "companhia_fixa_regra_manual":
                    justificativa += (
                        f" Município fixado como companhia de {batalhao} por regra operacional explícita."
                    )
                else:
                    justificativa += (
                        f" Município promovido a companhia para reduzir dispersão interna de {batalhao}, "
                        "com score operacional composto por distância, população oficial e efetivo."
                    )
            elif status_sugerido == "pelotao":
                if company_reason == "companhia_desempate_tecnico_operacional":
                    justificativa += (
                        f" Subordinação sugerida à companhia {companhia_sugerida} por desempate técnico entre "
                        "companhias muito próximas, priorizando compactação territorial, carga de efetivo, "
                        "população coberta e balanceamento operacional."
                    )
                else:
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
                "populacao_ibge": row.get("populacao_ibge"),
                "populacao_ano_referencia": row.get("populacao_ano_referencia"),
                "efetivo": row.get("efetivo"),
                "tipo_especial": row.get("tipo_especial"),
                "is_fortaleza": bool(row.get("is_fortaleza")),
            }
            if municipio_isolado:
                final_row["subordinados"] = []
            final_rows.append(final_row)

        subordinados = sorted(
            pelotao for pelotoes in companies_map.values() for pelotao in pelotoes
        )
        companhias_output = [
            {
                "companhia": companhia,
                "origem_sugestao": company_seed_origin[(batalhao, companhia)],
                "pelotoes": sorted(
                    companies_map.get(companhia, []),
                    key=lambda pelotao: pelotao_sort_key(companhia, pelotao, matrix_lookup),
                ),
            }
            for companhia in ordered_company_seeds
        ]
        if batalhao_isolado:
            companhias_output = [
                {
                    "companhia": item["companhia"],
                    "origem_sugestao": item["origem_sugestao"],
                    "pelotoes": [],
                }
                for item in ISOLATED_BATTALION_FORMAL_COMPANIES
            ]
        batalhoes_output.append(
            {
                "batalhao": batalhao,
                "municipio_sede": batalhao,
                "tipo_especial": ISOLATED_BATTALION_TYPE if batalhao_isolado else None,
                "companhias": companhias_output,
                "pelotoes_diretos_batalhao": sorted(pelotoes_diretos),
                "subordinados": subordinados,
                "municipios_total": len(battalion_rows),
                "redistribuidos_recebidos": sum(
                    1 for row in battalion_rows if row["batalhao_atual"] != batalhao
                ),
            }
        )
        if batalhao_isolado:
            logger.info("Fortaleza mantida na hierarquia final como batalhão isolado, sem subordinados.")

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
