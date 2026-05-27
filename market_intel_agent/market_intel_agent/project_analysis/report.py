"""Final human-readable report assembly for project analysis pipeline."""

from __future__ import annotations

from typing import Any

from market_intel_agent.project_analysis.models import AnalysisState


class FinalReportAssembler:
    def build(self, state: AnalysisState) -> str:
        verdict = self._verdict(state)
        lines = [
            f"# {state.resolved_entity.name or state.asset_input} — Structured Analysis",
            "",
            "## Project summary",
            f"- Input: {state.asset_input}",
            f"- Resolved entity: {state.resolved_entity.name} ({state.resolved_entity.slug})",
            f"- Sector: {state.sector}",
            f"- Pipeline status: {state.pipeline_status}",
            "",
            "## Universal metrics",
            f"- Market cap: {state.universal.market_cap}",
            f"- FDV: {state.universal.fdv}",
            f"- Circulating supply: {state.universal.circulating_supply}",
            f"- Total supply: {state.universal.total_supply}",
            f"- Max supply: {state.universal.max_supply}",
            f"- Spot volume 30d: {state.universal.spot_volume_30d}",
            f"- Annualized protocol revenue: {state.universal.annualized_protocol_revenue}",
            f"- Annualized tokenholder revenue: {state.universal.annualized_tokenholder_revenue}",
            "",
            "## Sector metrics",
            f"- TVL: {state.sector_metrics.tvl}",
            f"- Supplied TVL: {state.sector_metrics.supplied_tvl}",
            f"- Borrowed TVL: {state.sector_metrics.borrowed_tvl}",
            f"- Volume: {state.sector_metrics.volume}",
            f"- Open interest: {state.sector_metrics.open_interest}",
            f"- Markets count: {state.sector_metrics.markets_count}",
            "",
            "## Tokenomics / unlocks / value capture",
            f"- 12m unlocks: {state.universal.token_unlocks_12m}",
            f"- Unlock recipients: {state.universal.unlock_recipients}",
            f"- Value capture type: {state.universal.value_capture_type}",
            "",
            "## Peer comparison",
            f"- Peer group: {', '.join(state.comparison.peer_group) if state.comparison.peer_group else 'n/a'}",
            f"- Relative position: {state.comparison.relative_position}",
            f"- Market share: {state.comparison.market_share}",
            f"- Market share trend: {state.comparison.market_share_trend}",
            "",
            "## Risk block",
            f"- Hacks: {state.risk.hacks}",
            f"- Treasury: {state.risk.treasury}",
            f"- Oracle dependency: {state.risk.oracle_dependency}",
            "",
            "## Final verdict",
            f"- Strength of business: {verdict['business_strength']}",
            f"- Strength of token: {verdict['token_strength']}",
            f"- Business-token linkage: {verdict['linkage']}",
            f"- Main risk: {verdict['main_risk']}",
            f"- Main upside driver: {verdict['main_upside']}",
        ]
        return "\n".join(lines)

    def _verdict(self, state: AnalysisState) -> dict[str, str]:
        business_strength = "medium"
        token_strength = "medium"
        linkage = "unclear"

        if state.universal.annualized_protocol_revenue and state.universal.market_cap:
            ratio = state.computed.mc_to_revenue
            if ratio is not None and ratio < 10:
                business_strength = "strong"
            elif ratio is not None and ratio > 40:
                business_strength = "weak"

        if state.universal.value_capture_type in {"buyback", "burn", "revshare", "mixed"}:
            linkage = "visible"

        if state.computed.circulating_ratio is not None:
            if state.computed.circulating_ratio > 0.8:
                token_strength = "strong"
            elif state.computed.circulating_ratio < 0.3:
                token_strength = "weak"

        main_risk = "data gaps in required metrics" if state.missing_fields else "execution and market-cycle risk"
        main_upside = "operating leverage if demand KPI and revenue continue compounding"

        return {
            "business_strength": business_strength,
            "token_strength": token_strength,
            "linkage": linkage,
            "main_risk": main_risk,
            "main_upside": main_upside,
        }
