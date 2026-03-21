from __future__ import annotations

from _shared import (
    ANALYTICAL_REPORT_CSV_PATH,
    ANALYTICAL_REPORT_JSON_PATH,
    FINAL_STRUCTURE_JSON_PATH,
    SCENARIO_COMPARISON_JSON_PATH,
    build_logger,
    ensure_runtime_dirs,
    flatten_summary_for_csv,
    load_json,
    now_iso,
    safe_float,
    write_csv,
    write_json,
)


def main() -> None:
    logger = build_logger("gerar_relatorio_analitico")
    ensure_runtime_dirs()

    comparison = load_json(SCENARIO_COMPARISON_JSON_PATH)
    final_structure = load_json(FINAL_STRUCTURE_JSON_PATH)
    recommendation = comparison["recomendacao_final"]
    scenario_id = recommendation["scenario_id"]
    scenario_summary = comparison["cenarios"][scenario_id]

    municipios = final_structure["municipios"]
    redistribuidos = [row for row in municipios if row["mudar_batalhao"] == "sim"]
    mantidos = [row for row in municipios if row["mudar_batalhao"] == "nao"]
    ranking_ganhos = sorted(
        municipios,
        key=lambda row: safe_float(row.get("ganho_km")) or 0.0,
        reverse=True,
    )[:15]
    ranking_sensiveis = sorted(
        municipios,
        key=lambda row: (
            row.get("mudar_batalhao") != "sim",
            -(safe_float(row.get("ganho_km")) or 0.0),
            row["municipio"],
        ),
    )[:15]

    payload = {
        "metadata": {
            "generated_at": now_iso(),
            "cenario_recomendado": scenario_id,
        },
        "resumo_cenarios": comparison["cenarios"],
        "recomendacao_final": recommendation,
        "totais": {
            "total_km_cenario_atual": comparison["cenarios"]["cenario_atual"]["total_distance_km"],
            **{
                f"total_km_{scenario_key}": summary["total_distance_km"]
                for scenario_key, summary in comparison["cenarios"].items()
                if scenario_key != "cenario_atual"
            },
            "municipios_redistribuidos": len(redistribuidos),
            "municipios_mantidos": len(mantidos),
            "ganho_logistico_total_km": recommendation["ganho_total_vs_atual_km"],
        },
        "ranking_maiores_ganhos": ranking_ganhos,
        "ranking_casos_sensiveis": ranking_sensiveis,
        "municipios_redistribuidos": redistribuidos,
        "municipios_mantidos": mantidos,
        "justificativa_consolidada": {
            "distancia_total": f"Cenário recomendado com {scenario_summary['total_distance_km']:.1f} km totais.",
            "centralidade": f"Centralidade operacional média de {scenario_summary['centralidade_operacional_km']:.1f} km.",
            "coerencia_territorial": f"{scenario_summary['casos_fragmentados']} casos fragmentados relevantes após estabilização.",
            "preservacao_estrutura": f"{scenario_summary['percentual_manutencao_estrutura']:.1f}% da estrutura atual foi preservada no nível de batalhão.",
        },
        "observacoes_precisao": [
            "O critério principal de alocação entre batalhões usa distância rodoviária real obtida via OSRM até a sede do batalhão.",
            "Pelotões são tratados como nós flutuantes na etapa de roteamento entre batalhões; a reconstrução de companhias ocorre apenas depois da formação do cluster do batalhão.",
            "A etapa final de estruturação de companhias combina distância rodoviária, população oficial do IBGE e efetivo para manter coerência interna.",
            "Regras de negócio fixas prevalecem sobre o score automático quando explicitamente definidas, como Paracuru em Caucaia e a preservação das companhias da estrutura atual da unidade usada como referência do estudo.",
            "Restrição administrativa metropolitana aplicada: Caucaia e Eusébio só recebem municípios da Região Metropolitana.",
            "A precisão final depende da qualidade do grafo OSM disponível no endpoint OSRM utilizado.",
        ],
    }

    csv_rows = []
    for scenario_key, summary in comparison["cenarios"].items():
        row = {"secao": "cenario_metricas", "scenario_id": scenario_key}
        row.update(summary)
        csv_rows.append(row)

    for row in ranking_ganhos:
        csv_rows.append({"secao": "ranking_ganhos", **row})
    for row in ranking_sensiveis:
        csv_rows.append({"secao": "ranking_sensiveis", **row})
    for row in redistribuidos:
        csv_rows.append({"secao": "municipios_redistribuidos", **row})
    for row in mantidos:
        csv_rows.append({"secao": "municipios_mantidos", **row})
    csv_rows.extend(flatten_summary_for_csv("recomendacao_final", recommendation))

    write_json(ANALYTICAL_REPORT_JSON_PATH, payload)
    write_csv(ANALYTICAL_REPORT_CSV_PATH, csv_rows)
    logger.info("Relatório analítico consolidado gerado.")


if __name__ == "__main__":
    main()
