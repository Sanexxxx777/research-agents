"""Cross-sector metric schema and phased rollout for Market Intel Agent.

This module is a planning contract for all target sectors. It intentionally does
not change v1 runtime source collection or profile routing.
"""

from __future__ import annotations

import re
from typing import Any, Final

TARGET_SECTORS: Final[tuple[str, ...]] = (
    "defi_lending",
    "dex_spot",
    "perp_dex",
    "l1_l2",
    "lst_lrt",
    "stablecoins",
    "bridges",
    "rwa",
    "oracles",
    "depin",
    "ai",
    "dex_aggregators",
    "asset_management",
    "nft_marketplaces",
    "gaming",
    "social",
    "prediction_markets",
    "memes",
    "infrastructure",
)

PRIORITY_TIERS: Final[tuple[str, ...]] = ("must", "should", "optional_later")

METRIC_GROUPS: Final[tuple[str, ...]] = (
    "universal_base",
    "sector_metrics",
    "derived_metrics",
    "competitor_comparison",
    "gaps",
)

FUNDAMENTAL_HORIZONS: Final[tuple[str, ...]] = ("30d", "90d", "1y")
SHORT_TERM_HORIZONS: Final[tuple[str, ...]] = ("24h",)

INFRASTRUCTURE_CHILD_PROFILES: Final[tuple[str, ...]] = (
    "l1_l2",
    "bridges",
    "oracles",
    "depin",
)

SECTOR_CLASSIFICATION_PRIORITY: Final[tuple[str, ...]] = (
    "defi_lending",
    "perp_dex",
    "dex_spot",
    "stablecoins",
    "lst_lrt",
    "rwa",
    "oracles",
    "bridges",
    "depin",
    "ai",
    "dex_aggregators",
    "asset_management",
    "nft_marketplaces",
    "gaming",
    "social",
    "prediction_markets",
    "memes",
    "l1_l2",
    "infrastructure",
)

SECTOR_CLASSIFICATION_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "defi_lending": ("lending", "borrow", "loan", "money market", "cdp", "credit market"),
    "dex_spot": ("dex", "amm", "swap", "spot exchange", "spot dex"),
    "perp_dex": ("perp", "perpetual", "derivative", "futures", "perps"),
    "l1_l2": ("l1", "l2", "layer 1", "layer 2", "rollup", "mainnet", "blockchain", "execution layer"),
    "lst_lrt": ("lst", "lrt", "liquid staking", "restaking", "staked eth", "eigenlayer"),
    "stablecoins": ("stablecoin", "usd pegged", "fiat backed", "peg", "issuer"),
    "bridges": ("bridge", "bridging", "cross-chain", "message passing", "interop"),
    "rwa": ("rwa", "real world asset", "treasury token", "tokenized treasury", "tokenized credit"),
    "oracles": ("oracle", "price feed", "data feed", "attestation", "data availability oracle"),
    "depin": ("depin", "decentralized physical infrastructure", "physical node", "wireless network", "storage network"),
    "ai": ("ai", "agent", "agents", "llm", "inference", "model", "gpu compute", "copilot"),
    "dex_aggregators": ("dex aggregator", "aggregator", "routing", "smart order routing", "swap aggregator", "intent"),
    "asset_management": ("asset management", "vault", "yield vault", "strategy", "portfolio", "index", "structured product"),
    "nft_marketplaces": ("nft marketplace", "nft", "marketplace", "collectibles", "creator royalties"),
    "gaming": ("gaming", "gamefi", "game", "metaverse", "play to earn", "play-to-earn"),
    "social": ("social", "socialfi", "creator", "fan token", "community", "identity"),
    "prediction_markets": ("prediction market", "prediction markets", "betting", "forecast", "outcome market", "sportsbook"),
    "memes": ("meme", "memes", "memecoin", "community token"),
    "infrastructure": (
        "infrastructure",
        "infra",
        "middleware",
        "stack",
        "data availability",
        "sequencer",
        "indexer",
        "rpc",
        "rollup stack",
        "modular",
    ),
}

_KEYWORD_BOUNDARY_PATTERN: Final[str] = r"[a-z0-9]"


