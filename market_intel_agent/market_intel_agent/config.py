"""Configuration and registries for Market Intel Agent v1."""

from __future__ import annotations

import json
import os

from market_intel_agent.sector_schema import SECTOR_SCHEMA, TARGET_SECTORS

PROFILE_GENERIC_TOKEN = "generic_token"
PROFILE_DEFI_LENDING = "defi_lending"
PROFILE_DEX_SPOT = "dex_spot"
PROFILE_L1_L2 = "l1_l2"
PROFILE_PERP_DEX = "perp_dex"
PROFILE_LST_LRT = "lst_lrt"
PROFILE_STABLECOINS = "stablecoins"
PROFILE_BRIDGES = "bridges"
PROFILE_RWA = "rwa"
PROFILE_ORACLES = "oracles"
PROFILE_DEPIN = "depin"
PROFILE_AI = "ai"
PROFILE_INFRASTRUCTURE = "infrastructure"

SUPPORTED_PROFILES: tuple[str, ...] = (
    PROFILE_GENERIC_TOKEN,
    *TARGET_SECTORS,
)

PROFILE_REQUIRED_METRICS: dict[str, list[str]] = {
    PROFILE_GENERIC_TOKEN: [
        "price_usd",
        "market_cap",
        "volume_24h",
    ],
    **{
        sector: list(SECTOR_SCHEMA[sector]["sector_metrics"]["must"])
        for sector in TARGET_SECTORS
    },
}

PROFILE_SOURCE_REGISTRY: dict[str, list[str]] = {
    PROFILE_GENERIC_TOKEN: ["hub_market_status", "alerts_sector", "coingecko", "defillama"],
    **{sector: ["hub_market_status", "alerts_sector", "coingecko", "defillama"] for sector in TARGET_SECTORS},
}

HUB_BASE_URL = os.getenv("MARKET_INTEL_HUB_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
HUB_SERVICE_TOKEN = os.getenv("HUB_INTERNAL_SERVICE_TOKEN", "").strip()

COINGECKO_BASE_URL = os.getenv("MARKET_INTEL_COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3").rstrip("/")
DEFILLAMA_BASE_URL = os.getenv("MARKET_INTEL_DEFILLAMA_BASE_URL", "https://api.llama.fi").rstrip("/")
ALERTS_SECTOR_API_URL = os.getenv(
    "MARKET_INTEL_ALERTS_SECTOR_API_URL",
    "https://sectormap.dpdns.org/api/sheets",
).rstrip("/")
ALERTS_SECTOR_API_KEY = os.getenv("MARKET_INTEL_ALERTS_SECTOR_API_KEY", "crypto-dashboard-2024").strip()

TARGET_ID_SEARCH_LIMIT = int(os.getenv("MARKET_INTEL_TARGET_ID_SEARCH_LIMIT", "500"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("MARKET_INTEL_HTTP_TIMEOUT_SECONDS", "20"))


def _parse_json_dict(raw: str) -> dict[str, int]:
    text = raw.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in payload.items():
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            out[str(key).strip().lower()] = numeric
    return out


def _parse_json_str_dict(raw: str) -> dict[str, str]:
    text = raw.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in payload.items():
        left = str(key).strip().lower()
        right = str(value).strip().lower()
        if left and right:
            out[left] = right
    return out


PROJECT_ANALYSIS_ENABLED = str(os.getenv("MARKET_INTEL_PROJECT_ANALYSIS_ENABLED", "1")).strip().lower() not in {
    "0",
    "false",
    "no",
}
PROJECT_ANALYSIS_CONFIG: dict[str, object] = {
    "project_analysis": {
        "enabled": PROJECT_ANALYSIS_ENABLED,
        "coingecko_base_url": COINGECKO_BASE_URL,
        "defillama_base_url": DEFILLAMA_BASE_URL,
        "defillama_min_interval_ms": float(os.getenv("MARKET_INTEL_PA_DEFILLAMA_MIN_INTERVAL_MS", "250")),
        "defillama_max_calls_per_run": int(os.getenv("MARKET_INTEL_PA_DEFILLAMA_MAX_CALLS_PER_RUN", "20")),
        "defillama_retry_max": int(os.getenv("MARKET_INTEL_PA_DEFILLAMA_RETRY_MAX", "2")),
        "defillama_retry_backoff_ms": float(os.getenv("MARKET_INTEL_PA_DEFILLAMA_RETRY_BACKOFF_MS", "400")),
        "coingecko_retry_max": int(os.getenv("MARKET_INTEL_PA_COINGECKO_RETRY_MAX", "2")),
        "coingecko_retry_backoff_ms": float(os.getenv("MARKET_INTEL_PA_COINGECKO_RETRY_BACKOFF_MS", "400")),
        "defillama_summary_max_candidates": int(os.getenv("MARKET_INTEL_PA_DEFILLAMA_SUMMARY_MAX_CANDIDATES", "2")),
        "defillama_protocol_aliases": _parse_json_str_dict(
            os.getenv("MARKET_INTEL_PA_DEFILLAMA_PROTOCOL_ALIASES", "")
        ),
        "dune_base_url": os.getenv("MARKET_INTEL_DUNE_BASE_URL", "https://api.dune.com/api/v1").rstrip("/"),
        "dune_api_key": os.getenv("MARKET_INTEL_DUNE_API_KEY", "").strip(),
        "dune_gap_fill_enabled": str(os.getenv("MARKET_INTEL_PA_DUNE_GAP_FILL_ENABLED", "0")).strip().lower()
        in {"1", "true", "yes", "on"},
        "dune_query_timeout_sec": float(os.getenv("MARKET_INTEL_DUNE_QUERY_TIMEOUT_SECONDS", "25")),
        "dune_poll_interval_sec": float(os.getenv("MARKET_INTEL_DUNE_POLL_INTERVAL_SECONDS", "2")),
        "dune_query_ids": _parse_json_dict(os.getenv("MARKET_INTEL_DUNE_QUERY_IDS", "")),
        "http_timeout_sec": HTTP_TIMEOUT_SECONDS,
        "cache_ttl_sec": int(os.getenv("MARKET_INTEL_PA_CACHE_TTL_SEC", "900")),
        "error_cache_ttl_sec": float(os.getenv("MARKET_INTEL_PA_ERROR_CACHE_TTL_SEC", "30")),
        "entity_cache_ttl_sec": int(os.getenv("MARKET_INTEL_PA_ENTITY_CACHE_TTL_SEC", "3600")),
        "sector_cache_ttl_sec": int(os.getenv("MARKET_INTEL_PA_SECTOR_CACHE_TTL_SEC", "3600")),
        "skills": {
            "enabled": [
                item.strip()
                for item in (
                    os.getenv(
                        "MARKET_INTEL_DEFILLAMA_SKILLS",
                        "protocol-deep-dive,market-analysis,risk-assessment",
                    )
                ).split(",")
                if item.strip()
            ],
            "command_template": os.getenv("MARKET_INTEL_SKILLS_COMMAND_TEMPLATE", "").strip(),
        },
        "mcp": {
            "openclaw_bin": os.getenv("MARKET_INTEL_OPENCLAW_BIN", "openclaw"),
            "defillama_url": os.getenv("MARKET_INTEL_DEFILLAMA_MCP_URL", "").strip(),
            "coingecko_url": os.getenv("MARKET_INTEL_COINGECKO_MCP_URL", "").strip(),
            "dune_url": os.getenv("MARKET_INTEL_DUNE_MCP_URL", "").strip(),
        },
    }
}
