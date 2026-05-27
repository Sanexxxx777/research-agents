"""Compact peer group comparison for supported sectors."""

from __future__ import annotations

from market_intel_agent.project_analysis.models import AnalysisState
from market_intel_agent.project_analysis.sources import ProjectAnalysisSources


class PeerComparator:
    def __init__(self, *, sources: ProjectAnalysisSources, default_peer_count: int = 5):
        self.sources = sources
        self.default_peer_count = default_peer_count

    async def apply(self, state: AnalysisState) -> None:
        if state.sector == "unknown":
            state.comparison.relative_position = "not_available"
            return

        peers = await self.sources.discover_peer_group(
            sector=state.sector,
            target_slug=state.resolved_entity.defillama_slug,
            limit=self.default_peer_count,
        )

        state.comparison.peer_group = [str(item.get("name") or item.get("slug") or "") for item in peers if item]
        if not peers:
            state.comparison.relative_position = "not_available"
            return

        target_tvl = state.sector_metrics.tvl
        if target_tvl is None:
            if state.sector == "lending":
                target_tvl = state.sector_metrics.supplied_tvl
            elif state.sector in {"spot_dex", "perp_dex"}:
                target_tvl = state.sector_metrics.tvl

        peer_tvls = [float(item.get("tvl") or 0.0) for item in peers]
        if target_tvl is not None and target_tvl > 0:
            total = target_tvl + sum(peer_tvls)
            if total > 0:
                state.comparison.market_share = target_tvl / total

            sorted_values = sorted([target_tvl, *peer_tvls], reverse=True)
            rank = sorted_values.index(target_tvl) + 1
            state.comparison.relative_position = f"#{rank}/{len(sorted_values)} by TVL"
        else:
            state.comparison.relative_position = "insufficient_target_metric"

        state.comparison.market_share_trend = None