def matches_sector_keywords(text: str, sector: str) -> bool:
    """Keyword matcher with token boundaries to avoid substring false positives."""
    haystack = str(text or "").strip().lower()
    if not haystack:
        return False

    for raw_keyword in SECTOR_CLASSIFICATION_KEYWORDS.get(sector) or ():
        keyword = str(raw_keyword or "").strip().lower()
        if not keyword:
            continue
        pattern = rf"(?<!{_KEYWORD_BOUNDARY_PATTERN}){re.escape(keyword)}(?!{_KEYWORD_BOUNDARY_PATTERN})"
        if re.search(pattern, haystack):
            return True
    return False

UNIVERSAL_BASE_SCHEMA: Final[dict[str, list[str]]] = {
    "must": [
        "market_cap",
        "fdv",
        "price_usd",
        "growth_30d",
        "growth_90d",
        "growth_1y",
        "market_state",
    ],
    "should": [
        "circulating_supply",
        "total_supply",
        "volume_30d",
        "price_change_30d",
        "price_change_90d",
        "price_change_1y",
        "btc_price",
        "btc_24h",
        "tvl",
    ],
    "optional_later": [
        "volume_24h",
        "price_change_24h",
        "price_change_7d",
        "active_users_30d",
        "token_holder_count",
        "treasury_usd",
        "governance_participation_rate",
    ],
}

