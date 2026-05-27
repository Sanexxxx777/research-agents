"""Explicit metric ownership and fetch policy registry."""

from __future__ import annotations

from typing import Literal

from market_intel_agent.project_analysis.models import SectorType, SourceOwner

MetricLocation = tuple[Literal["universal", "sector_metrics", "risk", "computed", "comparison"], str]

FIRST_PASS_SKILLS: tuple[str, ...] = (
    "protocol-deep-dive",
    "market-analysis",
    "risk-assessment",
)

# Runtime aliases for installed skill slugs.
FIRST_PASS_SKILL_ALIASES: dict[str, str] = {
    "protocol-deep-dive": "protocol-deep-dive",
    "defillama-openapi-skill": "protocol-deep-dive",
    "market-analysis": "market-analysis",
    "defillama-api": "market-analysis",
    "market-analysis-cn": "market-analysis",
    "risk-assessment": "risk-assessment",
}

FIRST_PASS_SKILL_METRICS: dict[str, tuple[str, ...]] = {
    "protocol-deep-dive": (
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
        "tvl",
    ),
    "market-analysis": (
        "volume",
        "open_interest",
        "retention",
        "market_depth_or_liquidity",
        "markets_count",
    ),
    "risk-assessment": (
        "hacks",
        "treasury",
        "oracle_dependency",
    ),
}


UNIVERSAL_REQUIRED_METRICS: tuple[str, ...] = (
    "market_cap",
    "fdv",
    "circulating_supply",
    "total_supply",
    "max_supply",
    "spot_volume_30d",
    "annualized_protocol_revenue",
    "annualized_tokenholder_revenue",
    "token_unlocks_12m",
    "unlock_recipients",
    "value_capture_type",
    "main_demand_kpi",
    "main_demand_kpi_growth_90d",
)


SECTOR_REQUIRED_METRICS: dict[SectorType, tuple[str, ...]] = {
    "lending": (
        "supplied_tvl",
        "borrowed_tvl",
        "bad_debt",
        "collateral_mix",
        "borrow_mix",
        "concentration_metric",
    ),
    "spot_dex": (
        "volume",
        "tvl",
        "retention",
        "market_depth_or_liquidity",
    ),
    "perp_dex": (
        "volume",
        "open_interest",
        "retention",
        "market_depth_or_liquidity",
        "markets_count",
    ),
    "unknown": tuple(),
}


METRIC_OWNERS: dict[str, SourceOwner] = {
    # CoinGecko-owned
    "market_cap": "coingecko",
    "fdv": "coingecko",
    "current_price": "coingecko",
    "spot_volume_30d": "coingecko",
    "circulating_supply": "coingecko",
    "total_supply": "coingecko",
    "max_supply": "coingecko",

    # DefiLlama-owned
    "annualized_protocol_revenue": "defillama",
    "annualized_tokenholder_revenue": "defillama",
    "tvl": "defillama",
    "fees": "defillama",
    "token_unlocks_12m": "defillama",
    "unlock_recipients": "defillama",
    "value_capture_type": "defillama",
    "main_demand_kpi": "defillama",
    "main_demand_kpi_growth_90d": "defillama",
    "supplied_tvl": "defillama",
    "borrowed_tvl": "defillama",
    "bad_debt": "defillama",
    "collateral_mix": "defillama",
    "borrow_mix": "defillama",
    "concentration_metric": "defillama",
    "volume": "defillama",
    "open_interest": "defillama",
    "retention": "defillama",
    "market_depth_or_liquidity": "defillama",
    "markets_count": "defillama",
    "hacks": "defillama",
    "treasury": "defillama",
    "oracle_dependency": "defillama",

    # locally computed
    "fdv_mc_ratio": "local_compute",
    "circulating_ratio": "local_compute",
    "unlocks_12m_pct_of_circulating": "local_compute",
    "mc_to_revenue": "local_compute",
    "fdv_to_revenue": "local_compute",
    "mc_to_tokenholder_revenue": "local_compute",
    "revenue_yield": "local_compute",
    "tokenholder_revenue_yield": "local_compute",
    "lending_utilization": "local_compute",
    "dex_volume_tvl": "local_compute",
    "perp_volume_oi": "local_compute",
}

# Explicit policy registry used by second-pass orchestrator.
METRIC_FETCH_POLICY: dict[str, dict[str, object]] = {
    metric: {
        "owner": owner,
        "strategy": "local_compute" if owner == "local_compute" else "remote_fetch",
        "preferred_source": owner if owner in {"coingecko", "defillama"} else "local",
        "fallback_sources": [],
    }
    for metric, owner in METRIC_OWNERS.items()
}


