"""Local ratio calculators for project analysis pipeline."""

from __future__ import annotations

from typing import Any

from market_intel_agent.project_analysis.models import AnalysisState


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator


class LocalMetricsCalculator:
    def apply(self, state: AnalysisState) -> int:
        u = state.universal
        s = state.sector_metrics
        c = state.computed

        c.fdv_mc_ratio = _safe_div(u.fdv, u.market_cap)

        circulating_denominator = u.max_supply if u.max_supply not in (None, 0) else u.total_supply
        c.circulating_ratio = _safe_div(u.circulating_supply, circulating_denominator)

        c.unlocks_12m_pct_of_circulating = _safe_div(u.token_unlocks_12m, u.circulating_supply)

        c.mc_to_revenue = _safe_div(u.market_cap, u.annualized_protocol_revenue)
        c.fdv_to_revenue = _safe_div(u.fdv, u.annualized_protocol_revenue)
        c.mc_to_tokenholder_revenue = _safe_div(u.market_cap, u.annualized_tokenholder_revenue)

        c.revenue_yield = _safe_div(u.annualized_protocol_revenue, u.market_cap)
        c.tokenholder_revenue_yield = _safe_div(u.annualized_tokenholder_revenue, u.market_cap)

        c.lending_utilization = _safe_div(s.borrowed_tvl, s.supplied_tvl)
        c.dex_volume_tvl = _safe_div(s.volume, s.tvl)
        c.perp_volume_oi = _safe_div(s.volume, s.open_interest)

        return sum(
            1
            for value in (
                c.fdv_mc_ratio,
                c.circulating_ratio,
                c.unlocks_12m_pct_of_circulating,
                c.mc_to_revenue,
                c.fdv_to_revenue,
                c.mc_to_tokenholder_revenue,
                c.revenue_yield,
                c.tokenholder_revenue_yield,
                c.lending_utilization,
                c.dex_volume_tvl,
                c.perp_volume_oi,
            )
            if value is not None
        )
