from __future__ import annotations

from _shared import build_base_records, build_logger, ensure_runtime_dirs, persist_normalized_records


def main() -> None:
    logger = build_logger("normalizar_dados")
    ensure_runtime_dirs()
    records = build_base_records(logger=logger)
    sem_coordenadas = [
        item["nome"]
        for item in records
        if item.get("latitude") is None or item.get("longitude") is None
    ]
    logger.info("Municípios consolidados: %s", len(records))
    if sem_coordenadas:
        logger.warning("Municípios sem coordenadas válidas: %s", ", ".join(sem_coordenadas))
    else:
        logger.info("Todos os municípios possuem coordenadas válidas na base consolidada.")

    persist_normalized_records(
        records,
        metadata_extra={
            "normalizacao": {
                "faltantes_coordenadas": sem_coordenadas,
            }
        },
    )


if __name__ == "__main__":
    main()
