from __future__ import annotations

from _config import IBGE_POPULATION_STATE_CODE, IBGE_POPULATION_YEAR
from _shared import (
    IBGE_POPULATION_JSON_PATH,
    POPULATION_DIR,
    build_logger,
    ensure_runtime_dirs,
    now_iso,
    title_key,
    write_json,
)

import requests


IBGE_POPULATION_API_URL = (
    f"https://apisidra.ibge.gov.br/values/t/6579/n6/in%20n3%20{IBGE_POPULATION_STATE_CODE}/v/9324/p/{IBGE_POPULATION_YEAR}?formato=json"
)
IBGE_POPULATION_NEWS_URL = (
    "https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/"
    "44305-populacao-estimada-do-pais-chega-a-213-4-milhoes-de-habitantes-em-2025"
)


def main() -> None:
    logger = build_logger("atualizar_populacao_ibge")
    ensure_runtime_dirs()
    POPULATION_DIR.mkdir(parents=True, exist_ok=True)

    response = requests.get(IBGE_POPULATION_API_URL, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or len(payload) <= 1:
        raise RuntimeError("Resposta do SIDRA/IBGE inválida para população municipal.")

    municipios = []
    for row in payload[1:]:
        municipio = str(row.get("D1N") or "").replace(" - CE", "").strip()
        if not municipio:
            continue
        municipios.append(
            {
                "municipio": municipio,
                "municipio_normalizado": title_key(municipio),
                "codigo_ibge": str(row.get("D1C") or "").strip(),
                "populacao_estimada": int(float(row.get("V") or 0)),
                "ano_referencia": IBGE_POPULATION_YEAR,
                "data_referencia": f"{IBGE_POPULATION_YEAR}-07-01",
                "fonte_api": IBGE_POPULATION_API_URL,
                "fonte_noticia": IBGE_POPULATION_NEWS_URL,
            }
        )

    output = {
        "metadata": {
            "generated_at": now_iso(),
            "estado_ibge": IBGE_POPULATION_STATE_CODE,
            "ano_referencia": IBGE_POPULATION_YEAR,
            "data_referencia": f"{IBGE_POPULATION_YEAR}-07-01",
            "fonte_api": IBGE_POPULATION_API_URL,
            "fonte_noticia": IBGE_POPULATION_NEWS_URL,
            "descricao": (
                "Estimativas oficiais da população residente dos municípios do Ceará, "
                "com data de referência em 1º de julho, obtidas no SIDRA/IBGE."
            ),
        },
        "municipios": sorted(municipios, key=lambda item: item["municipio"]),
    }
    write_json(IBGE_POPULATION_JSON_PATH, output)
    logger.info(
        "População oficial IBGE atualizada com %s municípios do Ceará para %s.",
        len(output["municipios"]),
        IBGE_POPULATION_YEAR,
    )


if __name__ == "__main__":
    main()
