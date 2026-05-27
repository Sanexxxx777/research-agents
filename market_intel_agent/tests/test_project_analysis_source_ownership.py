from market_intel_agent.project_analysis.registry import (
    UNIVERSAL_REQUIRED_METRICS,
    canonical_first_pass_skill,
    metrics_covered_by_first_pass,
    owner_for_metric,
    policy_for_metric,
    required_metrics_for_sector,
)


def test_source_ownership_registry_assignments():
    assert owner_for_metric("market_cap") == "coingecko"
    assert owner_for_metric("fdv") == "coingecko"
    assert owner_for_metric("annualized_protocol_revenue") == "defillama"
    assert owner_for_metric("lending_utilization") == "local_compute"


def test_sector_required_metrics_include_universal_and_sector_fields():
    lending = required_metrics_for_sector("lending")
    spot = required_metrics_for_sector("spot_dex")
    perp = required_metrics_for_sector("perp_dex")

    for metric in UNIVERSAL_REQUIRED_METRICS:
        assert metric in lending
        assert metric in spot
        assert metric in perp

    assert "supplied_tvl" in lending
    assert "volume" in spot
    assert "open_interest" in perp


def test_first_pass_coverage_and_default_no_dune_fallback():
    covered = metrics_covered_by_first_pass(["protocol-deep-dive", "market-analysis", "risk-assessment"])
    assert "annualized_protocol_revenue" in covered
    assert "volume" in covered
    assert "hacks" in covered
    assert policy_for_metric("annualized_protocol_revenue").get("fallback_sources") == []


def test_first_pass_skill_aliases_map_to_canonical():
    assert canonical_first_pass_skill("defillama-openapi-skill") == "protocol-deep-dive"
    assert canonical_first_pass_skill("defillama-api") == "market-analysis"
    covered = metrics_covered_by_first_pass(["defillama-openapi-skill", "defillama-api", "risk-assessment"])
    assert "annualized_protocol_revenue" in covered
    assert "volume" in covered
    assert "hacks" in covered
