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
    )
