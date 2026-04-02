"""Resolve target sector using Hub market overview + lightweight heuristics."""

from __future__ import annotations

from typing import Any

from market_intel_agent.sector_schema import (
    SECTOR_CLASSIFICATION_PRIORITY,
    matches_sector_keywords,
)


class SectorResolver:
    def resolve(
        self,
        *,
        target: dict[str, Any],
        market_status: dict[str, Any] | None,
        coingecko_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        known_sectors = self._known_sectors_from_market_status(market_status or {})
        target_text = " ".join(
            [
                str(target.get("category") or ""),
                str((target.get("metadata") or {}).get("sector") or ""),
                " ".join((coingecko_payload or {}).get("categories") or []),
            ]
        ).strip().lower()

        matched_sector = None
        for sector_name in known_sectors:
            if sector_name and sector_name in target_text:
                matched_sector = sector_name
                break

        if not matched_sector:
            matched_sector = self._fallback_sector(target_text)

        return {
            "sector": matched_sector,
            "known_sectors": known_sectors,
            "resolution_source": "hub_market_status+heuristics",
            "target_text": target_text,
        }

    def _known_sectors_from_market_status(self, market_status: dict[str, Any]) -> list[str]:
        names: list[str] = []
        for key in ("top_sectors", "worst_sectors"):
            rows = market_status.get(key) or []
            for row in rows:
                name = str((row or {}).get("name") or "").strip().lower()
                if name and name not in names:
                    names.append(name)
        return names

    def _fallback_sector(self, text: str) -> str:
        for candidate in SECTOR_CLASSIFICATION_PRIORITY:
            if matches_sector_keywords(text, candidate):
                return candidate
        return "generic_token"
