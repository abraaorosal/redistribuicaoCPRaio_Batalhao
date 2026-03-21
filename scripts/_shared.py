from __future__ import annotations

import csv
import json
import logging
import math
import re
import statistics
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

from _config import (
    IBGE_POPULATION_STATE_CODE,
    IBGE_POPULATION_YEAR,
    LOCAL_OSRM_BASE_URL,
    NOMINATIM_USER_AGENT,
    OSRM_BASE_URL,
    REQUEST_TIMEOUT,
    RETRY_ATTEMPTS,
    USE_LOCAL_OSRM,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "dados"
OUTPUT_DIR = PROJECT_ROOT / "output"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

INDEX_PATH = PROJECT_ROOT / "index.html"
CITIES_SOURCE_PATH = DATA_DIR / "cidades" / "municipios.json"
STRUCTURE_SOURCE_PATH = DATA_DIR / "estrutura" / "proposta1.json"
SCENARIOS_PATH = DATA_DIR / "cenarios_batalhoes.json"
MUNICIPIOS_BASE_PATH = DATA_DIR / "municipios_base.json"
# O nome do arquivo foi mantido por compatibilidade, mas ele representa
# a estrutura atual da unidade usada como referência de preservação.
CURRENT_STRUCTURE_STATUS_SOURCE_PATH = DATA_DIR / "estrutura" / "status_municipio_antigo.json"
EFETIVO_JSON_PATH = DATA_DIR / "efetivo" / f"efetivo_21_03_2026.json"
POPULATION_DIR = DATA_DIR / "populacao"
IBGE_POPULATION_JSON_PATH = POPULATION_DIR / f"ibge_estimativa_populacao_ce_{IBGE_POPULATION_YEAR}.json"

NORMALIZED_JSON_PATH = OUTPUT_DIR / "municipios_normalizados.json"
NORMALIZED_CSV_PATH = OUTPUT_DIR / "municipios_normalizados.csv"
COMPLEMENTARY_COORDS_PATH = OUTPUT_DIR / "coordenadas_complementares.json"
MATRIX_JSON_PATH = OUTPUT_DIR / "matriz_distancias_municipios.json"
MATRIX_CSV_PATH = OUTPUT_DIR / "matriz_distancias_municipios.csv"
CURRENT_SCENARIO_PATH = OUTPUT_DIR / "cenario_atual_avaliado.json"
EUSEBIO_SCENARIO_PATH = OUTPUT_DIR / "cenario_eusebio_avaliado.json"
SCENARIO_COMPARISON_JSON_PATH = OUTPUT_DIR / "comparativo_cenarios.json"
SCENARIO_COMPARISON_CSV_PATH = OUTPUT_DIR / "comparativo_cenarios.csv"
FINAL_STRUCTURE_JSON_PATH = OUTPUT_DIR / "estrutura_sugerida_final.json"
FINAL_STRUCTURE_CSV_PATH = OUTPUT_DIR / "estrutura_sugerida_final.csv"
ANALYTICAL_REPORT_JSON_PATH = OUTPUT_DIR / "relatorio_analitico.json"
ANALYTICAL_REPORT_CSV_PATH = OUTPUT_DIR / "relatorio_analitico.csv"


LOGGER_INITIALIZED = False
ISOLATED_BATTALION_NAME = "Fortaleza"
ISOLATED_BATTALION_KEY = "FORTALEZA"
ISOLATED_BATTALION_TYPE = "batalhao_isolado"
ISOLATED_BATTALION_NOTE = (
    "Batalhão isolado com atuação própria; não participa da redistribuição territorial "
    "e não vincula outros municípios."
)
ISOLATED_BATTALION_FORMAL_COMPANIES = (
    {"companhia": "Fortaleza", "origem_sugestao": "sede_batalhao"},
    {"companhia": "Motopoliciamento Ordinário", "origem_sugestao": "companhia_preservada_orientacao_gestao"},
    {"companhia": "Messejana", "origem_sugestao": "companhia_preservada_orientacao_gestao"},
)
MANUAL_BATTALION_OVERRIDE_BY_KEY = {
    "PARACURU": "Caucaia",
}
MANUAL_COMPANY_OVERRIDE_BY_BATTALION_KEY = {
    "CAUCAIA": {"PARACURU"},
}
METROPOLITAN_BATTALION_KEYS = {
    "CAUCAIA",
    "EUSEBIO",
}
METROPOLITAN_MUNICIPALITY_KEYS = {
    "FORTALEZA",
    "AQUIRAZ",
    "CASCAVEL",
    "CAUCAIA",
    "CHOROZINHO",
    "EUSEBIO",
    "GUAIUBA",
    "HORIZONTE",
    "ITAITINGA",
    "MARACANAU",
    "MARANGUAPE",
    "PACAJUS",
    "PACATUBA",
    "PARACURU",
    "PARAIPABA",
    "PINDORETAMA",
    "SAO GONCALO DO AMARANTE",
    "SAO LUIS DO CURU",
    "TRAIRI",
}


def build_logger(name: str) -> logging.Logger:
    global LOGGER_INITIALIZED
    if not LOGGER_INITIALIZED:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        LOGGER_INITIALIZED = True
    return logging.getLogger(name)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_runtime_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def normalize_name(value: str | None) -> str:
    value = str(value or "")
    normalized = value.strip().upper()
    normalized = unicodedata.normalize("NFD", normalized)
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.replace("D' ", "D ")
    return normalized


def title_key(name: str) -> str:
    return normalize_name(name)


def is_isolated_battalion(name: str | None) -> bool:
    return title_key(name or "") == ISOLATED_BATTALION_KEY


def get_manual_battalion_override(municipio: str | None) -> str | None:
    return MANUAL_BATTALION_OVERRIDE_BY_KEY.get(title_key(municipio))


def is_metropolitan_battalion(name: str | None) -> bool:
    return title_key(name or "") in METROPOLITAN_BATTALION_KEYS


def is_metropolitan_municipio(name: str | None) -> bool:
    return title_key(name or "") in METROPOLITAN_MUNICIPALITY_KEYS


def get_manual_company_overrides_for_battalion(batalhao: str | None) -> set[str]:
    return set(MANUAL_COMPANY_OVERRIDE_BY_BATTALION_KEY.get(title_key(batalhao), set()))


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
        fieldnames = keys
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def safe_float(value: Any) -> float | None:
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(output) or math.isinf(output):
        return None
    return output


def is_valid_coordinate(latitude: Any, longitude: Any) -> bool:
    lat = safe_float(latitude)
    lon = safe_float(longitude)
    if lat is None or lon is None:
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180


def format_km(value: float | None) -> str:
    if value is None:
        return "n/d"
    return f"{value:.1f}"


def percentil(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * q) - 1))
    return ordered[idx]


