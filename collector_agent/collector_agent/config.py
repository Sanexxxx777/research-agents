"""Runtime settings for the external collector agent."""

from __future__ import annotations

from dataclasses import dataclass
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

    @property
    def auth_enabled(self) -> bool:
        return bool(self.service_token)


def get_settings() -> Settings:
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
    )
