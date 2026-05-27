import asyncio

from market_intel_agent.project_analysis.models import ResolvedEntity
from market_intel_agent.project_analysis.pipeline import ProjectAnalysisPipeline


class _FakeSources:
    def __init__(self):
        self.coingecko_calls = 0
        self.defillama_calls = 0

    async def fetch_coingecko_metrics(self, *, asset_input, coingecko_id, required_metrics):
        self.coingecko_calls += 1
        return {
            "coingecko_id": "aave",
            "token_symbol": "AAVE",
            "categories": ["Lending"],
            "market_cap": 1_000.0,
            "fdv": 1_500.0,
            "current_price": 100.0,
            "circulating_supply": 10.0,
            "total_supply": 16.0,
            "max_supply": 16.0,
            "spot_volume_30d": 250.0,
        }

    async def fetch_defillama_metrics(self, *, asset_input, sector, candidate_slug, coingecko_id, token_symbol, required_metrics):
        self.defillama_calls += 1
        return {}

    async def discover_peer_group(self, *, sector, target_slug, limit=5):
        return [
            {"name": "Compound", "slug": "compound", "tvl": 500.0},
            {"name": "Morpho", "slug": "morpho", "tvl": 300.0},
        ]

    def estimated_cost(self):
        return {
            "coingecko_estimated_calls": self.coingecko_calls,
            "defillama_estimated_calls": self.defillama_calls,
        }


class _FakeResolver:
    async def resolve(self, asset_input: str):
        return ResolvedEntity(
            name="Aave",
            slug="aave",
            entity_type="protocol",
            token_symbol="AAVE",
            coingecko_id="aave",
            defillama_slug="aave",
            metadata={"defillama_category": "Lending"},
        )


class _FakeRouter:
    async def resolve(self, entity, *, coingecko_categories=None):
        return "lending", "test"


class _FakeFirstPass:
    skills = ["protocol-deep-dive", "market-analysis", "risk-assessment"]

    async def run(self, *, asset_input, entity, sector):
        return {
            "skills": list(self.skills),
            "mode": "skills_command",
            "raw_outputs": {},
            "normalized": {
                # wrong owner field; must be rejected and replaced by CoinGecko value
                "market_cap": 999_999.0,
                "annualized_protocol_revenue": 100.0,
                "annualized_tokenholder_revenue": 50.0,
                "token_unlocks_12m": 2.0,
                "unlock_recipients": [{"name": "team", "pct": 0.4}],
                "value_capture_type": "revshare",
                "main_demand_kpi": 200.0,
                "main_demand_kpi_growth_90d": 0.2,
                "supplied_tvl": 600.0,
                "borrowed_tvl": 300.0,
                "bad_debt": 0.0,
                "collateral_mix": [{"asset": "WETH", "pct": 0.5}],
                "borrow_mix": [{"asset": "USDC", "pct": 0.4}],
                "concentration_metric": 0.3,
            },
        }


def test_pipeline_owner_enforcement_and_duplicate_call_prevention():
    sources = _FakeSources()
    pipeline = ProjectAnalysisPipeline(
        config={"project_analysis": {"enabled": True}},
        queries=None,
        cache=None,
        sources=sources,
        entity_resolver=_FakeResolver(),
        sector_router=_FakeRouter(),
        first_pass_runner=_FakeFirstPass(),
    )

    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(pipeline.run("AAVE"))
    analysis = result["analysis"]

    assert analysis["pipeline_status"] == "final_report_ready"
    assert analysis["universal"]["market_cap"] == 1_000.0
    assert analysis["universal"]["market_cap"] != 999_999.0
    assert analysis["sources_used"]["coingecko"] is True
    assert analysis["sources_used"]["defillama"] is True
    assert sources.coingecko_calls == 1
    assert sources.defillama_calls == 0
    assert analysis["missing_fields"] == []
    assert any(
        event.get("event") == "metric_rejected_wrong_owner" and event.get("metric") == "market_cap"
        for event in analysis["fetch_audit"]
    )


