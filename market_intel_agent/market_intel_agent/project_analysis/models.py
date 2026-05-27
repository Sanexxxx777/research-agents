"""State models for deterministic project analysis pipeline."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PipelineStatus = Literal[
    "initialized",
    "entity_resolved",
    "first_pass_complete",
    "normalized",
    "missing_fields_identified",
    "enrichment_complete",
    "ratios_computed",
    "peer_comparison_complete",
    "final_report_ready",
]

SectorType = Literal["lending", "spot_dex", "perp_dex", "unknown"]
SourceOwner = Literal["coingecko", "defillama", "local_compute"]
ValueCaptureType = Literal["none", "buyback", "burn", "revshare", "staking", "mixed"]


class ResolvedEntity(BaseModel):
    name: str = ""
    slug: str | None = None
    entity_type: Literal["protocol", "token", "unknown"] = "protocol"
    token_symbol: str | None = None
    coingecko_id: str | None = None
    defillama_slug: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourcesUsed(BaseModel):
    coingecko: bool = False
    defillama: bool = False
    skills: list[str] = Field(default_factory=list)


class UniversalMetrics(BaseModel):
    market_cap: float | None = None
    fdv: float | None = None
    current_price: float | None = None
    circulating_supply: float | None = None
    total_supply: float | None = None
    max_supply: float | None = None
    spot_volume_30d: float | None = None

    annualized_protocol_revenue: float | None = None
    annualized_tokenholder_revenue: float | None = None
    token_unlocks_12m: float | None = None
    unlock_recipients: list[dict[str, Any]] | None = None
    value_capture_type: ValueCaptureType | None = None
    main_demand_kpi: float | None = None
    main_demand_kpi_growth_90d: float | None = None


class SectorMetrics(BaseModel):
    # lending
    supplied_tvl: float | None = None
    borrowed_tvl: float | None = None
    bad_debt: float | None = None
    collateral_mix: list[dict[str, Any]] | None = None
    borrow_mix: list[dict[str, Any]] | None = None
    concentration_metric: float | None = None

    # spot/perp shared
    volume: float | None = None
    retention: float | None = None
    market_depth_or_liquidity: float | None = None

    # spot specific
    tvl: float | None = None

    # perp specific
    open_interest: float | None = None
    markets_count: int | None = None


class RiskMetrics(BaseModel):
    hacks: list[dict[str, Any]] | None = None
    treasury: dict[str, Any] | None = None
    oracle_dependency: dict[str, Any] | None = None


class ComputedMetrics(BaseModel):
    fdv_mc_ratio: float | None = None
    circulating_ratio: float | None = None
    unlocks_12m_pct_of_circulating: float | None = None
    mc_to_revenue: float | None = None
    fdv_to_revenue: float | None = None
    mc_to_tokenholder_revenue: float | None = None
    revenue_yield: float | None = None
    tokenholder_revenue_yield: float | None = None
    lending_utilization: float | None = None
    dex_volume_tvl: float | None = None
    perp_volume_oi: float | None = None


class ComparisonMetrics(BaseModel):
    peer_group: list[str] = Field(default_factory=list)
    relative_position: str | None = None
    market_share: float | None = None
    market_share_trend: float | None = None


class MissingField(BaseModel):
    field: str
    owner: SourceOwner
    stage: str
    reason: str
    attempted_sources: list[str] = Field(default_factory=list)


class AnalysisState(BaseModel):
    asset_input: str
    resolved_entity: ResolvedEntity = Field(default_factory=ResolvedEntity)
    sector: SectorType = "unknown"
    sources_used: SourcesUsed = Field(default_factory=SourcesUsed)

    universal: UniversalMetrics = Field(default_factory=UniversalMetrics)
    sector_metrics: SectorMetrics = Field(default_factory=SectorMetrics)
    risk: RiskMetrics = Field(default_factory=RiskMetrics)
    computed: ComputedMetrics = Field(default_factory=ComputedMetrics)
    comparison: ComparisonMetrics = Field(default_factory=ComparisonMetrics)

    missing_fields: list[MissingField] = Field(default_factory=list)
    pipeline_status: PipelineStatus = "initialized"
    first_pass_covered_metrics: list[str] = Field(default_factory=list)

    # field -> owner/source trace for overwrite protection and auditability
    field_sources: dict[str, str] = Field(default_factory=dict)
    fetch_audit: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def initialize(cls, *, asset_input: str, skills: list[str]) -> "AnalysisState":
        return cls(
            asset_input=asset_input,
            sources_used=SourcesUsed(skills=list(skills)),
            pipeline_status="initialized",
        )
