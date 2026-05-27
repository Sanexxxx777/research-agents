"""Market Intel Agent v1 (external, constrained, profile-driven)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from loguru import logger

try:
    from core.models import CollectionMethod, EvidenceBundle, EvidenceFact, Target
except Exception:
    class CollectionMethod(str, Enum):
        API = "api"

    @dataclass
    class Target:
        id: int | None = None
        name: str = ""
        ticker: str | None = None
        category: str | None = None
        coingecko_id: str | None = None
        metadata: dict[str, Any] = field(default_factory=dict)

    @dataclass
    class EvidenceFact:
        key: str
        value: Any
        label: str | None = None
        unit: str | None = None
        period: str | None = None
        source: str = ""
        collection_method: CollectionMethod = CollectionMethod.API
        confidence: float = 0.7
        citation_url: str | None = None
        as_of: datetime | None = None
        metadata: dict[str, Any] = field(default_factory=dict)

    @dataclass
    class EvidenceBundle:
        agent: str
        profile: str = "generic_token"
        facts: list[EvidenceFact] = field(default_factory=list)
        missing_metrics: list[str] = field(default_factory=list)
        source_plan: list[str] = field(default_factory=list)
        coverage: dict[str, Any] = field(default_factory=dict)
        metadata: dict[str, Any] = field(default_factory=dict)
from market_intel_agent.config import (
    HUB_SERVICE_TOKEN,
    PROJECT_ANALYSIS_CONFIG,
    PROJECT_ANALYSIS_ENABLED,
    PROFILE_GENERIC_TOKEN,
    PROFILE_REQUIRED_METRICS,
)
from market_intel_agent.contracts import SourceFetchResult
from market_intel_agent.hub_client import HubClient
from market_intel_agent.hub_writer import HubWriter
from market_intel_agent.project_analysis.cache import Cache as ProjectAnalysisCache
from market_intel_agent.project_analysis.pipeline import ProjectAnalysisPipeline
from market_intel_agent.profile_selector import ProfileSelector
from market_intel_agent.sector_resolver import SectorResolver
from market_intel_agent.source_planner import SourcePlanner
from market_intel_agent.sources import AlertsSectorSource, CoinGeckoSource, DefiLlamaSource, HubMarketStatusSource
from market_intel_agent.target_resolver import TargetResolver


class MarketIntelAgent:
    """External Market Intel Agent.

    v1 scope:
    - profiles: generic_token + full target sector map (12 sectors in registry/schema)
    - sources: Hub target/get/search + market/status + CoinGecko + DefiLlama
    - no browser, no wide crawling, no final thesis layer
    """

    def __init__(self) -> None:
        self.hub_client = HubClient()
        self.target_resolver = TargetResolver(self.hub_client)
        self.sector_resolver = SectorResolver()
        self.profile_selector = ProfileSelector()
        self.source_planner = SourcePlanner()
        self.hub_writer = HubWriter(self.hub_client)

        self.hub_market_source = HubMarketStatusSource(self.hub_client)
        self.alerts_sector_source = AlertsSectorSource()
        self.coingecko_source = CoinGeckoSource()
        self.defillama_source = DefiLlamaSource()
        self.project_analysis_cache = ProjectAnalysisCache()
        self.project_analysis_pipeline = (
            ProjectAnalysisPipeline(
                config=PROJECT_ANALYSIS_CONFIG,
                cache=self.project_analysis_cache,
                queries=None,
            )
            if PROJECT_ANALYSIS_ENABLED
            else None
        )

    def availability(self) -> tuple[bool, str]:
        if not HUB_SERVICE_TOKEN:
            return False, "missing HUB_INTERNAL_SERVICE_TOKEN"
        return True, "ok"

    async def run(
        self,
        *,
        query: str | None = None,
        target_id: int | None = None,
        run_id: int | None = None,
        requested_by: int | None = None,
    ) -> dict[str, Any]:
        """Main v1 entrypoint: resolve target, collect market intel, persist to Hub."""
        resolved_target = await self.target_resolver.resolve(query=query, target_id=target_id)
        target = asdict(resolved_target)
        project_analysis = await self.run_project_analysis(query or target.get("name") or "")

        market_status_result = await self._safe_collect_hub_market_status()
        coingecko_result = await self._safe_collect_coingecko(target)
        alerts_sector_result = await self._safe_collect_alerts_sector(target)
        sector_resolution = self.sector_resolver.resolve(
            target=target,
            market_status=market_status_result.raw_payload,
            coingecko_payload=coingecko_result.raw_payload,
            alerts_payload=alerts_sector_result.raw_payload,
        )
        profile = self.profile_selector.select(target=target, sector_resolution=sector_resolution)
        source_plan = self.source_planner.build(profile)

        source_results: list[SourceFetchResult] = [market_status_result]
        if "alerts_sector" in source_plan.allowed_sources:
            source_results.append(alerts_sector_result)
        if "coingecko" in source_plan.allowed_sources:
            source_results.append(coingecko_result)
        defillama_result: SourceFetchResult | None = None
        if "defillama" in source_plan.allowed_sources:
            defillama_result = await self._safe_collect_defillama(target)
            source_results.append(defillama_result)

        merged_metrics = self._merge_metrics(source_results)
        missing_metrics = [
            metric
            for metric in PROFILE_REQUIRED_METRICS.get(profile, PROFILE_REQUIRED_METRICS[PROFILE_GENERIC_TOKEN])
            if metric not in merged_metrics
        ]
        sector_block = (
            (
                (defillama_result.raw_payload or {}).get("sector_block")
                or (defillama_result.raw_payload or {}).get("lending_block")
                or (defillama_result.raw_payload or {}).get("dex_block")
                or (defillama_result.raw_payload or {}).get("l1_l2_block")
                or (defillama_result.raw_payload or {}).get("perp_block")
                or (defillama_result.raw_payload or {}).get("oracle_block")
            )
            if defillama_result
            else None
        )
        if sector_block is None:
            sector_block = (alerts_sector_result.raw_payload or {}).get("sector_block")
        sector_gaps = list((sector_block or {}).get("gaps") or [])

        created_run_id = await self.hub_writer.ensure_run(
            run_id=run_id,
            target_id=target.get("id"),
            query=query or target.get("name"),
            requested_sources=source_plan.allowed_sources,
            requested_by=requested_by,
        )

        source_dicts = [asdict(item) for item in source_results]
        observations = self.hub_writer.build_observations(
            run_id=created_run_id,
            target_id=target.get("id"),
            profile=profile,
            source_results=source_dicts,
        )
        artifacts = self.hub_writer.build_artifacts(
            run_id=created_run_id,
            source_results=source_dicts,
        )
        snapshot_payload = {
            "agent": "market_intel_agent",
            "version": "v1",
            "query": query,
            "target": target,
            "profile": profile,
            "sector_resolution": sector_resolution,
            "allowed_sources": source_plan.allowed_sources,
            "required_metrics": source_plan.required_metrics,
            "metrics": merged_metrics,
            "missing_metrics": missing_metrics,
            "sector_block": sector_block,
            "sector_gaps": sector_gaps,
            "sources": source_dicts,
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

        observation_result = await self.hub_writer.write_observations(created_run_id, observations)
        artifact_result = await self.hub_writer.write_artifacts(created_run_id, artifacts)
        snapshot_result = await self.hub_writer.write_snapshot(created_run_id, snapshot_payload)

        return {
            "run_id": created_run_id,
            "target": target,
            "profile": profile,
            "sector_resolution": sector_resolution,
            "allowed_sources": source_plan.allowed_sources,
            "metrics": merged_metrics,
            "missing_metrics": missing_metrics,
            "sector_block": sector_block,
            "gaps": sector_gaps or missing_metrics,
            "sources": source_dicts,
            "write_result": {
                "observations": observation_result,
                "artifacts": artifact_result,
                "snapshot": snapshot_result,
            },
            "project_analysis": project_analysis,
        }

    async def run_project_analysis(self, asset_input: str) -> dict[str, Any] | None:
        text = str(asset_input or "").strip()
        if not text or self.project_analysis_pipeline is None:
            return None
        try:
            return await self.project_analysis_pipeline.run(text)
        except Exception as exc:
            logger.warning(f"[market_intel] project analysis failed: {exc}")
            return None

    async def collect_market_intel(
        self,
        target: Target,
        baseline_results: list,
        period_days: int = 365,
    ) -> EvidenceBundle:
        """Compatibility method for older call-sites expecting EvidenceBundle."""
        target_dict = {
            "id": target.id,
            "name": target.name,
            "ticker": target.ticker,
            "category": target.category,
            "coingecko_id": target.coingecko_id,
            "metadata": target.metadata or {},
        }
        market_status_result = await self._safe_collect_hub_market_status()
        coingecko_result = await self._safe_collect_coingecko(target_dict)
        alerts_sector_result = await self._safe_collect_alerts_sector(target_dict)
        sector_resolution = self.sector_resolver.resolve(
            target=target_dict,
            market_status=market_status_result.raw_payload,
            coingecko_payload=coingecko_result.raw_payload,
            alerts_payload=alerts_sector_result.raw_payload,
        )
        profile = self.profile_selector.select(target=target_dict, sector_resolution=sector_resolution)
        source_plan = self.source_planner.build(profile)

        source_results: list[SourceFetchResult] = [market_status_result]
        if "alerts_sector" in source_plan.allowed_sources:
            source_results.append(alerts_sector_result)
        source_results.append(coingecko_result)
        defillama_result: SourceFetchResult | None = None
        if "defillama" in source_plan.allowed_sources:
            defillama_result = await self._safe_collect_defillama(target_dict)
            source_results.append(defillama_result)

        facts = self._collect_baseline_facts(baseline_results)
        facts.extend(self._facts_from_source_results(source_results))
        missing_metrics = self._missing_metrics(profile, facts)
        sector_block = (
            (
                (defillama_result.raw_payload or {}).get("sector_block")
                or (defillama_result.raw_payload or {}).get("lending_block")
                or (defillama_result.raw_payload or {}).get("dex_block")
                or (defillama_result.raw_payload or {}).get("l1_l2_block")
                or (defillama_result.raw_payload or {}).get("perp_block")
                or (defillama_result.raw_payload or {}).get("oracle_block")
            )
            if defillama_result
            else None
        )
        if sector_block is None:
            sector_block = (alerts_sector_result.raw_payload or {}).get("sector_block")

        return EvidenceBundle(
            agent="market_intel_agent",
            profile=profile,
            facts=facts,
            missing_metrics=missing_metrics,
            source_plan=source_plan.allowed_sources,
            coverage={
                "available": True,
                "period_days": period_days,
                "sources": {item.source: item.status for item in source_results},
                "v": "v1",
            },
            metadata={
                "target": target.name,
                "sector_resolution": sector_resolution,
                "sector_block": sector_block,
            },
        )

    async def _safe_collect_hub_market_status(self) -> SourceFetchResult:
        try:
            return await self.hub_market_source.collect()
        except Exception as exc:
            logger.warning(f"[market_intel] hub_market_status failed: {exc}")
            return SourceFetchResult(
                source="hub_market_status",
                status="error",
                note=str(exc),
            )

    async def _safe_collect_coingecko(self, target: dict[str, Any]) -> SourceFetchResult:
        try:
            return await self.coingecko_source.collect(target)
        except Exception as exc:
            logger.warning(f"[market_intel] coingecko failed: {exc}")
            return SourceFetchResult(
                source="coingecko",
                status="error",
                note=str(exc),
            )

    async def _safe_collect_alerts_sector(self, target: dict[str, Any]) -> SourceFetchResult:
        try:
            return await self.alerts_sector_source.collect(target)
        except Exception as exc:
            logger.warning(f"[market_intel] alerts_sector failed: {exc}")
            return SourceFetchResult(
                source="alerts_sector",
                status="error",
                note=str(exc),
            )

    async def _safe_collect_defillama(self, target: dict[str, Any]) -> SourceFetchResult:
        try:
            return await self.defillama_source.collect(target)
        except Exception as exc:
            logger.warning(f"[market_intel] defillama failed: {exc}")
            return SourceFetchResult(
                source="defillama",
                status="error",
                note=str(exc),
            )

    def _merge_metrics(self, source_results: list[SourceFetchResult]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for result in source_results:
            for key, value in (result.metrics or {}).items():
                if value is not None and key not in merged:
                    merged[key] = value
        return merged

    def _collect_baseline_facts(self, baseline_results: list) -> list[EvidenceFact]:
        facts: list[EvidenceFact] = []
        for result in baseline_results:
            source = result.source.value
            metrics = result.metrics
            if not metrics:
                continue
            baseline = {
                "price_usd": metrics.price_usd,
                "market_cap": metrics.market_cap,
                "volume_24h": metrics.volume_24h,
                "tvl": metrics.tvl,
                "price_change_24h": metrics.price_change_24h,
                "price_change_7d": metrics.price_change_7d,
                **(metrics.extra or {}),
            }
            for key, value in baseline.items():
                if value is None:
                    continue
                facts.append(self._fact(key=key, value=value, source=source))
        return facts

    def _facts_from_source_results(self, source_results: list[SourceFetchResult]) -> list[EvidenceFact]:
        facts: list[EvidenceFact] = []
        for result in source_results:
            for key, value in (result.metrics or {}).items():
                if value is None:
                    continue
                unit, period = self._metric_meta(key)
                facts.append(
                    self._fact(
                        key=key,
                        value=value,
                        source=result.source,
                        unit=unit,
                        period=period,
                        url=result.citation_url,
                        confidence=0.8 if result.status == "ok" else 0.4,
                    )
                )
        return facts

    def _missing_metrics(self, profile: str, facts: list[EvidenceFact]) -> list[str]:
        required = PROFILE_REQUIRED_METRICS.get(profile, PROFILE_REQUIRED_METRICS[PROFILE_GENERIC_TOKEN])
        present = {fact.key for fact in facts if fact.value is not None}
        return [metric for metric in required if metric not in present]

    def _metric_meta(self, key: str) -> tuple[str | None, str | None]:
        mapping: dict[str, tuple[str | None, str | None]] = {
            "price_usd": ("USD", None),
            "market_cap": ("USD", None),
            "volume_24h": ("USD", "24h"),
            "tvl": ("USD", None),
            "borrowed_usd": ("USD", None),
            "supplied_usd": ("USD", None),
            "collateral_related_usd": ("USD", None),
            "fdv": ("USD", None),
            "fees_30d": ("USD", "30d"),
            "fees_90d": ("USD", "90d"),
            "fees_1y": ("USD", "1y"),
            "fees_24h": ("USD", "24h"),
            "revenue_30d": ("USD", "30d"),
            "revenue_90d": ("USD", "90d"),
            "revenue_1y": ("USD", "1y"),
            "revenue_24h": ("USD", "24h"),
            "holder_revenue_30d": ("USD", "30d"),
            "holder_revenue_90d": ("USD", "90d"),
            "holder_revenue_1y": ("USD", "1y"),
            "protocol_income_24h": ("USD", "24h"),
            "protocol_income_30d": ("USD", "30d"),
            "holder_revenue_24h": ("USD", "24h"),
            "annualized_revenue": ("USD", "annualized"),
            "annualized_holder_revenue": ("USD", "annualized"),
            "net_borrow_flow_30d": ("USD", "30d"),
            "borrowed_growth_30d": ("ratio", "30d"),
            "avg_apy": ("%", None),
            "avg_supply_apy": ("%", None),
            "avg_borrow_apy": ("%", None),
            "utilization_rate": ("ratio", None),
            "dex_volume_24h": ("USD", "24h"),
            "dex_volume_30d": ("USD", "30d"),
            "dex_volume_90d": ("USD", "90d"),
            "dex_volume_1y": ("USD", "1y"),
            "volume_30d": ("USD", "30d"),
            "active_addresses_24h": ("count", "24h"),
            "active_addresses_30d": ("count", "30d"),
            "active_addresses_90d": ("count", "90d"),
            "active_addresses_1y": ("count", "1y"),
            "transactions_24h": ("count", "24h"),
            "transactions_30d": ("count", "30d"),
            "transactions_90d": ("count", "90d"),
            "transactions_1y": ("count", "1y"),
            "stablecoin_supply_usd": ("USD", None),
            "stablecoin_supply_growth_30d": ("ratio", "30d"),
            "ecosystem_tvl": ("USD", None),
            "ecosystem_tvl_growth_30d": ("ratio", "30d"),
            "ecosystem_tvl_growth_90d": ("ratio", "90d"),
            "ecosystem_tvl_growth_1y": ("ratio", "1y"),
            "app_count_30d": ("count", "30d"),
            "open_interest_usd": ("USD", "24h"),
            "open_interest_30d": ("USD", "30d"),
            "open_interest_1y": ("USD", "1y"),
            "open_interest_share_30d": ("ratio", "30d"),
            "open_interest_change_30d": ("ratio", "30d"),
            "perp_volume_30d": ("USD", "30d"),
            "active_users_30d": ("count", "30d"),
            "active_traders_30d": ("count", "30d"),
            "funding_rate": ("ratio", None),
            "liquidations_30d": ("USD", "30d"),
            "market_depth_usd": ("USD", None),
            "insurance_fund_usd": ("USD", None),
            "growth_30d": ("ratio", "30d"),
            "growth_90d": ("ratio", "90d"),
            "growth_1y": ("ratio", "1y"),
            "borrow_to_supply_ratio": ("ratio", None),
            "mcap_to_tvl_ratio": ("ratio", None),
            "mcap_tvl": ("ratio", None),
            "revenue_to_tvl_ratio_30d": ("ratio", "30d"),
            "revenue_to_tvl_ratio": ("ratio", "24h"),
            "borrow_supply_spread": ("pp", None),
            "volume_to_tvl_ratio_30d": ("ratio", "30d"),
            "fees_to_volume_ratio_30d": ("ratio", "30d"),
            "revenue_to_volume_ratio_30d": ("ratio", "30d"),
            "revenue_to_fees_ratio_30d": ("ratio", "30d"),
            "fees_per_active_address_30d": ("USD", "30d"),
            "stablecoin_penetration_ratio": ("ratio", None),
            "fees_to_tvl_ratio_30d": ("ratio", "30d"),
            "fees_to_open_interest_ratio_30d": ("ratio", "30d"),
            "revenue_to_open_interest_ratio_30d": ("ratio", "30d"),
            "protocol_revenue_margin_30d": ("ratio", "30d"),
            "fee_per_active_user_30d": ("USD", "30d"),
            "mcap_to_volume_ratio_30d": ("ratio", "30d"),
            "bad_debt_usd": ("USD", None),
            "liquidations_24h": ("USD", "24h"),
            "bad_debt_to_tvl_ratio": ("ratio", None),
            "liquidations_to_borrowed_ratio": ("ratio", "24h"),
            "price_change_24h": ("%", "24h"),
            "price_change_7d": ("%", "7d"),
            "annualized_fees": ("USD", "annualized"),
            "sector_mcap": ("USD", None),
            "sector_avg_24h": ("%", "24h"),
            "sector_avg_7d": ("%", "7d"),
            "sector_avg_30d": ("%", "30d"),
            "sector_token_count": ("count", None),
            "sector_best_token_change_24h": ("%", "24h"),
            "sector_target_alpha_24h": ("pp", "24h"),
            "sector_peer_count": ("count", None),
        }
        return mapping.get(key, (None, None))

    def _fact(
        self,
        *,
        key: str,
        value: Any,
        source: str,
        unit: str | None = None,
        period: str | None = None,
        url: str | None = None,
        confidence: float = 0.7,
    ) -> EvidenceFact:
        return EvidenceFact(
            key=key,
            label=key.replace("_", " ").title(),
            value=value,
            unit=unit,
            period=period,
            source=source,
            collection_method=CollectionMethod.API,
            confidence=confidence,
            citation_url=url,
            as_of=datetime.now(timezone.utc),
        )
