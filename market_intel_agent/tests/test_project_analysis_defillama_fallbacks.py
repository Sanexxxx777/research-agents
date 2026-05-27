import asyncio

from market_intel_agent.project_analysis.sources import ProjectAnalysisSources


class _FallbackSources(ProjectAnalysisSources):
    def __init__(self):
        super().__init__(config={"project_analysis": {"defillama_summary_max_candidates": 2}}, cache=None)

    async def resolve_defillama_protocol(self, *, asset_input, candidate_slug, coingecko_id, token_symbol):
        return {
            "slug": "demo-protocol",
            "name": "Demo Protocol",
            "category": "Lending",
            "tvl": [{"date": 1, "totalLiquidityUSD": 1000.0}, {"date": 2, "totalLiquidityUSD": 1100.0}],
            "currentChainTvls": {"borrowed": 500.0, "staking": 1000.0},
        }

    async def _fetch_summary(self, group: str, slug: str):
        if group == "revenue":
            return None
        if group == "fees":
            return {"total30d": 10.0}
        if group == "unlocks":
            return None
        return None


def test_defillama_revenue_falls_back_to_fees_with_audit():
    sources = _FallbackSources()
    loop = asyncio.get_event_loop()
    payload = loop.run_until_complete(
        sources.fetch_defillama_metrics(
            asset_input="DEMO",
            sector="lending",
            candidate_slug="demo-protocol",
            coingecko_id="demo",
            token_symbol="DEMO",
            required_metrics=["annualized_protocol_revenue", "annualized_tokenholder_revenue", "token_unlocks_12m"],
        )
    )

    assert payload.get("annualized_protocol_revenue") == 120.0
    assert payload.get("annualized_tokenholder_revenue") == 120.0
    audit = payload.get("_audit") or []
    assert any(item.get("event") == "metric_fallback_applied" and item.get("metric") == "annualized_protocol_revenue" for item in audit)


def test_defillama_marks_unlock_fields_unavailable_with_reason():
    sources = _FallbackSources()
    loop = asyncio.get_event_loop()
    payload = loop.run_until_complete(
        sources.fetch_defillama_metrics(
            asset_input="DEMO",
            sector="lending",
            candidate_slug="demo-protocol",
            coingecko_id="demo",
            token_symbol="DEMO",
            required_metrics=["token_unlocks_12m", "unlock_recipients"],
        )
    )
    audit = payload.get("_audit") or []
    assert any(
        item.get("event") == "metric_unavailable"
        and item.get("metric") == "token_unlocks_12m"
        and "unlocks" in str(item.get("reason") or "").lower()
        for item in audit
    )
    assert any(
        item.get("event") == "metric_unavailable"
        and item.get("metric") == "unlock_recipients"
        and "recipients" in str(item.get("reason") or "").lower()
        for item in audit
    )


class _PerpSummaryFallbackSources(ProjectAnalysisSources):
    def __init__(self):
        super().__init__(config={"project_analysis": {"defillama_summary_max_candidates": 3}}, cache=None)

    async def resolve_defillama_protocol(self, *, asset_input, candidate_slug, coingecko_id, token_symbol):
        return {
            "slug": "dydx-v4",
            "name": "dYdX V4",
            "category": "Derivatives",
            "parentProtocol": "parent#dydx",
            "tvl": [{"date": 1, "totalLiquidityUSD": 1000.0}],
        }

    async def _fetch_summary(self, group: str, slug: str):
        if group == "derivatives" and slug == "dydx":
            return {"total30d": 123.0, "openInterest": 45.0, "markets": [1, 2, 3], "change_3m": 0.1}
        return None


def test_defillama_perp_derivatives_summary_uses_candidate_slugs():
    sources = _PerpSummaryFallbackSources()
    loop = asyncio.get_event_loop()
    payload = loop.run_until_complete(
        sources.fetch_defillama_metrics(
            asset_input="DYDX",
            sector="perp_dex",
            candidate_slug="dydx-v4",
            coingecko_id="dydx",
            token_symbol="DYDX",
            required_metrics=["volume", "open_interest", "markets_count", "main_demand_kpi"],
        )
    )

    assert payload.get("volume") == 123.0
    assert payload.get("main_demand_kpi") == 123.0
    assert payload.get("open_interest") == 45.0
    assert payload.get("markets_count") == 3
    audit = payload.get("_audit") or []
    volume_events = [item for item in audit if item.get("metric") == "volume" and item.get("event") == "metric_source"]
    assert volume_events
    assert volume_events[0].get("slug") == "dydx"
