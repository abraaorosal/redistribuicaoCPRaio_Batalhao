from __future__ import annotations

import time

import requests

from _config import NOMINATIM_BASE_URL, NOMINATIM_USER_AGENT, REQUEST_TIMEOUT
from _shared import (
    COMPLEMENTARY_COORDS_PATH,
    build_logger,
    ensure_runtime_dirs,
    is_valid_coordinate,
    load_normalized_records,
    now_iso,
    persist_normalized_records,
    safe_float,
    title_key,
    write_json,
)


def geocode_name(logger, nome: str) -> dict[str, float | str] | None:
    params = {
        "q": f"{nome}, Ceará, Brasil",
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "br",
    }
    response = requests.get(
        NOMINATIM_BASE_URL,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": NOMINATIM_USER_AGENT},
    )
    response.raise_for_status()
    payload = response.json()
    if not payload:
        logger.warning("Nominatim sem resultado para %s", nome)
        return None

    best = payload[0]
    latitude = safe_float(best.get("lat"))
    longitude = safe_float(best.get("lon"))
    if not is_valid_coordinate(latitude, longitude):
        logger.warning("Resultado inválido para %s: %s", nome, best)
        return None

    return {
        "nome": nome,
        "latitude": latitude,
        "longitude": longitude,
        "display_name": best.get("display_name"),
        "fonte": "Nominatim/OpenStreetMap",
    }


def main() -> None:
    logger = build_logger("geocodificar_complementares")
    ensure_runtime_dirs()
    records = load_normalized_records()
    pending = [
        item for item in records if not is_valid_coordinate(item.get("latitude"), item.get("longitude"))
    ]

    complements: list[dict[str, float | str]] = []
    if not pending:
        logger.info("Nenhum município sem coordenadas válidas. Nenhuma geocodificação necessária.")
    else:
        for index, item in enumerate(pending, start=1):
            logger.info("Consultando Nominatim (%s/%s): %s", index, len(pending), item["nome"])
            result = geocode_name(logger, item["nome"])
            if result:
                complements.append(result)
            time.sleep(1.0)

    complement_payload = {
        "generated_at": now_iso(),
        "municipios": complements,
    }
    write_json(COMPLEMENTARY_COORDS_PATH, complement_payload)

    by_name = {title_key(item["nome"]): item for item in complements}
    merged: list[dict[str, object]] = []
    for item in records:
        replacement = by_name.get(title_key(item["nome"]))
        if replacement and not is_valid_coordinate(item.get("latitude"), item.get("longitude")):
            item = {
                **item,
                "latitude": replacement["latitude"],
                "longitude": replacement["longitude"],
                "fonte_coordenadas": "Nominatim/OpenStreetMap",
            }
        merged.append(item)

    persist_normalized_records(
        merged,
        metadata_extra={
            "geocodificacao_complementar": {
                "municipios_consultados": [item["nome"] for item in pending],
                "municipios_enriquecidos": [item["nome"] for item in complements],
            }
        },
    )


if __name__ == "__main__":
    main()