METRIC_LOCATIONS: dict[str, MetricLocation] = {
    "market_cap": ("universal", "market_cap"),
    "fdv": ("universal", "fdv"),
    "current_price": ("universal", "current_price"),
    "circulating_supply": ("universal", "circulating_supply"),
    "total_supply": ("universal", "total_supply"),
    "max_supply": ("universal", "max_supply"),
    "spot_volume_30d": ("universal", "spot_volume_30d"),
    "annualized_protocol_revenue": ("universal", "annualized_protocol_revenue"),
    "annualized_tokenholder_revenue": ("universal", "annualized_tokenholder_revenue"),
    "token_unlocks_12m": ("universal", "token_unlocks_12m"),
    "unlock_recipients": ("universal", "unlock_recipients"),
    "value_capture_type": ("universal", "value_capture_type"),
    "main_demand_kpi": ("universal", "main_demand_kpi"),
    "main_demand_kpi_growth_90d": ("universal", "main_demand_kpi_growth_90d"),

    "supplied_tvl": ("sector_metrics", "supplied_tvl"),
    "borrowed_tvl": ("sector_metrics", "borrowed_tvl"),
    "bad_debt": ("sector_metrics", "bad_debt"),
    "collateral_mix": ("sector_metrics", "collateral_mix"),
    "borrow_mix": ("sector_metrics", "borrow_mix"),
    "concentration_metric": ("sector_metrics", "concentration_metric"),
    "volume": ("sector_metrics", "volume"),
    "tvl": ("sector_metrics", "tvl"),
    "retention": ("sector_metrics", "retention"),
    "market_depth_or_liquidity": ("sector_metrics", "market_depth_or_liquidity"),
    "open_interest": ("sector_metrics", "open_interest"),
    "markets_count": ("sector_metrics", "markets_count"),

    "hacks": ("risk", "hacks"),
    "treasury": ("risk", "treasury"),
    "oracle_dependency": ("risk", "oracle_dependency"),

    "fdv_mc_ratio": ("computed", "fdv_mc_ratio"),
    "circulating_ratio": ("computed", "circulating_ratio"),
    "unlocks_12m_pct_of_circulating": ("computed", "unlocks_12m_pct_of_circulating"),
    "mc_to_revenue": ("computed", "mc_to_revenue"),
    "fdv_to_revenue": ("computed", "fdv_to_revenue"),
    "mc_to_tokenholder_revenue": ("computed", "mc_to_tokenholder_revenue"),
    "revenue_yield": ("computed", "revenue_yield"),
    "tokenholder_revenue_yield": ("computed", "tokenholder_revenue_yield"),
    "lending_utilization": ("computed", "lending_utilization"),
    "dex_volume_tvl": ("computed", "dex_volume_tvl"),
    "perp_volume_oi": ("computed", "perp_volume_oi"),
}


COMPUTED_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "fdv_mc_ratio": ("fdv", "market_cap"),
    "circulating_ratio": ("circulating_supply", "max_supply", "total_supply"),
    "unlocks_12m_pct_of_circulating": ("token_unlocks_12m", "circulating_supply"),
    "mc_to_revenue": ("market_cap", "annualized_protocol_revenue"),
    "fdv_to_revenue": ("fdv", "annualized_protocol_revenue"),
    "mc_to_tokenholder_revenue": ("market_cap", "annualized_tokenholder_revenue"),
    "revenue_yield": ("annualized_protocol_revenue", "market_cap"),
    "tokenholder_revenue_yield": ("annualized_tokenholder_revenue", "market_cap"),
    "lending_utilization": ("borrowed_tvl", "supplied_tvl"),
    "dex_volume_tvl": ("volume", "tvl"),
    "perp_volume_oi": ("volume", "open_interest"),
}


def owner_for_metric(metric: str) -> SourceOwner:
    return METRIC_OWNERS.get(metric, "defillama")


def location_for_metric(metric: str) -> MetricLocation | None:
    return METRIC_LOCATIONS.get(metric)


def required_metrics_for_sector(sector: SectorType) -> list[str]:
    return [*UNIVERSAL_REQUIRED_METRICS, *SECTOR_REQUIRED_METRICS.get(sector, tuple())]


def policy_for_metric(metric: str) -> dict[str, object]:
    return METRIC_FETCH_POLICY.get(
        metric,
        {
            "owner": owner_for_metric(metric),
            "strategy": "remote_fetch",
            "preferred_source": "defillama",
            "fallback_sources": [],
        },
    )


def metrics_for_first_pass_skill(skill_name: str) -> tuple[str, ...]:
    canonical = canonical_first_pass_skill(skill_name)
    return FIRST_PASS_SKILL_METRICS.get(canonical, tuple())


def canonical_first_pass_skill(skill_name: str) -> str:
    key = str(skill_name or "").strip().lower()
    return FIRST_PASS_SKILL_ALIASES.get(key, key)


def canonicalize_first_pass_skills(skills: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        canonical = canonical_first_pass_skill(skill)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        ordered.append(canonical)
    return ordered


def metrics_covered_by_first_pass(skills: list[str]) -> list[str]:
    covered: set[str] = set()
    for skill in canonicalize_first_pass_skills(skills):
        covered.update(metrics_for_first_pass_skill(skill))
    return sorted(covered)
