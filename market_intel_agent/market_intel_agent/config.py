"""Configuration and registries for Market Intel Agent v1."""

from __future__ import annotations

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
    PROFILE_GENERIC_TOKEN: ["hub_market_status", "coingecko", "defillama"],
    **{sector: ["hub_market_status", "coingecko", "defillama"] for sector in TARGET_SECTORS},
}

HUB_BASE_URL = os.getenv("MARKET_INTEL_HUB_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
HUB_SERVICE_TOKEN = os.getenv("HUB_INTERNAL_SERVICE_TOKEN", "").strip()

COINGECKO_BASE_URL = os.getenv("MARKET_INTEL_COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3").rstrip("/")
DEFILLAMA_BASE_URL = os.getenv("MARKET_INTEL_DEFILLAMA_BASE_URL", "https://api.llama.fi").rstrip("/")

TARGET_ID_SEARCH_LIMIT = int(os.getenv("MARKET_INTEL_TARGET_ID_SEARCH_LIMIT", "500"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("MARKET_INTEL_HTTP_TIMEOUT_SECONDS", "20"))