SECTOR_SCHEMA: Final[dict[str, dict[str, dict[str, list[str]]]]] = {
    "l1_l2": {
        "sector_metrics": {
            "must": [
                "active_addresses_30d",
                "fees_30d",
                "revenue_30d",
                "stablecoin_supply_usd",
                "ecosystem_tvl",
                "growth_30d",
            ],
            "should": [
                "active_addresses_90d",
                "active_addresses_1y",
                "fees_90d",
                "fees_1y",
                "revenue_90d",
                "revenue_1y",
                "transactions_30d",
                "ecosystem_tvl_growth_30d",
                "ecosystem_tvl_growth_90d",
                "ecosystem_tvl_growth_1y",
                "stablecoin_supply_growth_30d",
                "app_count_30d",
                "annualized_fees",
                "annualized_revenue",
            ],
            "optional_later": [
                "transactions_24h",
                "transactions_90d",
                "transactions_1y",
                "active_addresses_24h",
                "developers_30d",
                "retention_30d",
                "sequencer_uptime_pct",
                "blob_cost_usd_24h",
            ],
        },
        "derived_metrics": {
            "must": [
                "fees_per_active_address_30d",
                "revenue_to_fees_ratio_30d",
                "stablecoin_penetration_ratio",
            ],
            "should": ["fees_to_tvl_ratio_30d", "revenue_to_tvl_ratio_30d"],
            "optional_later": ["decentralization_score", "execution_cost_efficiency", "retention_quality_score"],
        },
        "competitor_comparison": {
            "must": ["ecosystem_tvl_rank", "active_addresses_30d_rank", "fees_30d_rank", "stablecoin_supply_rank"],
            "should": ["revenue_30d_rank", "growth_30d_rank", "app_count_30d_rank"],
            "optional_later": ["transactions_30d_rank", "retention_rank"],
        },
        "gaps": {
            "must": ["missing_chain_coverage", "missing_transactions_dataset"],
            "should": ["missing_developer_dataset", "missing_retention_dataset"],
            "optional_later": ["missing_sequencer_censorship_metrics"],
        },
    },
    "dex_spot": {
        "sector_metrics": {
            "must": [
                "dex_volume_30d",
                "tvl",
                "fees_30d",
                "revenue_30d",
                "market_cap",
                "growth_30d",
            ],
            "should": [
                "dex_volume_90d",
                "dex_volume_1y",
                "fees_90d",
                "fees_1y",
                "revenue_90d",
                "revenue_1y",
                "holder_revenue_30d",
                "holder_revenue_90d",
                "holder_revenue_1y",
                "growth_90d",
                "growth_1y",
                "annualized_fees",
                "annualized_revenue",
            ],
            "optional_later": [
                "fees_24h",
                "revenue_24h",
                "dex_volume_24h",
                "unique_traders_24h",
                "pool_depth_2pct_usd",
                "swap_count_24h",
                "intent_fill_rate",
                "aggregator_volume_share",
            ],
        },
        "derived_metrics": {
            "must": ["volume_to_tvl_ratio_30d", "fees_to_volume_ratio_30d"],
            "should": ["revenue_to_volume_ratio_30d", "revenue_to_fees_ratio_30d", "mcap_to_volume_ratio_30d"],
            "optional_later": ["traders_to_tvl_efficiency", "organic_volume_ratio", "wash_trade_risk_score"],
        },
        "competitor_comparison": {
            "must": ["tvl_rank", "dex_volume_30d_rank", "fees_30d_rank"],
            "should": ["revenue_30d_rank", "growth_30d_rank"],
            "optional_later": ["price_impact_rank"],
        },
        "gaps": {
            "must": ["missing_chain_split_volume", "missing_pool_level_depth"],
            "should": ["missing_unique_trader_count", "missing_true_user_retention"],
            "optional_later": ["missing_orderflow_quality"],
        },
    },
    "perp_dex": {
        "sector_metrics": {
            "must": [
                "open_interest_usd",
                "fees_30d",
                "revenue_30d",
                "open_interest_share_30d",
                "growth_30d",
            ],
            "should": [
                "perp_volume_30d",
                "open_interest_30d",
                "open_interest_1y",
                "fees_90d",
                "fees_1y",
                "revenue_90d",
                "revenue_1y",
                "active_users_30d",
                "growth_90d",
                "growth_1y",
                "annualized_fees",
                "annualized_revenue",
            ],
            "optional_later": [
                "funding_rate",
                "liquidations_30d",
                "active_traders_30d",
                "market_depth_usd",
                "retention_30d",
                "insurance_fund_usd",
            ],
        },
        "derived_metrics": {
            "must": [
                "revenue_to_fees_ratio_30d",
                "fees_to_open_interest_ratio_30d",
                "revenue_to_open_interest_ratio_30d",
            ],
            "should": ["protocol_revenue_margin_30d", "fee_per_active_user_30d", "open_interest_change_30d"],
            "optional_later": [
                "liquidation_to_open_interest_ratio",
                "funding_rate_annualized",
                "depth_to_open_interest_ratio",
            ],
        },
        "competitor_comparison": {
            "must": [
                "open_interest_rank",
                "fees_30d_rank",
                "revenue_30d_rank",
                "open_interest_share_30d_rank",
            ],
            "should": ["growth_30d_rank", "active_users_30d_rank"],
            "optional_later": [
                "perp_volume_30d_rank",
                "funding_competitiveness",
                "liquidation_intensity_percentile",
            ],
        },
        "gaps": {
            "must": ["missing_perp_volume_dataset"],
            "should": ["missing_active_trader_dataset", "missing_liquidation_dataset"],
            "optional_later": ["missing_orderbook_depth", "missing_retention_dataset", "missing_funding_rate_dataset"],
        },
    },
    "defi_lending": {
        "sector_metrics": {
            "must": [
                "tvl",
                "borrowed_usd",
                "supplied_usd",
                "fees_30d",
                "revenue_30d",
                "holder_revenue_30d",
                "net_borrow_flow_30d",
                "market_cap",
                "growth_30d",
            ],
            "should": [
                "fees_90d",
                "revenue_90d",
                "holder_revenue_90d",
                "fees_1y",
                "revenue_1y",
                "holder_revenue_1y",
                "growth_90d",
                "growth_1y",
                "annualized_revenue",
                "annualized_holder_revenue",
                "borrowed_growth_30d",
                "utilization_rate",
                "avg_borrow_apy",
                "avg_supply_apy",
                "avg_apy",
                "liquidations_24h",
                "bad_debt_usd",
            ],
            "optional_later": [
                "volume_30d",
                "fees_24h",
                "revenue_24h",
                "holder_revenue_24h",
                "volume_24h",
                "reserve_factor",
                "isolation_mode_share",
                "oracle_exposure_share",
            ],
        },
        "derived_metrics": {
            "must": [
                "borrow_to_supply_ratio",
                "mcap_to_tvl_ratio",
                "revenue_to_tvl_ratio_30d",
            ],
            "should": ["borrow_supply_spread", "bad_debt_to_tvl_ratio", "liquidations_to_borrowed_ratio"],
            "optional_later": ["risk_adjusted_real_yield", "capital_efficiency_score"],
        },
        "competitor_comparison": {
            "must": ["tvl_rank", "fees_30d_rank", "revenue_30d_rank", "growth_30d_rank"],
            "should": ["borrowed_usd_rank", "utilization_rank", "avg_apy_rank", "bad_debt_risk_rank"],
            "optional_later": ["market_share_trend_30d"],
        },
        "gaps": {
            "must": ["missing_chain_level_borrow_supply", "missing_bad_debt_consistency"],
            "should": ["missing_liquidation_quality"],
            "optional_later": ["missing_collateral_composition"],
        },
    },
    "lst_lrt": {
        "sector_metrics": {
            "must": ["staked_assets_usd", "restaking_tvl_usd", "avg_staking_apy", "depeg_bps_30d"],
            "should": ["validator_count", "withdrawal_queue_days", "slash_events_30d"],
            "optional_later": ["operator_concentration_hhi", "restaking_reward_mix"],
        },
        "derived_metrics": {
            "must": ["restaking_ratio", "yield_spread_vs_native", "depeg_risk_score"],
            "should": ["validator_decentralization_score", "redemption_liquidity_ratio"],
            "optional_later": ["slashing_adjusted_yield"],
        },
        "competitor_comparison": {
            "must": ["restaking_tvl_rank", "depeg_stability_rank", "apy_net_risk_rank"],
            "should": ["withdrawal_latency_rank", "validator_distribution_rank"],
            "optional_later": ["institutional_adoption_rank"],
        },
        "gaps": {
            "must": ["missing_validator_distribution", "missing_restaking_slash_transparency"],
            "should": ["missing_native_vs_wrapped_flow"],
            "optional_later": ["missing_restaking_contract_risk_matrix"],
        },
    },
    "stablecoins": {
        "sector_metrics": {
            "must": [
                "circulating_supply",
                "transfer_volume_24h",
                "peg_deviation_bps",
                "active_addresses_24h",
                "reserve_ratio",
            ],
            "should": ["minted_7d", "redeemed_7d", "collateral_mix", "cex_dex_volume_share"],
            "optional_later": ["attestation_lag_days", "counterparty_exposure_score"],
        },
        "derived_metrics": {
            "must": ["net_issuance_7d", "velocity_ratio", "peg_stability_score"],
            "should": ["reserve_coverage_ratio", "collateral_concentration_score"],
            "optional_later": ["stress_redemption_capacity"],
        },
        "competitor_comparison": {
            "must": ["supply_rank", "supply_growth_share_30d", "peg_stability_rank"],
            "should": ["velocity_rank", "reserve_transparency_rank"],
            "optional_later": ["cross_chain_reach_rank"],
        },
        "gaps": {
            "must": ["missing_reserve_attestation_granularity", "missing_chain_level_supply"],
            "should": ["missing_redemption_channel_data"],
            "optional_later": ["missing_offchain_settlement_lag"],
        },
    },
    "bridges": {
        "sector_metrics": {
            "must": ["bridge_volume_24h", "bridge_tx_count_24h", "bridge_users_24h", "failed_tx_rate"],
            "should": ["net_flow_24h", "avg_transfer_time_min", "bridge_fees_24h"],
            "optional_later": ["validator_set_size", "relayer_concentration_score"],
        },
        "derived_metrics": {
            "must": ["flow_retention_7d", "fee_per_transfer", "bridge_reliability_score"],
            "should": ["latency_percentile_p95", "failure_rate_trend_30d"],
            "optional_later": ["corridor_dependency_score"],
        },
        "competitor_comparison": {
            "must": ["bridge_volume_share", "reliability_rank", "latency_rank"],
            "should": ["cost_efficiency_rank", "corridor_coverage_rank"],
            "optional_later": ["security_assurance_rank"],
        },
        "gaps": {
            "must": ["missing_corridor_level_flow", "missing_failed_tx_root_cause"],
            "should": ["missing_bridge_security_events"],
            "optional_later": ["missing_relayer_profitability"],
        },
    },
    "rwa": {
        "sector_metrics": {
            "must": ["rwa_aum_usd", "tokenized_treasuries_aum_usd", "issuance_30d_usd", "avg_yield_pct"],
            "should": ["redemption_30d_usd", "holders_count", "default_rate_pct"],
            "optional_later": ["nav_update_frequency_days", "jurisdiction_mix_score"],
        },
        "derived_metrics": {
            "must": ["net_issuance_30d_usd", "yield_spread_vs_tbill", "rwa_share_of_defi_tvl"],
            "should": ["aum_growth_90d", "concentration_score"],
            "optional_later": ["liquidity_haircut_adjusted_yield"],
        },
        "competitor_comparison": {
            "must": ["aum_rank", "aum_growth_rank", "yield_adjusted_risk_rank"],
            "should": ["holder_growth_rank", "redemption_liquidity_rank"],
            "optional_later": ["credit_quality_rank"],
        },
        "gaps": {
            "must": ["missing_nav_transparency", "missing_default_recovery_history"],
            "should": ["missing_issuer_concentration_breakdown"],
            "optional_later": ["missing_secondary_market_liquidity"],
        },
    },
    "oracles": {
        "sector_metrics": {
            "must": [
                "integrations_count",
                "secured_value_usd",
                "usage_30d",
                "fees_30d",
                "revenue_30d",
                "chain_count",
                "client_protocols_count",
                "growth_30d",
            ],
            "should": [
                "secured_value_growth_30d",
                "secured_value_growth_90d",
                "secured_value_growth_1y",
                "usage_90d",
                "usage_1y",
                "fees_90d",
                "fees_1y",
                "revenue_90d",
                "revenue_1y",
                "annualized_fees",
                "annualized_revenue",
                "network_diversification_score",
                "client_diversification_score",
                "token_dependency_score",
            ],
            "optional_later": [
                "request_count_30d",
                "update_frequency_sec",
                "deviation_bps",
                "uptime_pct",
                "slash_events_30d",
                "report_latency_ms",
                "retention_30d",
            ],
        },
        "derived_metrics": {
            "must": [
                "secured_value_to_fees_ratio_30d",
                "revenue_to_fees_ratio_30d",
                "fees_per_integration_30d",
            ],
            "should": [
                "revenue_per_client_30d",
                "usage_per_chain_30d",
                "chain_client_diversification_ratio",
            ],
            "optional_later": ["uptime_adjusted_revenue_score", "oracle_quality_score"],
        },
        "competitor_comparison": {
            "must": [
                "secured_value_rank",
                "integrations_count_rank",
                "usage_30d_rank",
                "fees_30d_rank",
                "revenue_30d_rank",
            ],
            "should": ["chain_count_rank", "client_protocols_count_rank", "growth_30d_rank"],
            "optional_later": ["client_diversification_rank", "token_dependency_rank"],
        },
        "gaps": {
            "must": ["missing_secured_value_dataset", "missing_standardized_request_count"],
            "should": ["missing_client_level_usage_breakdown", "missing_token_dependency_methodology"],
            "optional_later": ["missing_feed_level_latency", "missing_oracle_failure_postmortems"],
        },
    },
    "depin": {
        "sector_metrics": {
            "must": ["active_nodes", "node_growth_30d", "network_revenue_24h", "utilization_pct"],
            "should": ["hardware_onboarded_30d", "geographic_coverage_score", "token_emissions_24h"],
            "optional_later": ["device_quality_score", "churn_rate_30d"],
        },
        "derived_metrics": {
            "must": ["revenue_per_node", "incentive_dependency_ratio", "utilization_growth_30d"],
            "should": ["payback_period_months", "node_productivity_score"],
            "optional_later": ["organic_demand_ratio", "infra_redundancy_score"],
        },
        "competitor_comparison": {
            "must": ["active_nodes_rank", "network_revenue_rank", "utilization_rank"],
            "should": ["growth_efficiency_rank", "geographic_diversification_rank"],
            "optional_later": ["hardware_partner_rank"],
        },
        "gaps": {
            "must": ["missing_verified_demand_telemetry", "missing_sybil_node_detection"],
            "should": ["missing_node_quality_distribution"],
            "optional_later": ["missing_real_world_sla_breaches"],
        },
    },
    "ai": {
        "sector_metrics": {
            "must": [
                "ai_revenue_30d",
                "ai_active_users_30d",
                "inference_volume_30d",
                "compute_spend_30d",
                "growth_30d",
            ],
            "should": [
                "ai_revenue_90d",
                "ai_revenue_1y",
                "inference_volume_90d",
                "inference_volume_1y",
                "growth_90d",
                "growth_1y",
                "annualized_ai_revenue",
                "retention_30d",
            ],
            "optional_later": [
                "enterprise_customer_count",
                "inference_latency_ms",
                "model_quality_score",
                "safety_incident_count_30d",
            ],
        },
        "derived_metrics": {
            "must": [
                "revenue_per_active_user_30d",
                "inference_to_compute_efficiency",
                "compute_margin_30d",
            ],
            "should": [
                "inference_growth_to_revenue_growth_ratio",
                "retention_adjusted_revenue_score",
            ],
            "optional_later": ["quality_adjusted_margin", "model_cost_efficiency_score"],
        },
        "competitor_comparison": {
            "must": ["ai_revenue_30d_rank", "inference_volume_30d_rank", "growth_30d_rank"],
            "should": ["ai_active_users_30d_rank", "compute_efficiency_rank"],
            "optional_later": ["model_quality_rank"],
        },
        "gaps": {
            "must": ["missing_standardized_ai_revenue_reporting"],
            "should": ["missing_cross_project_inference_telemetry", "missing_retention_dataset"],
            "optional_later": ["missing_model_quality_benchmarking"],
        },
    },
    "infrastructure": {
        "sector_metrics": {
            "must": [
                "infra_revenue_30d",
                "infra_usage_30d",
                "infra_active_clients_30d",
                "infra_secured_value_usd",
                "growth_30d",
            ],
            "should": [
                "infra_revenue_90d",
                "infra_revenue_1y",
                "infra_usage_90d",
                "infra_usage_1y",
                "growth_90d",
                "growth_1y",
                "annualized_infra_revenue",
            ],
            "optional_later": [
                "infra_retention_30d",
                "service_uptime_pct",
                "latency_p95_ms",
                "cost_to_serve_ratio",
            ],
        },
        "derived_metrics": {
            "must": [
                "revenue_per_client_30d",
                "usage_to_revenue_ratio_30d",
                "secured_value_to_revenue_ratio_30d",
            ],
            "should": ["growth_consistency_score", "client_concentration_score"],
            "optional_later": ["sla_adjusted_revenue_score", "cost_efficiency_score"],
        },
        "competitor_comparison": {
            "must": ["infra_revenue_30d_rank", "infra_usage_30d_rank", "growth_30d_rank"],
            "should": ["infra_active_clients_30d_rank", "infra_secured_value_rank"],
            "optional_later": ["sla_quality_rank"],
        },
        "gaps": {
            "must": ["missing_subprofile_specific_dataset_mapping"],
            "should": ["missing_client_level_usage_disclosure", "missing_retention_dataset"],
            "optional_later": ["missing_sla_breach_transparency"],
        },
    },
}