def test_pipeline_keeps_missing_fields_with_reason_when_data_unavailable():
    class _SparseSources(_FakeSources):
        async def fetch_coingecko_metrics(self, *, asset_input, coingecko_id, required_metrics):
            self.coingecko_calls += 1
            return {"coingecko_id": "aave", "categories": ["Lending"]}

    class _SparseFirstPass(_FakeFirstPass):
        async def run(self, *, asset_input, entity, sector):
            payload = await super().run(asset_input=asset_input, entity=entity, sector=sector)
            payload["normalized"] = {"annualized_protocol_revenue": 1.0}
            return payload

    sources = _SparseSources()
    pipeline = ProjectAnalysisPipeline(
        config={"project_analysis": {"enabled": True}},
        queries=None,
        cache=None,
        sources=sources,
        entity_resolver=_FakeResolver(),
        sector_router=_FakeRouter(),
        first_pass_runner=_SparseFirstPass(),
    )
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(pipeline.run("AAVE"))
    analysis = result["analysis"]

    assert analysis["pipeline_status"] == "final_report_ready"
    assert len(analysis["missing_fields"]) > 0
    assert all(item["reason"] for item in analysis["missing_fields"])
    assert all("dune" not in item.get("attempted_sources", []) for item in analysis["missing_fields"])


def test_pipeline_second_pass_skips_skill_covered_defillama_metrics():
    class _SpySources(_FakeSources):
        def __init__(self):
            super().__init__()
            self.last_defillama_required = []

        async def fetch_defillama_metrics(self, *, asset_input, sector, candidate_slug, coingecko_id, token_symbol, required_metrics):
            self.defillama_calls += 1
            self.last_defillama_required = list(required_metrics)
            return {}

    class _CoveredFirstPass(_FakeFirstPass):
        async def run(self, *, asset_input, entity, sector):
            return {
                "skills": list(self.skills),
                "covered_metrics": [
                    "annualized_protocol_revenue",
                    "annualized_tokenholder_revenue",
                    "token_unlocks_12m",
                    "unlock_recipients",
                    "value_capture_type",
                    "main_demand_kpi",
                    "main_demand_kpi_growth_90d",
                    "supplied_tvl",
                    "borrowed_tvl",
                    "bad_debt",
                    "collateral_mix",
                    "borrow_mix",
                    "concentration_metric",
                ],
                "mode": "skills_command",
                "raw_outputs": {},
                "normalized": {},
            }

    sources = _SpySources()
    pipeline = ProjectAnalysisPipeline(
        config={"project_analysis": {"enabled": True}},
        queries=None,
        cache=None,
        sources=sources,
        entity_resolver=_FakeResolver(),
        sector_router=_FakeRouter(),
        first_pass_runner=_CoveredFirstPass(),
    )
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(pipeline.run("AAVE"))
    analysis = result["analysis"]

    assert analysis["pipeline_status"] == "final_report_ready"
    assert sources.defillama_calls == 0
    assert sources.last_defillama_required == []
    assert any(item["field"] == "annualized_protocol_revenue" for item in analysis["missing_fields"])


def test_pipeline_missing_reason_uses_metric_unavailable_audit():
    class _ReasonedFirstPass(_FakeFirstPass):
        async def run(self, *, asset_input, entity, sector):
            return {
                "skills": list(self.skills),
                "covered_metrics": [
                    "annualized_protocol_revenue",
                ],
                "mode": "skills_command",
                "raw_outputs": {},
                "normalized": {},
                "source_audit": [
                    {
                        "event": "metric_unavailable",
                        "metric": "annualized_protocol_revenue",
                        "owner": "defillama",
                        "reason": "defillama.revenue summary unavailable",
                    }
                ],
            }

    sources = _FakeSources()
    pipeline = ProjectAnalysisPipeline(
        config={"project_analysis": {"enabled": True}},
        queries=None,
        cache=None,
        sources=sources,
        entity_resolver=_FakeResolver(),
        sector_router=_FakeRouter(),
        first_pass_runner=_ReasonedFirstPass(),
    )
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(pipeline.run("AAVE"))
    analysis = result["analysis"]

    miss = [item for item in analysis["missing_fields"] if item["field"] == "annualized_protocol_revenue"]
    assert miss
    assert miss[0]["reason"] == "defillama.revenue summary unavailable"
