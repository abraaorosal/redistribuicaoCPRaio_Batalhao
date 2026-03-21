from __future__ import annotations

import os


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


USE_LOCAL_OSRM = _get_bool("USE_LOCAL_OSRM", True)
LOCAL_OSRM_BASE_URL = os.getenv("LOCAL_OSRM_BASE_URL", "http://localhost:5000").rstrip("/")
OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "3"))

STABILITY_MARGIN_KM = float(os.getenv("STABILITY_MARGIN_KM", "15"))
SIGNIFICANT_GAIN_KM = float(os.getenv("SIGNIFICANT_GAIN_KM", "30"))
COHERENCE_MARGIN_KM = float(os.getenv("COHERENCE_MARGIN_KM", "10"))
EXCESSIVE_DISTANCE_KM = float(os.getenv("EXCESSIVE_DISTANCE_KM", "150"))
COMPANY_PROMOTION_DISTANCE_THRESHOLD_KM = float(
    os.getenv("COMPANY_PROMOTION_DISTANCE_THRESHOLD_KM", "70")
)
COMPANY_CLUSTER_SIZE_THRESHOLD = int(os.getenv("COMPANY_CLUSTER_SIZE_THRESHOLD", "6"))
NEIGHBOR_COUNT_FOR_COHERENCE = int(os.getenv("NEIGHBOR_COUNT_FOR_COHERENCE", "5"))
OSRM_BATCH_SIZE = int(os.getenv("OSRM_BATCH_SIZE", "20"))
IBGE_POPULATION_YEAR = int(os.getenv("IBGE_POPULATION_YEAR", "2025"))
IBGE_POPULATION_STATE_CODE = os.getenv("IBGE_POPULATION_STATE_CODE", "23").strip()
COMPANY_DISTANCE_WEIGHT = float(os.getenv("COMPANY_DISTANCE_WEIGHT", "0.35"))
COMPANY_CENTRALITY_WEIGHT = float(os.getenv("COMPANY_CENTRALITY_WEIGHT", "0.25"))
COMPANY_POPULATION_WEIGHT = float(os.getenv("COMPANY_POPULATION_WEIGHT", "0.25"))
COMPANY_EFETIVO_WEIGHT = float(os.getenv("COMPANY_EFETIVO_WEIGHT", "0.15"))
COMPANY_TIE_MARGIN_KM = float(os.getenv("COMPANY_TIE_MARGIN_KM", "8"))
COMPANY_TIE_DISTANCE_WEIGHT = float(os.getenv("COMPANY_TIE_DISTANCE_WEIGHT", "0.45"))
COMPANY_TIE_COVERAGE_WEIGHT = float(os.getenv("COMPANY_TIE_COVERAGE_WEIGHT", "0.30"))
COMPANY_TIE_EFETIVO_WEIGHT = float(os.getenv("COMPANY_TIE_EFETIVO_WEIGHT", "0.15"))
COMPANY_TIE_POPULATION_WEIGHT = float(os.getenv("COMPANY_TIE_POPULATION_WEIGHT", "0.07"))
COMPANY_TIE_COUNT_WEIGHT = float(os.getenv("COMPANY_TIE_COUNT_WEIGHT", "0.03"))

NOMINATIM_BASE_URL = os.getenv(
    "NOMINATIM_BASE_URL",
    "https://nominatim.openstreetmap.org/search",
).rstrip("/")
NOMINATIM_USER_AGENT = os.getenv(
    "NOMINATIM_USER_AGENT",
    "cpraio-redistribuicao-territorial/1.0 (operacional@cpraio.local)",
)