ALERTS_SECTOR_ALIASES: Final[dict[str, str]] = {
    "layer 1": "l1_l2",
    "layer 2": "l1_l2",
    "dex": "dex_spot",
    "dex aggregators": "dex_aggregators",
    "derivatives": "perp_dex",
    "lending": "defi_lending",
    "liquid staking": "lst_lrt",
    "stablecoins": "stablecoins",
    "asset management": "asset_management",
    "infrastructure": "infrastructure",
    "oracles": "oracles",
    "bridges": "bridges",
    "depin": "depin",
    "nft marketplaces": "nft_marketplaces",
    "gaming": "gaming",
    "social": "social",
    "prediction markets": "prediction_markets",
    "rwa": "rwa",
    "memes": "memes",
    "ai agents": "ai",
}

ALERTS_GENERIC_ONLY_SECTORS: Final[tuple[str, ...]] = (
    "dex_aggregators",
    "asset_management",
    "nft_marketplaces",
    "gaming",
    "social",
    "prediction_markets",
    "memes",
)


def normalize_alerts_sector_name(name: str | None) -> str | None:
    raw = str(name or "").strip().lower()
    if not raw:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", raw).strip()
    return ALERTS_SECTOR_ALIASES.get(normalized) or normalized.replace(" ", "_")


