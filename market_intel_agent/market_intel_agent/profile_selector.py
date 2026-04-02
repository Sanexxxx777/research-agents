"""Select analysis profile for v1 based on target + sector resolution."""

from __future__ import annotations

from typing import Any

from market_intel_agent.config import (
    PROFILE_GENERIC_TOKEN,
    SUPPORTED_PROFILES,
)
from market_intel_agent.sector_schema import SECTOR_CLASSIFICATION_PRIORITY, matches_sector_keywords


class ProfileSelector:
    def select(self, *, target: dict[str, Any], sector_resolution: dict[str, Any]) -> str:
        metadata = target.get("metadata") or {}
        override = str(metadata.get("market_intel_profile") or "").strip().lower()
        if override in SUPPORTED_PROFILES:
            return override

        sector = str(sector_resolution.get("sector") or "").strip().lower()
        if sector in SUPPORTED_PROFILES:
            return sector

        text = " ".join(
            [
                str(target.get("category") or ""),
                str((target.get("metadata") or {}).get("sector") or ""),
                sector,
            ]
        ).lower()

        for candidate in SECTOR_CLASSIFICATION_PRIORITY:
            if candidate in SUPPORTED_PROFILES and matches_sector_keywords(text, candidate):
                return candidate
        return PROFILE_GENERIC_TOKEN
