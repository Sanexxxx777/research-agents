"""Runtime settings for the external collector agent."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os


@dataclass(frozen=True)
class Settings:
    service_token: str
    http_timeout_seconds: float
    coingecko_base_url: str
    defillama_base_url: str
    profile_cache_dir: str
    profile_cache_ttl_seconds: int
    docs_max_pages: int
    docs_max_seed_pages: int
    docs_stage_cap_seconds: float
    dune_api_key: str
    dune_base_url: str
    dune_query_timeout_seconds: float
    dune_poll_interval_seconds: float
    dune_query_ids: dict[str, int]

    @property
    def auth_enabled(self) -> bool:
        return bool(self.service_token)


def get_settings() -> Settings:
    query_ids = _parse_dune_query_ids(os.getenv("COLLECTOR_DUNE_QUERY_IDS", ""))
    return Settings(
        service_token=os.getenv("COLLECTOR_SERVICE_TOKEN", "").strip(),
        http_timeout_seconds=max(float(os.getenv("COLLECTOR_HTTP_TIMEOUT_SECONDS", "10")), 1.0),
        coingecko_base_url=os.getenv(
            "COINGECKO_BASE_URL",
            "https://api.coingecko.com/api/v3",
        ).rstrip("/"),
        defillama_base_url=os.getenv(
            "DEFILLAMA_BASE_URL",
            "https://api.llama.fi",
        ).rstrip("/"),
        profile_cache_dir=os.getenv(
            "COLLECTOR_PROFILE_CACHE_DIR",
            "/tmp/collector-agent-profile-cache",
        ).strip(),
        profile_cache_ttl_seconds=max(int(os.getenv("COLLECTOR_PROFILE_CACHE_TTL_SECONDS", "21600")), 60),
        docs_max_pages=max(int(os.getenv("COLLECTOR_DOCS_MAX_PAGES", "40")), 5),
        docs_max_seed_pages=max(int(os.getenv("COLLECTOR_DOCS_MAX_SEED_PAGES", "12")), 3),
        docs_stage_cap_seconds=max(float(os.getenv("COLLECTOR_DOCS_STAGE_CAP_SECONDS", "4")), 1.0),
        dune_api_key=os.getenv("COLLECTOR_DUNE_API_KEY", "").strip(),
        dune_base_url=os.getenv("COLLECTOR_DUNE_BASE_URL", "https://api.dune.com/api/v1").rstrip("/"),
        dune_query_timeout_seconds=max(float(os.getenv("COLLECTOR_DUNE_QUERY_TIMEOUT_SECONDS", "25")), 3.0),
        dune_poll_interval_seconds=max(float(os.getenv("COLLECTOR_DUNE_POLL_INTERVAL_SECONDS", "2")), 0.5),
        dune_query_ids=query_ids,
    )


def _parse_dune_query_ids(raw: str) -> dict[str, int]:
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}

    parsed: dict[str, int] = {}
    for key, value in payload.items():
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            parsed[str(key).strip().lower()] = numeric
    return parsed