def _generic_alerts_sector_schema(sector: str) -> dict[str, dict[str, list[str]]]:
    del sector
    return {
        "sector_metrics": {
            "must": ["sector_mcap", "sector_avg_24h", "sector_avg_7d", "sector_avg_30d", "sector_token_count"],
            "should": ["sector_best_token_change_24h", "sector_target_alpha_24h", "sector_peer_count"],
            "optional_later": ["sector_rotation_score", "sector_liquidity_depth_usd", "sector_revenue_30d"],
        },
        "derived_metrics": {
            "must": ["sector_target_alpha_24h"],
            "should": ["sector_target_alpha_7d", "sector_target_alpha_30d"],
            "optional_later": ["sector_relative_strength_score", "sector_beta_to_market"],
        },
        "competitor_comparison": {
            "must": ["sector_mcap_rank", "sector_avg_24h_rank", "sector_avg_30d_rank"],
            "should": ["sector_token_count_rank", "sector_best_token_rank"],
            "optional_later": ["sector_liquidity_rank", "sector_revenue_rank"],
        },
        "gaps": {
            "must": ["missing_deep_sector_fundamentals"],
            "should": ["missing_sector_revenue_dataset", "missing_sector_user_activity_dataset"],
            "optional_later": ["missing_sector_retention_dataset"],
        },
    }


