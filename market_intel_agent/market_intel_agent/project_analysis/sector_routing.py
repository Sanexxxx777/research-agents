"""Deterministic sector mapping for project analysis pipeline."""

from __future__ import annotations

from typing import Any

from market_intel_agent.project_analysis.cache import Cache
from market_intel_agent.project_analysis.models import ResolvedEntity, SectorType


class SectorRouter:
    def __init__(self, *, cache: Cache | None = None, ttl_sec: int = 3600):
        self.cache = cache
        self.ttl_sec = ttl_sec

    async def resolve(self, entity: ResolvedEntity, *, coingecko_categories: list[str] | None = None) -> tuple[SectorType, str]:
        key = f"pa:sector:{(entity.slug or entity.name or '').lower()}"
        if self.cache:
            cached = await self.cache.get(key)
            if isinstance(cached, dict) and cached.get("sector"):
                return cached["sector"], str(cached.get("reason") or "cache")

        metadata = entity.metadata or {}
        db_category = str(metadata.get("db_category") or "").lower()
        dl_category = str(metadata.get("defillama_category") or "").lower()
        raw_categories = [str(x).lower() for x in (coingecko_categories or [])]

        candidates = [db_category, dl_category, *raw_categories]
        for text in candidates:
            if not text:
                continue
            mapped = self._map_text_to_sector(text)
            if mapped != "unknown":
                reason = f"metadata:{text}"
                if self.cache:
                    await self.cache.set(key, {"sector": mapped, "reason": reason}, ttl=self.ttl_sec)
                return mapped, reason

        # deterministic keyword fallback (non-LLM)
        fallback_text = " ".join(
            [
                str(entity.name or "").lower(),
                str(entity.token_symbol or "").lower(),
                str(entity.slug or "").lower(),
            ]
        )
        mapped = self._map_text_to_sector(fallback_text)
        reason = "keyword_fallback" if mapped != "unknown" else "unresolved"

        if self.cache:
            await self.cache.set(key, {"sector": mapped, "reason": reason}, ttl=self.ttl_sec)
        return mapped, reason

    def _map_text_to_sector(self, text: str) -> SectorType:
        lower = text.lower()
        if any(token in lower for token in ("lend", "money market", "borrow", "loan")):
            return "lending"
        if any(token in lower for token in ("perp", "deriv", "futures")):
            return "perp_dex"
        if any(token in lower for token in ("dex", "amm", "swap", "exchange")):
            return "spot_dex"
        return "unknown"
