"""Resolve target sector using Hub market overview + lightweight heuristics."""

from __future__ import annotations

import re
from typing import Any

from market_intel_agent.sector_schema import (
    SECTOR_CLASSIFICATION_PRIORITY,
    matches_sector_keywords,
    normalize_alerts_sector_name,
)


class SectorResolver:
    def resolve(
        self,
        *,
        target: dict[str, Any],
        market_status: dict[str, Any] | None,
        coingecko_payload: dict[str, Any] | None = None,
        alerts_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        known_sectors = self._known_sectors_from_market_status(market_status or {})
        alerts_known_sectors = self._known_sectors_from_alerts_payload(alerts_payload or {})
        for sector in alerts_known_sectors:
            if sector not in known_sectors:
                known_sectors.append(sector)
        target_text = " ".join(
            [
                str(target.get("category") or ""),
                str((target.get("metadata") or {}).get("sector") or ""),
                " ".join((coingecko_payload or {}).get("categories") or []),
            ]
        ).strip().lower()

        matched_sector = None
        alerts_sector = self._sector_from_alerts_payload(target=target, alerts_payload=alerts_payload or {})
        if alerts_sector:
            matched_sector = alerts_sector

        for sector_name in known_sectors:
            if not matched_sector and sector_name and sector_name in target_text:
                matched_sector = sector_name
                break

        if not matched_sector:
            matched_sector = self._fallback_sector(target_text)

        return {
            "sector": matched_sector,
            "known_sectors": known_sectors,
            "resolution_source": "alerts_sector+hub_market_status+heuristics" if alerts_sector else "hub_market_status+heuristics",
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

    def _known_sectors_from_alerts_payload(self, alerts_payload: dict[str, Any]) -> list[str]:
        sectors = alerts_payload.get("known_sectors")
        if not sectors and isinstance(alerts_payload.get("sectors"), dict):
            sectors = list((alerts_payload.get("sectors") or {}).keys())
        names: list[str] = []
        for raw in sectors or []:
            normalized = normalize_alerts_sector_name(str(raw))
            if normalized and normalized not in names:
                names.append(normalized)
        return names

    def _sector_from_alerts_payload(self, *, target: dict[str, Any], alerts_payload: dict[str, Any]) -> str | None:
        normalized = str(alerts_payload.get("normalized_sector") or "").strip().lower()
        if normalized:
            return normalized
        sector_block = alerts_payload.get("sector_block") or {}
        normalized = str((sector_block or {}).get("sector") or "").strip().lower()
        if normalized:
            return normalized
        sector_tokens = alerts_payload.get("sectorTokens") or {}
        if not isinstance(sector_tokens, dict):
            return None
        identifiers = {
            str(target.get("coingecko_id") or "").strip().lower(),
            str(target.get("id") or "").strip().lower(),
            str(target.get("ticker") or "").strip().lower(),
            str(target.get("name") or "").strip().lower(),
        }
        identifiers = {item for item in identifiers if item}
        for item in list(identifiers):
            slug = "-".join(part for part in re.split(r"[^a-z0-9]+", item.lower()) if part)
            if slug:
                identifiers.add(slug)
        for display_name, tokens in sector_tokens.items():
            token_ids = {str(item or "").strip().lower() for item in (tokens or []) if str(item or "").strip()}
            if identifiers & token_ids:
                return normalize_alerts_sector_name(str(display_name))
        return None