def median(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.median(values)


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.fmean(values)


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return 0.0 if values else None
    return statistics.pstdev(values)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def extract_js_object_literal(text: str, marker: str) -> str:
    # O index atual é a referência operacional vigente; extraímos a estrutura dele sem reescrever o painel.
    marker_index = text.find(marker)
    if marker_index < 0:
        raise ValueError(f"Marcador não encontrado no index.html: {marker}")

    start = text.find("{", marker_index)
    if start < 0:
        raise ValueError(f"Objeto não encontrado após marcador: {marker}")

    depth = 0
    in_string: str | None = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue

        if char in {'"', "'"}:
            in_string = char
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise ValueError(f"Objeto não finalizado para marcador: {marker}")


def js_object_to_dict(literal: str) -> dict[str, Any]:
    literal = re.sub(
        r"(?<=[{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:",
        lambda match: f' "{match.group(1)}":',
        literal,
    )
    literal = re.sub(r",\s*([}\]])", r"\1", literal)
    return json.loads(literal)


def load_current_structure_from_index() -> dict[str, Any]:
    text = INDEX_PATH.read_text(encoding="utf-8")
    literal = extract_js_object_literal(text, "const distribuicaoOficialAtual = {")
    return js_object_to_dict(literal)


def load_coordinates_sources() -> dict[str, dict[str, Any]]:
    coord_index: dict[str, dict[str, Any]] = {}
    for item in load_json(CITIES_SOURCE_PATH):
        coord_index[title_key(item["nome"])] = {
            "nome": item["nome"],
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
            "id_municipio": item.get("id_municipio"),
            "origem": "dados/cidades/municipios.json",
        }

    try:
        structure = load_json(STRUCTURE_SOURCE_PATH)
    except FileNotFoundError:
        return coord_index

    for batalhao in structure.get("bpraios", []):
        sede = batalhao.get("sede", {})
        for entry in [sede, *batalhao.get("companhias", [])]:
            if not isinstance(entry, dict):
                continue
            key = title_key(entry.get("nome"))
            if key and key not in coord_index and is_valid_coordinate(
                entry.get("latitude"), entry.get("longitude")
            ):
                coord_index[key] = {
                    "nome": entry.get("nome"),
                    "latitude": entry.get("latitude"),
                    "longitude": entry.get("longitude"),
                    "id_municipio": entry.get("id_municipio"),
                    "origem": "dados/estrutura/proposta1.json",
                }
            for pelotao in entry.get("pelotoes", []):
                pel_key = title_key(pelotao.get("nome"))
                if pel_key and pel_key not in coord_index and is_valid_coordinate(
                    pelotao.get("latitude"),
                    pelotao.get("longitude"),
                ):
                    coord_index[pel_key] = {
                        "nome": pelotao.get("nome"),
                        "latitude": pelotao.get("latitude"),
                        "longitude": pelotao.get("longitude"),
                        "id_municipio": pelotao.get("id_municipio"),
                        "origem": "dados/estrutura/proposta1.json",
                    }
    return coord_index


def load_complementary_coordinates() -> dict[str, dict[str, Any]]:
    if not COMPLEMENTARY_COORDS_PATH.exists():
        return {}

    payload = load_json(COMPLEMENTARY_COORDS_PATH)
    municipios = payload.get("municipios", [])
    output: dict[str, dict[str, Any]] = {}
    for item in municipios:
        key = title_key(item.get("nome"))
        if key:
            output[key] = item
    return output


def load_population_by_municipio() -> dict[str, dict[str, Any]]:
    if not IBGE_POPULATION_JSON_PATH.exists():
        return {}

    payload = load_json(IBGE_POPULATION_JSON_PATH)
    municipios = payload.get("municipios", [])
    output: dict[str, dict[str, Any]] = {}
    for item in municipios:
        key = title_key(item.get("municipio"))
        if key:
            output[key] = item
    return output


def load_efetivo_by_municipio() -> dict[str, int]:
    if not EFETIVO_JSON_PATH.exists():
        return {}

    payload = load_json(EFETIVO_JSON_PATH)
    output: dict[str, int] = {}
    for item in payload:
        key = title_key(item.get("municipio"))
        if not key:
            continue
        try:
            output[key] = int(item.get("efetivo") or 0)
        except (TypeError, ValueError):
            output[key] = 0
    return output


def load_current_structure_company_keys() -> set[str]:
    if not CURRENT_STRUCTURE_STATUS_SOURCE_PATH.exists():
        return set()

    payload = load_json(CURRENT_STRUCTURE_STATUS_SOURCE_PATH)
    return {
        title_key(item.get("municipio"))
        for item in payload
        if title_key(item.get("municipio")) and title_key(item.get("status")) == "COMPANHIA"
    }


def _make_record(
    *,
    nome: str,
    status_atual: str,
    tipo_atual: str,
    batalhao_codigo_atual: str,
    batalhao_atual: str,
    companhia_atual: str | None,
    subordinacao_atual: str | None,
    observacoes: str,
    coord_index: dict[str, dict[str, Any]],
    source_hint: str,
    population_index: dict[str, dict[str, Any]] | None = None,
    efetivo_index: dict[str, int] | None = None,
    tipo_especial: str | None = None,
    is_fortaleza: bool = False,
) -> dict[str, Any]:
    coord_data = coord_index.get(title_key(nome), {})
    population_data = (population_index or {}).get(title_key(nome), {})
    return {
        "nome": nome,
        "nome_normalizado": title_key(nome),
        "latitude": coord_data.get("latitude"),
        "longitude": coord_data.get("longitude"),
        "id_municipio": coord_data.get("id_municipio"),
        "tipo_atual": tipo_atual,
        "status_atual": status_atual,
        "subordinacao_atual": subordinacao_atual,
        "batalhao_codigo_atual": batalhao_codigo_atual,
        "batalhao_atual": batalhao_atual,
        "companhia_atual": companhia_atual,
        "observacoes": observacoes.strip(),
        "fonte_estrutura": source_hint,
        "fonte_coordenadas": coord_data.get("origem"),
        "populacao_ibge": safe_float(population_data.get("populacao_estimada")),
        "populacao_ano_referencia": population_data.get("ano_referencia"),
        "fonte_populacao": population_data.get("fonte_api"),
        "efetivo": (efetivo_index or {}).get(title_key(nome), 0),
        "tipo_especial": tipo_especial,
        "is_fortaleza": is_fortaleza,
    }


def ensure_isolated_battalion_records(
    records: dict[str, dict[str, Any]],
    *,
    coord_index: dict[str, dict[str, Any]],
    population_index: dict[str, dict[str, Any]],
    efetivo_index: dict[str, int],
    logger: logging.Logger,
) -> None:
    existing = records.get(ISOLATED_BATTALION_KEY)
    if existing:
        existing.update(
            {
                "status_atual": "batalhao",
                "tipo_atual": "batalhao",
                "batalhao_codigo_atual": existing.get("batalhao_codigo_atual") or "BATALHAO ISOLADO",
                "batalhao_atual": ISOLATED_BATTALION_NAME,
                "companhia_atual": ISOLATED_BATTALION_NAME,
                "subordinacao_atual": ISOLATED_BATTALION_NAME,
                "observacoes": ISOLATED_BATTALION_NOTE,
                "tipo_especial": ISOLATED_BATTALION_TYPE,
                "is_fortaleza": True,
                "populacao_ibge": safe_float(
                    population_index.get(ISOLATED_BATTALION_KEY, {}).get("populacao_estimada")
                ),
                "populacao_ano_referencia": population_index.get(ISOLATED_BATTALION_KEY, {}).get("ano_referencia"),
                "fonte_populacao": population_index.get(ISOLATED_BATTALION_KEY, {}).get("fonte_api"),
                "efetivo": efetivo_index.get(ISOLATED_BATTALION_KEY, 0),
            }
        )
        logger.info("Fortaleza carregada com sucesso na base operacional existente.")
        return

    if ISOLATED_BATTALION_KEY not in coord_index:
        logger.warning(
            "Fortaleza não foi encontrada na base de coordenadas; batalhão isolado não pôde ser injetado."
        )
        return

    records[ISOLATED_BATTALION_KEY] = _make_record(
        nome=ISOLATED_BATTALION_NAME,
        status_atual="batalhao",
        tipo_atual="batalhao",
        batalhao_codigo_atual="BATALHAO ISOLADO",
        batalhao_atual=ISOLATED_BATTALION_NAME,
        companhia_atual=ISOLATED_BATTALION_NAME,
        subordinacao_atual=ISOLATED_BATTALION_NAME,
        observacoes=ISOLATED_BATTALION_NOTE,
        coord_index=coord_index,
        source_hint="dados/cidades/municipios.json::fortaleza_batalhao_isolado",
        population_index=population_index,
        efetivo_index=efetivo_index,
        tipo_especial=ISOLATED_BATTALION_TYPE,
        is_fortaleza=True,
    )
    logger.info("Fortaleza carregada com sucesso na base operacional como batalhão isolado.")


def build_base_records(logger: logging.Logger | None = None) -> list[dict[str, Any]]:
    logger = logger or build_logger("shared")
    current_structure = load_current_structure_from_index()
    coord_index = load_coordinates_sources()
    coord_index.update(load_complementary_coordinates())
    population_index = load_population_by_municipio()
    efetivo_index = load_efetivo_by_municipio()

    records: dict[str, dict[str, Any]] = {}

    for batalhao_codigo, bloco in current_structure.items():
        sede = (bloco.get("sede") or [None])[0]
        if not sede:
            logger.warning("Batalhão %s sem sede no index.", batalhao_codigo)
            continue

        observacoes = bloco.get("observacoes", {})
        records[title_key(sede)] = _make_record(
            nome=sede,
            status_atual="batalhao",
            tipo_atual="batalhao",
            batalhao_codigo_atual=batalhao_codigo,
            batalhao_atual=sede,
            companhia_atual=sede,
            subordinacao_atual=sede,
            observacoes=observacoes.get(sede, "Sede atual do batalhão."),
            coord_index=coord_index,
            source_hint="index.html::distribuicaoOficialAtual",
            population_index=population_index,
            efetivo_index=efetivo_index,
        )

        for companhia in bloco.get("companhias", []):
            records[title_key(companhia)] = _make_record(
                nome=companhia,
                status_atual="companhia",
                tipo_atual="companhia",
                batalhao_codigo_atual=batalhao_codigo,
                batalhao_atual=sede,
                companhia_atual=companhia,
                subordinacao_atual=sede,
                observacoes=observacoes.get(companhia, "Companhia atual da estrutura em vigor."),
                coord_index=coord_index,
                source_hint="index.html::distribuicaoOficialAtual",
                population_index=population_index,
                efetivo_index=efetivo_index,
            )

        for independente in bloco.get("independentes", []):
            records[title_key(independente)] = _make_record(
                nome=independente,
                status_atual="cia_independente",
                tipo_atual="companhia",
                batalhao_codigo_atual=batalhao_codigo,
                batalhao_atual=sede,
                companhia_atual=independente,
                subordinacao_atual=independente,
                observacoes=observacoes.get(
                    independente,
                    "Companhia independente atual vinculada ao batalhão.",
                ),
                coord_index=coord_index,
                source_hint="index.html::distribuicaoOficialAtual",
                population_index=population_index,
                efetivo_index=efetivo_index,
            )

        subordinacao = bloco.get("subordinacao", {})
        pelotoes_vistos: set[str] = set()
        for parent, children in subordinacao.items():
            for pelotao in children:
                pel_key = title_key(pelotao)
                pelotoes_vistos.add(pel_key)
                records[pel_key] = _make_record(
                    nome=pelotao,
                    status_atual="pelotao",
                    tipo_atual="pelotao",
                    batalhao_codigo_atual=batalhao_codigo,
                    batalhao_atual=sede,
                    companhia_atual=parent,
                    subordinacao_atual=parent,
                    observacoes=observacoes.get(
                        pelotao,
                        f"Pelotão atualmente subordinado a {parent}.",
                    ),
                    coord_index=coord_index,
                    source_hint="index.html::distribuicaoOficialAtual",
                    population_index=population_index,
                    efetivo_index=efetivo_index,
                )

        for pelotao in bloco.get("pelotoes", []):
            pel_key = title_key(pelotao)
            if pel_key in pelotoes_vistos:
                continue
            records[pel_key] = _make_record(
                nome=pelotao,
                status_atual="pelotao",
                tipo_atual="pelotao",
                batalhao_codigo_atual=batalhao_codigo,
                batalhao_atual=sede,
                companhia_atual=sede,
                subordinacao_atual=sede,
                observacoes=observacoes.get(
                    pelotao,
                    "Pelotão atualmente subordinado diretamente à sede do batalhão.",
                ),
                coord_index=coord_index,
                source_hint="index.html::distribuicaoOficialAtual",
                population_index=population_index,
                efetivo_index=efetivo_index,
            )

    ensure_isolated_battalion_records(
        records,
        coord_index=coord_index,
        population_index=population_index,
        efetivo_index=efetivo_index,
        logger=logger,
    )
    output = sorted(records.values(), key=lambda item: item["nome"])
    return output


def persist_normalized_records(
    records: list[dict[str, Any]],
    *,
    metadata_extra: dict[str, Any] | None = None,
) -> None:
    metadata = {
        "generated_at": now_iso(),
        "total_municipios": len(records),
            "fontes": {
                "estrutura_atual": "index.html::distribuicaoOficialAtual",
                "coordenadas_base": str(CITIES_SOURCE_PATH.relative_to(PROJECT_ROOT)),
                "coordenadas_complementares": str(
                    COMPLEMENTARY_COORDS_PATH.relative_to(PROJECT_ROOT)
                ),
                "populacao_ibge": str(IBGE_POPULATION_JSON_PATH.relative_to(PROJECT_ROOT)),
                "efetivo": str(EFETIVO_JSON_PATH.relative_to(PROJECT_ROOT)),
            },
        }
    if metadata_extra:
        metadata.update(metadata_extra)

    payload = {"metadata": metadata, "municipios": records}
    write_json(MUNICIPIOS_BASE_PATH, payload)
    write_json(NORMALIZED_JSON_PATH, payload)
    write_csv(
        NORMALIZED_CSV_PATH,
        records,
        fieldnames=[
            "nome",
            "nome_normalizado",
            "latitude",
            "longitude",
            "id_municipio",
            "tipo_atual",
            "status_atual",
            "batalhao_codigo_atual",
            "batalhao_atual",
            "companhia_atual",
            "subordinacao_atual",
            "observacoes",
            "fonte_estrutura",
            "fonte_coordenadas",
            "populacao_ibge",
            "populacao_ano_referencia",
            "fonte_populacao",
            "efetivo",
            "tipo_especial",
            "is_fortaleza",
        ],
    )


def load_normalized_records() -> list[dict[str, Any]]:
    if NORMALIZED_JSON_PATH.exists():
        return load_json(NORMALIZED_JSON_PATH)["municipios"]
    if MUNICIPIOS_BASE_PATH.exists():
        return load_json(MUNICIPIOS_BASE_PATH)["municipios"]
    return build_base_records()


def load_scenarios() -> dict[str, Any]:
    return load_json(SCENARIOS_PATH)


def matrix_to_lookup(matrix_payload: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    return matrix_payload.get("matrix", {})


def get_distance_km(
    matrix_lookup: dict[str, dict[str, dict[str, Any]]],
    origin: str,
    destination: str,
) -> float | None:
    data = matrix_lookup.get(origin, {}).get(destination)
    if not data:
        return None
    return safe_float(data.get("distance_km"))


def get_duration_min(
    matrix_lookup: dict[str, dict[str, dict[str, Any]]],
    origin: str,
    destination: str,
) -> float | None:
    data = matrix_lookup.get(origin, {}).get(destination)
    if not data:
        return None
    return safe_float(data.get("duration_min"))


def build_record_index(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["nome"]: item for item in records}


def build_neighbor_map(records: list[dict[str, Any]], top_n: int) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    valid_records = [
        item
        for item in records
        if is_valid_coordinate(item.get("latitude"), item.get("longitude"))
    ]
    for record in valid_records:
        current_lat = float(record["latitude"])
        current_lon = float(record["longitude"])
        distances: list[tuple[float, str]] = []
        for other in valid_records:
            if other["nome"] == record["nome"]:
                continue
            distance = haversine_km(
                current_lat,
                current_lon,
                float(other["latitude"]),
                float(other["longitude"]),
            )
            distances.append((distance, other["nome"]))
        distances.sort(key=lambda item: item[0])
        output[record["nome"]] = [name for _, name in distances[:top_n]]
    return output


def summarize_distance_series(values: list[float]) -> dict[str, float | None]:
    ordered = sorted(values)
    return {
        "total_km": sum(values) if values else 0.0,
        "media_km": mean(values),
        "mediana_km": median(values),
        "p90_km": percentil(ordered, 0.9),
        "max_km": max(values) if values else None,
        "min_km": min(values) if values else None,
        "desvio_padrao_km": stdev(values),
    }


def classify_distance_band(distance_km: float | None) -> str:
    if distance_km is None:
        return "indefinido"
    if distance_km <= 40:
        return "proxima"
    if distance_km <= 80:
        return "moderada"
    if distance_km <= 150:
        return "distante"
    return "critica"


def build_battalion_summaries(
    scenario_rows: list[dict[str, Any]],
    *,
    battalion_field: str,
    distance_field: str,
    changed_field: str,
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    logger = logger or build_logger("shared")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scenario_rows:
        grouped[row[battalion_field]].append(row)

    counts = [len(items) for items in grouped.values()]
    mean_count = statistics.fmean(counts) if counts else 0.0
    output: list[dict[str, Any]] = []

    for batalhao, rows in sorted(grouped.items(), key=lambda item: item[0]):
        distances = [row[distance_field] for row in rows if safe_float(row[distance_field]) is not None]
        changed = sum(1 for row in rows if row.get(changed_field))
        summary = summarize_distance_series([float(value) for value in distances])
        sobrecarregado = (
            (summary["media_km"] or 0) > 120
            or (summary["max_km"] or 0) > 220
            or len(rows) > (mean_count * 1.4 if mean_count else len(rows) + 1)
        )
        output.append(
            {
                "batalhao": batalhao,
                "municipios_atendidos": len(rows),
                "distancia_total_km": round(summary["total_km"] or 0.0, 3),
                "distancia_media_km": round(summary["media_km"] or 0.0, 3),
                "distancia_maxima_km": round(summary["max_km"] or 0.0, 3),
                "desvio_padrao_km": round(summary["desvio_padrao_km"] or 0.0, 3),
                "redistribuidos": changed,
                "sobrecarregado_territorialmente": sobrecarregado,
                "municipios": [row["municipio"] for row in sorted(rows, key=lambda item: item["municipio"])],
            }
        )
    return output


@dataclass
class OsrmClient:
    logger: logging.Logger
    base_url: str | None = None
    last_healthcheck_error: str | None = None

    def __post_init__(self) -> None:
        if not self.base_url:
            self.base_url = self._resolve_base_url()

    def _resolve_base_url(self) -> str:
        candidates: list[str] = []
        if USE_LOCAL_OSRM:
            candidates.append(LOCAL_OSRM_BASE_URL)
        if OSRM_BASE_URL not in candidates:
            candidates.append(OSRM_BASE_URL)

        for candidate in candidates:
            if self._is_healthy(candidate):
                self.logger.info("Usando endpoint OSRM: %s", candidate)
                return candidate

        error_msg = self.last_healthcheck_error or "nenhum endpoint respondeu com sucesso"
        raise RuntimeError(f"Não foi possível inicializar o OSRM: {error_msg}")

    def _is_healthy(self, base_url: str) -> bool:
        probe_url = (
            f"{base_url}/table/v1/driving/"
            "-38.661931,-3.727966;-38.455875,-3.892501"
            "?sources=0&destinations=1&annotations=distance,duration"
        )
        try:
            response = requests.get(
                probe_url,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": NOMINATIM_USER_AGENT},
            )
            response.raise_for_status()
            payload = response.json()
            ok = payload.get("code") == "Ok"
            if not ok:
                self.last_healthcheck_error = f"{base_url}: {payload}"
            return ok
        except Exception as exc:  # noqa: BLE001
            self.last_healthcheck_error = f"{base_url}: {exc}"
            return False

    def _request(self, service: str, coordinates: list[tuple[float, float]], params: dict[str, Any]) -> dict[str, Any]:
        coord_blob = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coordinates)
        url = f"{self.base_url}/{service}/v1/driving/{coord_blob}"

        last_error: Exception | None = None
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                    headers={"User-Agent": NOMINATIM_USER_AGENT},
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("code") != "Ok":
                    raise RuntimeError(f"Resposta OSRM inválida: {payload}")
                return payload
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self.logger.warning(
                    "Falha OSRM (%s) tentativa %s/%s: %s",
                    service,
                    attempt,
                    RETRY_ATTEMPTS,
                    exc,
                )
                time.sleep(min(2**attempt, 6))

        raise RuntimeError(f"Falha após retries no OSRM ({service}): {last_error}") from last_error

    def table(
        self,
        origins: list[dict[str, Any]],
        destinations: list[dict[str, Any]],
    ) -> dict[str, dict[str, dict[str, float | None]]]:
        # Usamos o serviço table para reduzir o volume de requisições mantendo distância e duração rodoviárias.
        coordinates = [
            (float(item["latitude"]), float(item["longitude"])) for item in [*origins, *destinations]
        ]
        source_indexes = ";".join(str(index) for index in range(len(origins)))
        dest_indexes = ";".join(
            str(index) for index in range(len(origins), len(origins) + len(destinations))
        )
        payload = self._request(
            "table",
            coordinates,
            {
                "sources": source_indexes,
                "destinations": dest_indexes,
                "annotations": "distance,duration",
            },
        )
        distances = payload.get("distances") or []
        durations = payload.get("durations") or []

        output: dict[str, dict[str, dict[str, float | None]]] = {}
        for row_index, origin in enumerate(origins):
            bucket: dict[str, dict[str, float | None]] = {}
            for col_index, destination in enumerate(destinations):
                distance_m = safe_float(distances[row_index][col_index]) if distances else None
                duration_s = safe_float(durations[row_index][col_index]) if durations else None
                bucket[destination["nome"]] = {
                    "distance_m": distance_m,
                    "distance_km": round(distance_m / 1000, 6) if distance_m is not None else None,
                    "duration_s": duration_s,
                    "duration_min": round(duration_s / 60, 6) if duration_s is not None else None,
                }
            output[origin["nome"]] = bucket
        return output

    def route(self, origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, float | None]:
        payload = self._request(
            "route",
            [
                (float(origin["latitude"]), float(origin["longitude"])),
                (float(destination["latitude"]), float(destination["longitude"])),
            ],
            {"overview": "false"},
        )
        route = (payload.get("routes") or [{}])[0]
        distance_m = safe_float(route.get("distance"))
        duration_s = safe_float(route.get("duration"))
        return {
            "distance_m": distance_m,
            "distance_km": round(distance_m / 1000, 6) if distance_m is not None else None,
            "duration_s": duration_s,
            "duration_min": round(duration_s / 60, 6) if duration_s is not None else None,
        }


def rank_scenario_tuple(summary: dict[str, Any]) -> tuple[float, float, int, int]:
    return (
        safe_float(summary.get("total_distance_km")) or float("inf"),
        safe_float(summary.get("centralidade_operacional_km")) or float("inf"),
        int(summary.get("casos_fragmentados", 0)),
        int(summary.get("municipios_redistribuidos", 0)),
    )


def flatten_summary_for_csv(section: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            continue
        rows.append({"secao": section, "chave": key, "valor": value})
    return rows
