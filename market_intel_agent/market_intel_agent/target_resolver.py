"""Resolve incoming query/target_id into a concrete Hub target."""

from __future__ import annotations

from market_intel_agent.config import TARGET_ID_SEARCH_LIMIT
from market_intel_agent.contracts import ResolvedTarget
from market_intel_agent.hub_client import HubClient


class TargetResolver:
    def __init__(self, hub_client: HubClient) -> None:
        self.hub_client = hub_client

    async def resolve(
        self,
        *,
        query: str | None = None,
        target_id: int | None = None,
    ) -> ResolvedTarget:
        if query:
            target = await self._resolve_by_query(query)
            if target_id is not None and target.id != target_id:
                matches = await self.hub_client.search_targets(query=query, limit=50)
                exact = next((item for item in matches if item.get("id") == target_id), None)
                if exact:
                    return self._to_target(exact)
            return target

        if target_id is not None:
            target = await self._resolve_by_target_id(target_id)
            if target:
                return target
            raise ValueError(f"Target with id={target_id} not found via Hub search")

        raise ValueError("Either query or target_id must be provided")

    async def _resolve_by_query(self, query: str) -> ResolvedTarget:
        direct = await self.hub_client.get_target_by_name(query)
        if direct:
            return self._to_target(direct)

        matches = await self.hub_client.search_targets(query=query, limit=20)
        if not matches:
            raise ValueError(f"Target not found for query='{query}'")

        q = query.strip().lower()
        exact = next(
            (
                item
                for item in matches
                if (item.get("name") or "").strip().lower() == q
                or (item.get("ticker") or "").strip().lower() == q
            ),
            None,
        )
        return self._to_target(exact or matches[0])

    async def _resolve_by_target_id(self, target_id: int) -> ResolvedTarget | None:
        matches = await self.hub_client.search_targets(query="", limit=TARGET_ID_SEARCH_LIMIT)
        found = next((item for item in matches if item.get("id") == target_id), None)
        if not found:
            return None
        return self._to_target(found)

    def _to_target(self, item: dict) -> ResolvedTarget:
        return ResolvedTarget(
            id=item.get("id"),
            name=item.get("name", ""),
            ticker=item.get("ticker"),
            category=item.get("category"),
            coingecko_id=item.get("coingecko_id"),
            metadata=item.get("metadata") or {},
        )
