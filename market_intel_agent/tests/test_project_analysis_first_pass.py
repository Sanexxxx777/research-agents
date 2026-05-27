import asyncio
from pathlib import Path

from market_intel_agent.project_analysis.first_pass import FirstPassRunner
from market_intel_agent.project_analysis.models import ResolvedEntity
from market_intel_agent.project_analysis.registry import metrics_covered_by_first_pass


class _FakeSources:
    def __init__(self):
        self.required_metrics = []

    async def fetch_defillama_metrics(self, *, asset_input, sector, candidate_slug, coingecko_id, token_symbol, required_metrics):
        self.required_metrics = list(required_metrics)
        return {
            "annualized_protocol_revenue": 100.0,
            "annualized_tokenholder_revenue": 50.0,
            "token_unlocks_12m": 10.0,
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
            "volume": 1_000.0,
            "open_interest": 200.0,
            "retention": 0.6,
            "market_depth_or_liquidity": 900.0,
            "markets_count": 7,
            "hacks": [{"name": "none"}],
            "treasury": {"stable_pct": 0.7},
            "oracle_dependency": {"provider": "chainlink"},
        }


def test_first_pass_bridge_uses_skill_coverage_union_and_profiles():
    sources = _FakeSources()
    runner = FirstPassRunner(
        config={
            "project_analysis": {
                "skills": {
                    "enabled": [
                        "defillama-openapi-skill",
                        "defillama-api",
                        "risk-assessment",
                    ]
                }
            }
        },
        sources=sources,
    )
    entity = ResolvedEntity(name="Aave", token_symbol="AAVE", coingecko_id="aave", defillama_slug="aave")

    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(runner.run(asset_input="AAVE", entity=entity, sector="lending"))

    expected = metrics_covered_by_first_pass(["protocol-deep-dive", "market-analysis", "risk-assessment"])
    assert result["mode"] == "bridge_skill_profiles"
    assert sorted(result["covered_metrics"]) == expected
    assert sorted(sources.required_metrics) == expected
    assert result["skill_aliases"] == {
        "protocol-deep-dive": "defillama-openapi-skill",
        "market-analysis": "defillama-api",
    }
    assert "hacks" in result["raw_outputs"]["risk-assessment"]["metrics"]
    assert "volume" in result["raw_outputs"]["market-analysis"]["metrics"]
    assert "supplied_tvl" in result["raw_outputs"]["protocol-deep-dive"]["metrics"]


def test_first_pass_command_template_uses_requested_and_canonical_skill(tmp_path: Path):
    tool = tmp_path / "emit_skill_json.py"
    tool.write_text(
        "\n".join(
            [
                "import argparse, json",
                "p = argparse.ArgumentParser()",
                "p.add_argument('--skill', required=True)",
                "p.add_argument('--canonical-skill', required=True)",
                "a = p.parse_args()",
                "out = {'_meta': {'skill': a.skill, 'canonical_skill': a.canonical_skill}}",
                "if a.canonical_skill == 'protocol-deep-dive':",
                "    out['annualized_protocol_revenue'] = 10.0",
                "elif a.canonical_skill == 'market-analysis':",
                "    out['volume'] = 20.0",
                "elif a.canonical_skill == 'risk-assessment':",
                "    out['hacks'] = [{'count': 1}]",
                "print(json.dumps(out))",
            ]
        ),
        encoding="utf-8",
    )

    command_template = (
        f'python3 "{tool}" --skill "{{skill}}" --canonical-skill "{{canonical_skill}}"'
    )
    runner = FirstPassRunner(
        config={
            "project_analysis": {
                "skills": {
                    "enabled": [
                        "defillama-openapi-skill",
                        "defillama-api",
                        "risk-assessment",
                    ],
                    "command_template": command_template,
                }
            }
        },
        sources=_FakeSources(),
    )
    entity = ResolvedEntity(name="Aave", token_symbol="AAVE", coingecko_id="aave", defillama_slug="aave")

    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(runner.run(asset_input="AAVE", entity=entity, sector="lending"))

    assert result["mode"] == "skills_command"
    assert result["skill_aliases"] == {
        "protocol-deep-dive": "defillama-openapi-skill",
        "market-analysis": "defillama-api",
    }
    assert result["raw_outputs"]["protocol-deep-dive"]["_meta"]["skill"] == "defillama-openapi-skill"
    assert result["raw_outputs"]["protocol-deep-dive"]["_meta"]["canonical_skill"] == "protocol-deep-dive"
    assert result["normalized"]["annualized_protocol_revenue"] == 10.0
    assert result["normalized"]["volume"] == 20.0
    assert result["normalized"]["hacks"][0]["count"] == 1
    assert any(
        item.get("event") == "metric_unavailable"
        and item.get("metric") == "open_interest"
        and "missing metric" in str(item.get("reason") or "")
        for item in (result.get("source_audit") or [])
    )