for _sector in ALERTS_GENERIC_ONLY_SECTORS:
    SECTOR_SCHEMA.setdefault(_sector, _generic_alerts_sector_schema(_sector))

IMPLEMENTATION_WAVES: Final[dict[str, list[str]]] = {
    "wave_1": ["defi_lending", "dex_spot", "perp_dex"],
    "wave_2": ["l1_l2", "stablecoins", "bridges"],
    "wave_3": ["lst_lrt", "rwa", "oracles", "depin"],
    "wave_4": ["ai", "infrastructure"],
    "wave_5_alerts_generic": list(ALERTS_GENERIC_ONLY_SECTORS),
}

WAVE_RATIONALE: Final[dict[str, str]] = {
    "wave_1": (
        "Core DeFi revenue engines with strongest near-term product demand and solid baseline coverage."
    ),
    "wave_2": (
        "Adjacency to core demand with chain throughput and cross-chain monetary flow context."
    ),
    "wave_3": (
        "Requires more bespoke datasets and quality controls (attestations, oracle internals, physical infra telemetry)."
    ),
    "wave_4": (
        "Strategic expansion sectors with partial dataset fragmentation and stronger taxonomy/fallback requirements."
    ),
}

SECTOR_FAMILY_MAP: Final[dict[str, str]] = {
    "defi_lending": "defi",
    "dex_spot": "defi",
    "perp_dex": "defi",
    "l1_l2": "infrastructure",
    "lst_lrt": "defi",
    "stablecoins": "money",
    "bridges": "infrastructure",
    "rwa": "real_world_assets",
    "oracles": "infrastructure",
    "depin": "infrastructure",
    "ai": "ai",
    "dex_aggregators": "defi",
    "asset_management": "defi",
    "nft_marketplaces": "consumer",
    "gaming": "consumer",
    "social": "consumer",
    "prediction_markets": "consumer",
    "memes": "community",
    "infrastructure": "infrastructure",
}

