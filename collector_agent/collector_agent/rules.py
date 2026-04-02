"""Deterministic rule layer for the external collector agent."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal

from collector_agent.contracts import CollectorRequest, SourceResult
from collector_agent.docs_profile import ProjectProfile

AssetType = Literal[
    "lending",
    "blockchain",
    "dex",
    "perp_dex",
    "rwa",
    "infrastructure_or_oracle_or_data",
    "unknown_other",
]
MetricStatus = Literal["found", "not_found", "unavailable_until_dune"]

_BUSINESS_PRIORITY = (
    "revenue",
    "fees",
    "market_share",
    "market_share_trend",
    "competitors",
    "niche_success",
)
_FUTURE_DUNE = ("future:dune",)


@dataclass(frozen=True)
class MetricRule:
    current_sources: tuple[str, ...] = ()
    future_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssetRule:
    asset_type: AssetType
    required_metrics: tuple[str, ...]
    optional_metrics: tuple[str, ...]
    source_priority: tuple[str, ...]
    metric_rules: dict[str, MetricRule]


@dataclass(frozen=True)
class ClassificationResult:
    asset_type: AssetType
    confidence: float
    reasons: tuple[str, ...]
    scores: dict[str, int]


def _mr(*, current: tuple[str, ...] = (), future: tuple[str, ...] = ()) -> MetricRule:
    return MetricRule(current_sources=current, future_sources=future)


_RULES: dict[AssetType, AssetRule] = {
    "lending": AssetRule(
        asset_type="lending",
        required_metrics=(
            "tvl",
            "deposits",
            "borrows",
            "yields",
            "fees",
            "revenue",
            "market_share",
            "competitors",
        ),
        optional_metrics=(
            "net_flows",
            "chain_distribution",
            "collateral_quality",
            "utilization",
            "growth_trend",
        ),
        source_priority=("defillama", "future:dune"),
        metric_rules={
            "tvl": _mr(current=("defillama",)),
            "deposits": _mr(future=("future:dune",)),
            "borrows": _mr(future=("future:dune",)),
            "yields": _mr(current=("defillama",)),
            "fees": _mr(current=("defillama",), future=("future:dune",)),
            "revenue": _mr(current=("defillama",), future=("future:dune",)),
            "market_share": _mr(current=("defillama",), future=("future:dune",)),
            "competitors": _mr(current=("defillama",)),
            "net_flows": _mr(future=("future:dune",)),
            "chain_distribution": _mr(current=("defillama",)),
            "collateral_quality": _mr(future=("future:dune",)),
            "utilization": _mr(future=("future:dune",)),
            "growth_trend": _mr(future=("future:dune",)),
        },
    ),
    "blockchain": AssetRule(
        asset_type="blockchain",
        required_metrics=(
            "active_addresses",
            "tx_count",
            "network_fees",
            "tvl",
            "user_count",
            "liquidity_flows",
            "stablecoin_volume_or_supply_in_chain",
            "competitive_position",
        ),
        optional_metrics=(
            "user_retention",
            "app_activity",
            "ecosystem_growth",
            "developer_activity_if_available",
        ),
        source_priority=("coingecko", "defillama", "future:dune"),
        metric_rules={
            "active_addresses": _mr(future=("future:dune",)),
            "tx_count": _mr(future=("future:dune",)),
            "network_fees": _mr(future=("future:dune",)),
            "tvl": _mr(current=("defillama",)),
            "user_count": _mr(future=("future:dune",)),
            "liquidity_flows": _mr(future=("future:dune",)),
            "stablecoin_volume_or_supply_in_chain": _mr(future=("future:dune",)),
            "competitive_position": _mr(current=("coingecko", "defillama"), future=("future:dune",)),
            "user_retention": _mr(future=("future:dune",)),
            "app_activity": _mr(future=("future:dune",)),
            "ecosystem_growth": _mr(future=("future:dune",)),
            "developer_activity_if_available": _mr(future=("future:dune",)),
        },
    ),
    "dex": AssetRule(
        asset_type="dex",
        required_metrics=(
            "trading_volume",
            "liquidity",
            "tvl",
            "fees",
            "revenue",
            "market_share",
            "key_pairs",
            "competitors",
        ),
        optional_metrics=(
            "active_traders",
            "volume_distribution",
            "net_flows",
            "volume_per_user",
            "concentration",
        ),
        source_priority=("defillama", "future:dune"),
        metric_rules={
            "trading_volume": _mr(current=("defillama",)),
            "liquidity": _mr(current=("defillama",), future=("future:dune",)),
            "tvl": _mr(current=("defillama",)),
            "fees": _mr(current=("defillama",), future=("future:dune",)),
            "revenue": _mr(current=("defillama",), future=("future:dune",)),
            "market_share": _mr(current=("defillama",), future=("future:dune",)),
            "key_pairs": _mr(current=("defillama",), future=("future:dune",)),
            "competitors": _mr(current=("defillama",)),
            "active_traders": _mr(future=("future:dune",)),
            "volume_distribution": _mr(future=("future:dune",)),
            "net_flows": _mr(future=("future:dune",)),
            "volume_per_user": _mr(future=("future:dune",)),
            "concentration": _mr(future=("future:dune",)),
        },
    ),
    "perp_dex": AssetRule(
        asset_type="perp_dex",
        required_metrics=(
            "trading_volume",
            "open_interest",
            "fees",
            "protocol_revenue",
            "market_share",
            "active_traders",
            "trader_retention",
            "liquidity_depth",
            "volume_to_oi_ratio",
        ),
        optional_metrics=(
            "funding_rate",
            "avg_volume_per_user",
            "market_count",
            "volume_distribution_by_market",
            "organic_vs_incentivized_volume",
            "net_flows",
            "volume_per_active_trader",
            "concentration",
            "liquidation_mechanism_quality",
        ),
        source_priority=("defillama", "future:dune"),
        metric_rules={
            "trading_volume": _mr(current=("defillama",)),
            "open_interest": _mr(current=("defillama",), future=("future:dune",)),
            "fees": _mr(current=("defillama",), future=("future:dune",)),
            "protocol_revenue": _mr(current=("defillama",), future=("future:dune",)),
            "market_share": _mr(current=("defillama",), future=("future:dune",)),
            "active_traders": _mr(future=("future:dune",)),
            "trader_retention": _mr(future=("future:dune",)),
            "liquidity_depth": _mr(future=("future:dune",)),
            "volume_to_oi_ratio": _mr(future=("future:dune",)),
            "funding_rate": _mr(future=("future:dune",)),
            "avg_volume_per_user": _mr(future=("future:dune",)),
            "market_count": _mr(future=("future:dune",)),
            "volume_distribution_by_market": _mr(future=("future:dune",)),
            "organic_vs_incentivized_volume": _mr(future=("future:dune",)),
            "net_flows": _mr(future=("future:dune",)),
            "volume_per_active_trader": _mr(future=("future:dune",)),
            "concentration": _mr(future=("future:dune",)),
            "liquidation_mechanism_quality": _mr(future=("future:dune",)),
        },
    ),
    "rwa": AssetRule(
        asset_type="rwa",
        required_metrics=(
            "aum",
            "net_flows",
            "asset_composition_or_collateral_quality",
            "yield",
            "duration_or_maturity_profile",
            "liquidity_and_redemption_terms",
            "concentration_by_assets_issuers_counterparties",
            "issuer",
            "legal_structure",
            "counterparty_and_custody_risk",
        ),
        optional_metrics=(
            "separate_inflows",
            "separate_outflows",
            "tokenization_wrappers_and_chains",
            "holder_count",
            "secondary_liquidity",
            "nav_discount_or_premium_if_applicable",
            "geographic_diversification",
            "reporting_frequency",
            "reserve_transparency",
            "operating_partners",
            "average_holding_period",
        ),
        source_priority=("future:dune", "defillama"),
        metric_rules={
            "aum": _mr(future=("future:dune",)),
            "net_flows": _mr(future=("future:dune",)),
            "asset_composition_or_collateral_quality": _mr(future=("future:dune",)),
            "yield": _mr(current=("defillama",), future=("future:dune",)),
            "duration_or_maturity_profile": _mr(future=("future:dune",)),
            "liquidity_and_redemption_terms": _mr(future=("future:dune",)),
            "concentration_by_assets_issuers_counterparties": _mr(future=("future:dune",)),
            "issuer": _mr(future=("future:dune",)),
            "legal_structure": _mr(future=("future:dune",)),
            "counterparty_and_custody_risk": _mr(future=("future:dune",)),
            "separate_inflows": _mr(future=("future:dune",)),
            "separate_outflows": _mr(future=("future:dune",)),
            "tokenization_wrappers_and_chains": _mr(current=("defillama",), future=("future:dune",)),
            "holder_count": _mr(future=("future:dune",)),
            "secondary_liquidity": _mr(future=("future:dune",)),
            "nav_discount_or_premium_if_applicable": _mr(future=("future:dune",)),
            "geographic_diversification": _mr(future=("future:dune",)),
            "reporting_frequency": _mr(future=("future:dune",)),
            "reserve_transparency": _mr(future=("future:dune",)),
            "operating_partners": _mr(future=("future:dune",)),
            "average_holding_period": _mr(future=("future:dune",)),
        },
    ),
    "infrastructure_or_oracle_or_data": AssetRule(
        asset_type="infrastructure_or_oracle_or_data",
        required_metrics=(
            "integrations",
            "chains_or_protocols_using_it",
            "fees",
            "revenue",
            "market_share",
            "competitors",
            "real_usage",
        ),
        optional_metrics=(
            "integration_growth",
            "client_retention",
            "demand_concentration",
            "ecosystem_criticality",
            "partnership_quality",
        ),
        source_priority=("coingecko", "defillama", "future:dune"),
        metric_rules={
            "integrations": _mr(current=("coingecko", "defillama"), future=("future:dune",)),
            "chains_or_protocols_using_it": _mr(current=("defillama",), future=("future:dune",)),
            "fees": _mr(current=("defillama",), future=("future:dune",)),
            "revenue": _mr(current=("defillama",), future=("future:dune",)),
            "market_share": _mr(current=("coingecko", "defillama"), future=("future:dune",)),
            "competitors": _mr(current=("defillama",)),
            "real_usage": _mr(current=("coingecko", "defillama"), future=("future:dune",)),
            "integration_growth": _mr(future=("future:dune",)),
            "client_retention": _mr(future=("future:dune",)),
            "demand_concentration": _mr(future=("future:dune",)),
            "ecosystem_criticality": _mr(future=("future:dune",)),
            "partnership_quality": _mr(future=("future:dune",)),
        },
    ),
    "unknown_other": AssetRule(
        asset_type="unknown_other",
        required_metrics=(),
        optional_metrics=("revenue", "fees", "market_share", "competitors", "niche_success"),
        source_priority=("coingecko", "defillama", "future:dune"),
        metric_rules={
            "revenue": _mr(current=("defillama",), future=("future:dune",)),
            "fees": _mr(current=("defillama",), future=("future:dune",)),
            "market_share": _mr(current=("coingecko", "defillama"), future=("future:dune",)),
            "competitors": _mr(current=("defillama",)),
            "niche_success": _mr(current=("coingecko", "defillama"), future=("future:dune",)),
        },
    ),
}

_DEFILLAMA_CATEGORY_MAP = {
    "lending": "lending",
    "borrowing": "lending",
    "chain": "blockchain",
    "chains": "blockchain",
    "blockchain": "blockchain",
    "dexes": "dex",
    "dex": "dex",
    "derivatives": "perp_dex",
    "perpetuals": "perp_dex",
    "perps": "perp_dex",
    "rwa": "rwa",
    "real world assets": "rwa",
    "oracles": "infrastructure_or_oracle_or_data",
    "oracle": "infrastructure_or_oracle_or_data",
    "data": "infrastructure_or_oracle_or_data",
    "bridge": "infrastructure_or_oracle_or_data",
    "bridges": "infrastructure_or_oracle_or_data",
}

_KEYWORD_HINTS: dict[AssetType, tuple[str, ...]] = {
    "lending": ("lending", "lend", "borrow", "loan", "credit", "cdp"),
    "blockchain": ("chain", "layer 1", "layer1", "layer 2", "layer2", "blockchain", "network"),
    "dex": ("dex", "exchange", "amm", "swap"),
    "perp_dex": ("perp", "perpetual", "derivative", "futures"),
    "rwa": ("rwa", "real world asset", "treasury", "credit fund", "bond"),
    "infrastructure_or_oracle_or_data": ("oracle", "data", "infrastructure", "bridge", "interoperability", "indexing"),
    "unknown_other": (),
}
_PROFILE_TYPE_TO_ASSET: dict[str, AssetType] = {
    "lending": "lending",
    "blockchain": "blockchain",
    "dex_spot": "dex",
    "perp_dex": "perp_dex",
    "rwa": "rwa",
    "bridge": "infrastructure_or_oracle_or_data",
    "oracle": "infrastructure_or_oracle_or_data",
    "data_infra": "infrastructure_or_oracle_or_data",
    "vault_yield": "unknown_other",
}


def get_rule(asset_type: AssetType) -> AssetRule:
    return _RULES[asset_type]


def classify_asset(
    request: CollectorRequest,
    results: list[SourceResult],
    project_profile: ProjectProfile | None = None,
) -> ClassificationResult:
    scores = {asset_type: 0 for asset_type in _RULES if asset_type != "unknown_other"}
    reasons: list[str] = []

    if project_profile is not None:
        mapped = _map_profile_project_type(project_profile.project_type)
        if mapped is not None and mapped != "unknown_other":
            boost = 12 + int(round((project_profile.confidence or 0.0) * 4))
            scores[mapped] += boost
            reasons.append(f"official_docs.project_type={project_profile.project_type}")
        elif project_profile.official_urls:
            website_hint = project_profile.what_the_project_does or ""
            mapped = _map_text_category(website_hint)
            if mapped is not None:
                scores[mapped] += 4
                reasons.append("official_website.summary")

    for result in results:
        if result.source == "defillama":
            category = str((result.metadata or {}).get("category") or "").strip().lower()
            mapped = _map_defillama_category(category)
            if mapped:
                scores[mapped] += 4
                reasons.append(f"defillama.category={category}")

    for category in _structured_categories(results):
        mapped = _map_text_category(category)
        if mapped:
            scores[mapped] += 2
            reasons.append(f"category:{category}")

    texts = list(_hint_texts(request, results, project_profile=project_profile))
    for asset_type, keywords in _KEYWORD_HINTS.items():
        if asset_type == "unknown_other":
            continue
        for keyword in keywords:
            if any(_text_matches_keyword(text, keyword) for text in texts):
                scores[asset_type] += 1
                reasons.append(f"keyword:{keyword}")

    best_type = "unknown_other"
    best_score = 0
    tied = False
    for asset_type, score in scores.items():
        if score > best_score:
            best_type = asset_type
            best_score = score
            tied = False
        elif score and score == best_score:
            tied = True

    if best_score < 2 or tied:
        return ClassificationResult(
            asset_type="unknown_other",
            confidence=0.25 if best_score else 0.1,
            reasons=tuple(reasons[:8]),
            scores=scores,
        )

    confidence = min(0.95, 0.45 + (best_score * 0.08))
    return ClassificationResult(
        asset_type=best_type,
        confidence=confidence,
        reasons=tuple(reasons[:8]),
        scores=scores,
    )


def build_agent_diagnostics(
    request: CollectorRequest,
    results: list[SourceResult],
    project_profile: ProjectProfile | None = None,
) -> dict[str, Any]:
    classification = classify_asset(request, results, project_profile=project_profile)
    rule = get_rule(classification.asset_type)

    required_attempted: list[str] = []
    optional_attempted: list[str] = []
    found_metrics: list[str] = []
    not_found_metrics: list[str] = []
    unavailable_until_dune: list[str] = []
    by_metric: dict[str, dict[str, Any]] = {}

    for metric in rule.required_metrics:
        status = _metric_diagnostic(metric, rule, request, results)
        by_metric[metric] = status
        if status["status"] != "unavailable_until_dune":
            required_attempted.append(metric)
        if status["status"] == "found":
            found_metrics.append(metric)
        elif status["status"] == "not_found":
            not_found_metrics.append(metric)
        else:
            unavailable_until_dune.append(metric)

    for metric in rule.optional_metrics:
        status = _metric_diagnostic(metric, rule, request, results)
        by_metric[metric] = status
        if status["status"] != "unavailable_until_dune":
            optional_attempted.append(metric)
        if status["status"] == "found":
            found_metrics.append(metric)
        elif status["status"] == "not_found":
            not_found_metrics.append(metric)
        else:
            unavailable_until_dune.append(metric)

    found_metrics = sorted(dict.fromkeys(found_metrics))
    not_found_metrics = sorted(dict.fromkeys(not_found_metrics))
    unavailable_until_dune = sorted(dict.fromkeys(unavailable_until_dune))

    return {
        "asset_type": classification.asset_type,
        "metric_plan_asset_type": classification.asset_type,
        "asset_type_confidence": round(classification.confidence, 2),
        "asset_type_reasons": list(classification.reasons),
        "classification_source_priority": [
            "official_docs",
            "official_website",
            "coingecko",
            "defillama",
            "unknown_other",
        ],
        "classification_basis": _classification_basis(project_profile),
        "source_priority": list(rule.source_priority),
        "priority_business_metrics": list(_BUSINESS_PRIORITY),
        "required_metrics": list(rule.required_metrics),
        "optional_metrics": list(rule.optional_metrics),
        "required_metrics_attempted": required_attempted,
        "optional_metrics_attempted": optional_attempted,
        "found_metrics": found_metrics,
        "not_found_metrics": not_found_metrics,
        "unavailable_until_dune": unavailable_until_dune,
        "by_metric": by_metric,
        "project_type": project_profile.project_type if project_profile else None,
        "project_subtype": project_profile.project_subtype if project_profile else None,
        "project_profile": project_profile.model_dump(mode="json") if project_profile else None,
    }


def _metric_diagnostic(
    metric: str,
    rule: AssetRule,
    request: CollectorRequest,
    results: list[SourceResult],
) -> dict[str, Any]:
    metric_rule = rule.metric_rules.get(metric, _mr())
    preferred_sources = list(metric_rule.current_sources + metric_rule.future_sources)
    current_attempted_sources = [source for source in metric_rule.current_sources if source in request.sources]
    future_attempted_sources = [
        source
        for source in (_normalize_future_source_name(item) for item in metric_rule.future_sources)
        if source and source in request.sources
    ]
    attempted_sources = list(dict.fromkeys(current_attempted_sources + future_attempted_sources))
    found_source = None
    for result in results:
        if result.source in attempted_sources and _metric_found(metric, result):
            found_source = result.source
            break

    if found_source:
        status: MetricStatus = "found"
    elif not attempted_sources and metric_rule.future_sources:
        status = "unavailable_until_dune"
    elif not attempted_sources and metric_rule.current_sources:
        status = "not_found"
    elif not attempted_sources:
        status = "not_found"
    elif metric_rule.future_sources and not metric_rule.current_sources and not future_attempted_sources:
        status = "unavailable_until_dune"
    else:
        status = "not_found"

    diagnostic = {
        "status": status,
        "preferred_sources": preferred_sources,
        "attempted_sources": attempted_sources,
    }
    if found_source:
        diagnostic["source"] = found_source
    if metric_rule.future_sources:
        diagnostic["future_sources"] = list(metric_rule.future_sources)
    return diagnostic


def _metric_found(metric: str, result: SourceResult) -> bool:
    metrics = result.metrics or {}
    metadata = result.metadata or {}
    items = result.items or []

    if metric == "tvl":
        return _has_number(metrics.get("tvl"))
    if metric == "trading_volume":
        return _has_number(metrics.get("trading_volume_24h")) or _has_number(metrics.get("volume_24h"))
    if metric == "open_interest":
        return _has_number(metrics.get("open_interest")) or _has_number(metrics.get("open_interest_usd"))
    if metric == "fees":
        return _has_number(metrics.get("fees_24h"))
    if metric in {"revenue", "protocol_revenue"}:
        return _has_number(metrics.get("protocol_revenue_24h")) or _has_number(metrics.get("revenue_24h"))
    if metric == "yields":
        return any(bool((item.get("metadata") or {}).get("yield_pool")) for item in items)
    if metric == "competitors":
        return any(bool((item.get("metadata") or {}).get("competitors")) for item in items)
    if metric == "market_share":
        return _can_estimate_market_share(items)
    if metric == "market_share_trend":
        return _has_number(metrics.get("change_7d")) or _has_number(metrics.get("change_1m"))
    if metric == "competitive_position":
        return _can_estimate_market_share(items) or _has_number(metrics.get("market_cap")) or _has_number(metrics.get("tvl"))
    if metric == "chain_distribution":
        if isinstance(metrics.get("chain_distribution"), dict) and bool(metrics.get("chain_distribution")):
            return True
        chains = metadata.get("chains") or _collect_item_metadata(items, "chains")
        return isinstance(chains, list) and bool(chains)
    if metric == "tokenization_wrappers_and_chains":
        chains = metadata.get("chains") or _collect_item_metadata(items, "chains")
        return isinstance(chains, list) and bool(chains)
    if metric == "chains_or_protocols_using_it":
        chains = metadata.get("chains") or _collect_item_metadata(items, "chains")
        return isinstance(chains, list) and bool(chains)
    if metric == "integrations":
        links = _collect_item_metadata(items, "official_links")
        return isinstance(links, dict) and bool(links)
    if metric == "liquidity":
        return _has_number(metrics.get("liquidity_usd")) or _has_number(metrics.get("tvl"))
    if metric == "key_pairs":
        pairs = metadata.get("key_pairs") or _collect_item_metadata(items, "key_pairs")
        return isinstance(pairs, list) and bool(pairs)
    if metric == "niche_success":
        return _can_estimate_market_share(items)
    if metric == "real_usage":
        return (
            _has_number(metrics.get("volume_24h"))
            or _has_number(metrics.get("trading_volume_24h"))
            or _has_number(metrics.get("fees_24h"))
            or _has_number(metrics.get("revenue_24h"))
        )
    if metric == "active_traders":
        return _has_number(metrics.get("active_traders")) or _has_number(metrics.get("active_users"))
    if metric == "funding_rate":
        return _has_number(metrics.get("funding_rate"))
    if metric == "liquidity_depth":
        return _has_number(metrics.get("liquidity_depth")) or _has_number(metrics.get("liquidity_depth_usd"))
    if metric == "volume_distribution":
        distribution = metrics.get("volume_distribution") or metrics.get("volume_distribution_by_market")
        return isinstance(distribution, (dict, list, str)) and bool(distribution)
    if metric == "deposits":
        return _has_number(metrics.get("deposits")) or _has_number(metrics.get("deposits_usd")) or _has_number(metrics.get("supplied_usd"))
    if metric == "borrows":
        return _has_number(metrics.get("borrows")) or _has_number(metrics.get("borrows_usd")) or _has_number(metrics.get("borrowed_usd"))
    if metric == "utilization":
        return _has_number(metrics.get("utilization")) or _has_number(metrics.get("utilization_rate"))
    if metric == "net_flows":
        return _has_number(metrics.get("net_flows")) or _has_number(metrics.get("net_flow_30d"))
    if metric == "active_addresses":
        return (
            _has_number(metrics.get("active_addresses"))
            or _has_number(metrics.get("active_addresses_24h"))
            or _has_number(metrics.get("active_addresses_30d"))
            or _has_number(metrics.get("daily_active_addresses"))
        )
    if metric == "tx_count":
        return _has_number(metrics.get("tx_count")) or _has_number(metrics.get("transactions")) or _has_number(metrics.get("transactions_24h"))
    if metric == "network_fees":
        return _has_number(metrics.get("network_fees")) or _has_number(metrics.get("network_fees_usd")) or _has_number(metrics.get("fees_24h"))
    if metric == "user_count":
        return _has_number(metrics.get("user_count")) or _has_number(metrics.get("users")) or _has_number(metrics.get("active_users"))
    if metric == "stablecoin_volume_or_supply_in_chain":
        return _has_number(metrics.get("stablecoin_supply_usd")) or _has_number(metrics.get("stablecoin_volume_usd"))
    if metric == "aum":
        return _has_number(metrics.get("aum")) or _has_number(metrics.get("aum_usd"))
    if metric == "holder_count":
        return _has_number(metrics.get("holder_count")) or _has_number(metrics.get("holders"))
    return False


def _normalize_future_source_name(source: str) -> str:
    text = str(source or "").strip().lower()
    if text.startswith("future:"):
        return text.split(":", 1)[1]
    return text


def _hint_texts(
    request: CollectorRequest,
    results: list[SourceResult],
    project_profile: ProjectProfile | None = None,
) -> list[str]:
    texts = [
        str(request.target.name or "").lower(),
        str(request.target.ticker or "").lower(),
        str(request.target.coingecko_id or "").lower(),
    ]
    if project_profile is not None:
        texts.extend(
            [
                str(project_profile.project_type or "").lower(),
                str(project_profile.project_subtype or "").lower(),
                str(project_profile.what_the_project_does or "").lower(),
                str(project_profile.business_model or "").lower(),
                str(project_profile.revenue_model or "").lower(),
            ]
        )
        texts.extend(str(keyword).lower() for keyword in project_profile.keywords or [])
        for evidence in project_profile.evidence_snippets or []:
            texts.append(str(evidence.get("signal") or "").lower())
            texts.append(str(evidence.get("snippet") or "").lower())
    for result in results:
        metadata = result.metadata or {}
        category = metadata.get("category")
        if category:
            texts.append(str(category).lower())
        categories = metadata.get("categories")
        if isinstance(categories, list):
            texts.extend(str(item).lower() for item in categories)
        for item in result.items or []:
            item_metadata = item.get("metadata") or {}
            item_category = item_metadata.get("category")
            if item_category:
                texts.append(str(item_category).lower())
            item_categories = item_metadata.get("categories")
            if isinstance(item_categories, list):
                texts.extend(str(entry).lower() for entry in item_categories)
            title = item.get("title")
            if title:
                texts.append(str(title).lower())
            content = item.get("content")
            if content:
                texts.append(str(content).lower())
    return [text for text in texts if text]


def _structured_categories(results: list[SourceResult]) -> list[str]:
    categories: list[str] = []
    for result in results:
        metadata = result.metadata or {}
        direct_category = metadata.get("category")
        if direct_category:
            direct_text = str(direct_category).lower()
            if not _is_noise_category(direct_text):
                categories.append(direct_text)
        direct_categories = metadata.get("categories")
        if isinstance(direct_categories, list):
            categories.extend(
                str(item).lower()
                for item in direct_categories
                if not _is_noise_category(str(item).lower())
            )
        for item in result.items or []:
            item_metadata = item.get("metadata") or {}
            item_category = item_metadata.get("category")
            if item_category:
                item_text = str(item_category).lower()
                if not _is_noise_category(item_text):
                    categories.append(item_text)
            item_categories = item_metadata.get("categories")
            if isinstance(item_categories, list):
                categories.extend(
                    str(entry).lower()
                    for entry in item_categories
                    if not _is_noise_category(str(entry).lower())
                )
    return [category for category in categories if category]


def _map_defillama_category(category: str) -> AssetType | None:
    text = category.strip().lower()
    if not text:
        return None
    for key, asset_type in _DEFILLAMA_CATEGORY_MAP.items():
        if _text_matches_keyword(text, key):
            return asset_type
    return None


def _map_text_category(text: str) -> AssetType | None:
    lowered = text.strip().lower()
    if not lowered:
        return None
    mapped = _map_defillama_category(lowered)
    if mapped:
        return mapped
    for asset_type, keywords in _KEYWORD_HINTS.items():
        if asset_type == "unknown_other":
            continue
        if any(_text_matches_keyword(lowered, keyword) for keyword in keywords):
            return asset_type
    return None


def _map_profile_project_type(project_type: str | None) -> AssetType | None:
    if not project_type:
        return None
    return _PROFILE_TYPE_TO_ASSET.get(project_type.strip().lower())


def _classification_basis(project_profile: ProjectProfile | None) -> str:
    if project_profile is None:
        return "aggregators_or_unknown"
    if (project_profile.official_urls or {}).get("docs"):
        return "official_docs"
    if project_profile.docs_urls_read or project_profile.official_urls:
        return "official_website"
    return "aggregators_or_unknown"


def _text_matches_keyword(text: str, keyword: str) -> bool:
    if " " in keyword or "/" in keyword or "-" in keyword:
        return keyword in text
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _is_noise_category(text: str) -> bool:
    return any(marker in text for marker in ("ecosystem", "portfolio", " index"))


def _can_estimate_market_share(items: list[dict[str, Any]]) -> bool:
    for item in items:
        metadata = item.get("metadata") or {}
        peers = metadata.get("competitors")
        if not isinstance(peers, list) or not peers:
            continue
        basis = _resolve_share_basis(metadata)
        target_snapshot = metadata.get("target_snapshot") or {}
        if basis and _has_number(target_snapshot.get(basis)):
            return True
    return False


def _resolve_share_basis(metadata: dict[str, Any]) -> str | None:
    target_snapshot = metadata.get("target_snapshot") or {}
    peers = metadata.get("competitors") or []
    for basis in ("volume_24h", "tvl", "market_cap"):
        if not _has_number(target_snapshot.get(basis)):
            continue
        if any(_has_number((peer or {}).get(basis)) for peer in peers if isinstance(peer, dict)):
            return basis
    return None


def _collect_item_metadata(items: list[dict[str, Any]], key: str) -> Any | None:
    for item in items:
        metadata = item.get("metadata") or {}
        value = metadata.get(key)
        if value:
            return value
    return None


def _has_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
