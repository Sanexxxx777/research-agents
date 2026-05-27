"""Entity resolution for project analysis pipeline."""

from __future__ import annotations

from typing import Any

from loguru import logger

from market_intel_agent.project_analysis.cache import Cache
from market_intel_agent.project_analysis.models import ResolvedEntity
from market_intel_agent.project_analysis.sources import ProjectAnalysisSources


class EntityResolver:
    def __init__(
        self,
        *,
        sources: ProjectAnalysisSources,
        cache: Cache | None = None,
        queries=None,
        ttl_sec: int = 3600,
    ):
        self.sources = sources
        self.cache = cache
        self.queries = queries
        self.ttl_sec = ttl_sec

    async def resolve(self, asset_input: str) -> ResolvedEntity:
        query = asset_input.strip()
        if not query:
            return ResolvedEntity(name="", entity_type="unknown")

        cache_key = f"pa:entity:{query.lower()}"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if isinstance(cached, dict):
                return ResolvedEntity(**cached)

        from_db = await self._resolve_from_db(query)

        cg_search = await self.sources.search_coingecko(query)
        coingecko_id = (
            from_db.get("coingecko_id")
            or str((cg_search or {}).get("id") or "").strip().lower()
            or None
        )
        token_symbol = (
            from_db.get("ticker")
            or str((cg_search or {}).get("symbol") or "").strip().upper()
            or None
        )
        base_name = (
            from_db.get("name")
            or str((cg_search or {}).get("name") or "").strip()
            or query
        )

        protocol = await self.sources.resolve_defillama_protocol(
            asset_input=query,
            candidate_slug=from_db.get("defillama_slug") or from_db.get("slug"),
            coingecko_id=coingecko_id,
            token_symbol=token_symbol,
        )
        defillama_slug = str((protocol or {}).get("slug") or "").strip().lower() or None

        entity = ResolvedEntity(
            name=str((protocol or {}).get("name") or base_name),
            slug=defillama_slug or coingecko_id or query.lower(),
            entity_type="protocol" if defillama_slug else "token",
            token_symbol=token_symbol,
            coingecko_id=coingecko_id,
            defillama_slug=defillama_slug,
            metadata={
                "input": query,
                "coingecko_rank": (cg_search or {}).get("market_cap_rank"),
                "coingecko_name": (cg_search or {}).get("name"),
                "defillama_category": (protocol or {}).get("category"),
                "db_category": from_db.get("category"),
                "db_metadata": from_db.get("metadata") or {},
            },
        )

        if self.cache:
            await self.cache.set(cache_key, entity.model_dump(), ttl=self.ttl_sec)
        return entity

    async def _resolve_from_db(self, query: str) -> dict[str, Any]:
        if not self.queries:
            return {}
        try:
            target = await self.queries.find_target(query)
        except Exception as exc:
            logger.debug(f"project_analysis db entity lookup failed: {exc}")
            return {}
        if not target:
            return {}
        return {
            "id": target.id,
            "name": target.name,
            "ticker": target.ticker,
            "category": target.category,
            "coingecko_id": target.coingecko_id,
            "metadata": target.metadata or {},
            "slug": str((target.metadata or {}).get("defillama_slug") or "").strip().lower() or None,
            "defillama_slug": str((target.metadata or {}).get("defillama_slug") or "").strip().lower() or None,
        }