SECTOR_PROFILE_KIND: Final[dict[str, str]] = {
    **{sector: "exact" for sector in TARGET_SECTORS},
    "infrastructure": "umbrella",
}

SECTOR_COMPETITOR_LOGIC: Final[dict[str, str]] = {
    "defi_lending": "Rank by lending balance depth + fee/revenue performance on 30d horizon.",
    "dex_spot": "Rank by 30d DEX throughput and monetization efficiency.",
    "perp_dex": "Rank by open-interest position and 30d monetization strength.",
    "l1_l2": "Rank by chain economic footprint (TVL/users/fees/stablecoin depth).",
    "lst_lrt": "Rank by staked/restaked depth and depeg-adjusted stability.",
    "stablecoins": "Rank by supply depth, peg stability, and issuance momentum.",
    "bridges": "Rank by transfer throughput, reliability, and corridor coverage.",
    "rwa": "Rank by AUM scale, issuance trend, and yield-adjusted quality.",
    "oracles": "Rank by secured value, feed coverage, and update quality.",
    "depin": "Rank by node network scale, utilization, and revenue productivity.",
    "ai": "Rank by long-horizon AI revenue, inference demand, and growth durability.",
    "dex_aggregators": "Rank by sector momentum, routing volume proxies, and peer-relative token performance until deep aggregator metrics are available.",
    "asset_management": "Rank by sector momentum, TVL/AUM proxies, and peer-relative token performance until deep vault metrics are available.",
    "nft_marketplaces": "Rank by sector momentum, marketplace volume proxies, and peer-relative token performance until deep NFT metrics are available.",
    "gaming": "Rank by sector momentum, game ecosystem growth proxies, and peer-relative token performance until deep gaming metrics are available.",
    "social": "Rank by sector momentum, user/community growth proxies, and peer-relative token performance until deep social metrics are available.",
    "prediction_markets": "Rank by sector momentum, market volume proxies, and peer-relative token performance until deep prediction-market metrics are available.",
    "memes": "Rank by sector momentum and peer-relative liquidity/market-cap behavior; fundamentals are intentionally limited.",
    "infrastructure": "Umbrella ranking via subprofile mapping first; fallback to infra-wide usage/revenue proxies.",
}

