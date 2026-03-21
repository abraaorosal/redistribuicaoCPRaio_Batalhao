from __future__ import annotations

from _config import OSRM_BATCH_SIZE
from _shared import (
    MATRIX_CSV_PATH,
    MATRIX_JSON_PATH,
    OsrmClient,
    build_logger,
    ensure_runtime_dirs,
    is_valid_coordinate,
    load_normalized_records,
    load_scenarios,
    now_iso,
    write_csv,
    write_json,
)


def main() -> None:
    logger = build_logger("gerar_matriz_osrm")
    ensure_runtime_dirs()

    records = load_normalized_records()
    scenarios = load_scenarios()["cenarios"]
    candidate_battalions = sorted(
        {
            batalhao
            for scenario in scenarios.values()
            for batalhao in scenario.get("batalhoes_ativos", [])
        }
    )

    valid_records = [
        item for item in records if is_valid_coordinate(item.get("latitude"), item.get("longitude"))
    ]
    invalid_records = [item["nome"] for item in records if item not in valid_records]
    logger.info(
        "Gerando matriz OSRM para %s municípios válidos e %s polos candidatos.",
        len(valid_records),
        len(candidate_battalions),
    )
    if invalid_records:
        logger.warning("Municípios ignorados por coordenada inválida: %s", ", ".join(invalid_records))

    client = OsrmClient(logger=logger)
    matrix: dict[str, dict[str, dict[str, float | None]]] = {}

    for start in range(0, len(valid_records), OSRM_BATCH_SIZE):
        batch = valid_records[start : start + OSRM_BATCH_SIZE]
        logger.info(
            "Consultando OSRM para o lote %s-%s de %s.",
            start + 1,
            start + len(batch),
            len(valid_records),
        )
        try:
            batch_output = client.table(batch, valid_records)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Table OSRM falhou no lote. Acionando fallback route: %s", exc)
            batch_output = {}
            for origin in batch:
                bucket: dict[str, dict[str, float | None]] = {}
                for destination in valid_records:
                    if origin["nome"] == destination["nome"]:
                        bucket[destination["nome"]] = {
                            "distance_m": 0.0,
                            "distance_km": 0.0,
                            "duration_s": 0.0,
                            "duration_min": 0.0,
                        }
                        continue
                    bucket[destination["nome"]] = client.route(origin, destination)
                batch_output[origin["nome"]] = bucket
        matrix.update(batch_output)

    for invalid_name in invalid_records:
        matrix[invalid_name] = {
            destination["nome"]: {
                "distance_m": None,
                "distance_km": None,
                "duration_s": None,
                "duration_min": None,
            }
            for destination in records
        }

    csv_rows: list[dict[str, object]] = []
    for origin in records:
        origin_bucket = matrix.get(origin["nome"], {})
        for destination in records:
            route_info = origin_bucket.get(destination["nome"], {})
            csv_rows.append(
                {
                    "municipio_origem": origin["nome"],
                    "municipio_destino": destination["nome"],
                    "destino_eh_batalhao_candidato": destination["nome"] in candidate_battalions,
                    "distance_km": route_info.get("distance_km"),
                    "duration_min": route_info.get("duration_min"),
                }
            )

    payload = {
        "metadata": {
            "generated_at": now_iso(),
            "municipios_validos": len(valid_records),
            "municipios_invalidos": invalid_records,
            "candidate_battalions": candidate_battalions,
            "osrm_base_url": client.base_url,
            "batch_size": OSRM_BATCH_SIZE,
        },
        "matrix": matrix,
    }
    write_json(MATRIX_JSON_PATH, payload)
    write_csv(MATRIX_CSV_PATH, csv_rows)
    logger.info("Matriz OSRM gravada em %s e %s", MATRIX_JSON_PATH.name, MATRIX_CSV_PATH.name)


if __name__ == "__main__":
    main()