SECTOR_LIKELY_SOURCE_FAMILIES: Final[dict[str, list[str]]] = {
    "defi_lending": ["defillama_protocol", "defillama_fees_revenue", "defillama_yields", "coingecko", "hub_market_status"],
    "dex_spot": ["defillama_dexs", "defillama_fees_revenue", "defillama_protocol", "coingecko", "hub_market_status"],
    "perp_dex": ["defillama_open_interest", "defillama_fees_revenue", "defillama_protocol", "coingecko", "hub_market_status"],
    "l1_l2": ["defillama_chains", "defillama_active_users", "defillama_fees_revenue", "stablecoins_llama", "hub_market_status"],
    "lst_lrt": ["defillama_protocol", "defillama_yields", "coingecko", "hub_market_status"],
    "stablecoins": ["stablecoins_llama", "defillama_fees_revenue", "coingecko", "hub_market_status"],
    "bridges": ["defillama_bridges", "defillama_chains", "coingecko", "hub_market_status"],
    "rwa": ["defillama_protocol", "coingecko", "issuer_reports", "hub_market_status"],
    "oracles": ["defillama_fees_revenue", "defillama_oracles", "defillama_protocol", "coingecko", "hub_market_status"],
    "depin": ["project_telemetry", "coingecko", "defillama_protocol", "hub_market_status"],
    "ai": ["project_telemetry", "coingecko", "onchain_usage_feeds", "hub_market_status"],
    "dex_aggregators": ["alerts_sector_map", "coingecko", "defillama_dexs", "hub_market_status"],
    "asset_management": ["alerts_sector_map", "coingecko", "defillama_protocol", "hub_market_status"],
    "nft_marketplaces": ["alerts_sector_map", "coingecko", "marketplace_apis", "hub_market_status"],
    "gaming": ["alerts_sector_map", "coingecko", "project_telemetry", "hub_market_status"],
    "social": ["alerts_sector_map", "coingecko", "project_telemetry", "hub_market_status"],
    "prediction_markets": ["alerts_sector_map", "coingecko", "project_telemetry", "hub_market_status"],
    "memes": ["alerts_sector_map", "coingecko", "hub_market_status"],
    "infrastructure": ["defillama_protocol", "defillama_chains", "coingecko", "hub_market_status"],
}

INFRASTRUCTURE_SUBPROFILE_MODEL: Final[dict[str, Any]] = {
    "parent_sector": "infrastructure",
    "subprofiles_current": list(INFRASTRUCTURE_CHILD_PROFILES),
    "subprofiles_future": [
        "rpc_indexing",
        "modular_data_availability",
        "sequencing_shared_services",
        "interop_messaging",
    ],
    "fallback_classification_logic": (
        "If infrastructure keyword is matched and no stronger exact child-sector signal exists, classify as infrastructure."
    ),
}


def _build_sector_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for sector in TARGET_SECTORS:
        schema = SECTOR_SCHEMA[sector]
        registry[sector] = {
            "sector_family": SECTOR_FAMILY_MAP.get(sector, "other"),
            "profile_kind": SECTOR_PROFILE_KIND.get(sector, "exact"),
            "must_metrics": list(schema["sector_metrics"]["must"]),
            "should_metrics": list(schema["sector_metrics"]["should"]),
            "optional_later_metrics": list(schema["sector_metrics"]["optional_later"]),
            "competitor_logic": SECTOR_COMPETITOR_LOGIC.get(sector, ""),
            "competitor_metric_contract": {
                tier: list(metrics) for tier, metrics in schema["competitor_comparison"].items()
            },
            "likely_data_source_families": list(SECTOR_LIKELY_SOURCE_FAMILIES.get(sector, [])),
            "classification_keywords": list(SECTOR_CLASSIFICATION_KEYWORDS.get(sector, ())),
        }
        if sector in INFRASTRUCTURE_CHILD_PROFILES:
            registry[sector]["parent_sector"] = "infrastructure"
        if sector == "infrastructure":
            registry[sector]["subprofile_model"] = INFRASTRUCTURE_SUBPROFILE_MODEL
    return registry


SECTOR_REGISTRY: Final[dict[str, dict[str, Any]]] = _build_sector_registry()

FIRST_FULL_IMPLEMENTATION_TARGET: Final[str] = "defi_lending"
