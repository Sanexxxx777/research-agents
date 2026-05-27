"""Deterministic two-pass project analysis pipeline."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from market_intel_agent.project_analysis.cache import Cache
from market_intel_agent.project_analysis.calculators import LocalMetricsCalculator
from market_intel_agent.project_analysis.entity_resolution import EntityResolver
from market_intel_agent.project_analysis.first_pass import FirstPassRunner
from market_intel_agent.project_analysis.models import AnalysisState, MissingField
from market_intel_agent.project_analysis.peers import PeerComparator
from market_intel_agent.project_analysis.registry import owner_for_metric, policy_for_metric, required_metrics_for_sector
from market_intel_agent.project_analysis.report import FinalReportAssembler
from market_intel_agent.project_analysis.sector_routing import SectorRouter
from market_intel_agent.project_analysis.sources import ProjectAnalysisSources
from market_intel_agent.project_analysis.state_ops import get_metric_value, set_metric_value


class ProjectAnalysisPipeline:
    """Pipeline controller that preserves state transitions and source ownership."""

    def __init__(
        self,
        *,
        config: dict[str, Any],
        queries=None,
        cache: Cache | None = None,
        sources: ProjectAnalysisSources | None = None,
        entity_resolver: EntityResolver | None = None,
        sector_router: SectorRouter | None = None,
        first_pass_runner: FirstPassRunner | None = None,
        calculator: LocalMetricsCalculator | None = None,
        peer_comparator: PeerComparator | None = None,
        report_assembler: FinalReportAssembler | None = None,
    ):
        self.config = config
        pa_cfg = config.get("project_analysis", {}) if isinstance(config, dict) else {}
        self.enable_dune_gap_fill = str(pa_cfg.get("dune_gap_fill_enabled", False)).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.cache = cache
        self.sources = sources or ProjectAnalysisSources(config=config, cache=cache)
        self.entity_resolver = entity_resolver or EntityResolver(
            sources=self.sources,
            cache=cache,
            queries=queries,
            ttl_sec=int(pa_cfg.get("entity_cache_ttl_sec", 3600)),
        )
        self.sector_router = sector_router or SectorRouter(
            cache=cache,
            ttl_sec=int(pa_cfg.get("sector_cache_ttl_sec", 3600)),
        )
        self.first_pass_runner = first_pass_runner or FirstPassRunner(config=config, sources=self.sources)
        self.calculator = calculator or LocalMetricsCalculator()
        self.peer_comparator = peer_comparator or PeerComparator(sources=self.sources)
        self.report_assembler = report_assembler or FinalReportAssembler()

    async def run(self, asset_input: str) -> dict[str, Any]:
        state = AnalysisState.initialize(asset_input=asset_input, skills=self.first_pass_runner.skills)

        entity = await self.entity_resolver.resolve(asset_input)
        state.resolved_entity = entity
        state.pipeline_status = "entity_resolved"

        cg_meta = await self.sources.fetch_coingecko_metrics(
            asset_input=asset_input,
            coingecko_id=entity.coingecko_id,
            required_metrics=(),
        )
        if cg_meta.get("coingecko_id") and not state.resolved_entity.coingecko_id:
            state.resolved_entity.coingecko_id = str(cg_meta["coingecko_id"])
        if cg_meta.get("token_symbol") and not state.resolved_entity.token_symbol:
            state.resolved_entity.token_symbol = str(cg_meta["token_symbol"])

        sector, reason = await self.sector_router.resolve(
            entity,
            coingecko_categories=list(cg_meta.get("categories") or []),
        )
        state.sector = sector
        state.fetch_audit.append({"event": "sector_resolved", "sector": sector, "reason": reason})
        cg_prefill = {k: v for k, v in cg_meta.items() if owner_for_metric(k) == "coingecko"}
        if cg_prefill:
            state.sources_used.coingecko = True
            self._apply_owner_payload(
                state,
                payload=cg_prefill,
                owner="coingecko",
                source="coingecko:entity_resolved_prefill",
                stage="entity_resolved",
            )

        first_pass = await self.first_pass_runner.run(asset_input=asset_input, entity=state.resolved_entity, sector=state.sector)
        state.sources_used.defillama = True
        state.sources_used.skills = list(first_pass.get("skills") or state.sources_used.skills)
        state.first_pass_covered_metrics = [str(item) for item in (first_pass.get("covered_metrics") or []) if str(item).strip()]
        first_pass_source_audit = [item for item in (first_pass.get("source_audit") or []) if isinstance(item, dict)]
        for item in first_pass_source_audit:
            entry = dict(item)
            entry.setdefault("stage", "first_pass_source")
            state.fetch_audit.append(entry)

        self._apply_owner_payload(
            state,
            payload=first_pass.get("normalized") or {},
            owner="defillama",
            source=f"defillama:first_pass:{first_pass.get('mode')}",
            stage="first_pass",
        )
        state.pipeline_status = "first_pass_complete"

        state.pipeline_status = "normalized"
        self._refresh_missing_fields(state, stage="post_first_pass")
        state.pipeline_status = "missing_fields_identified"

        await self._enrich_missing(state)
        state.pipeline_status = "enrichment_complete"

        self.calculator.apply(state)
        state.pipeline_status = "ratios_computed"

        await self.peer_comparator.apply(state)
        state.pipeline_status = "peer_comparison_complete"

        state.fetch_audit.append({"event": "source_cost", **self.sources.estimated_cost()})

        report_markdown = self.report_assembler.build(state)
        state.pipeline_status = "final_report_ready"

        return {
            "analysis": state.model_dump(mode="json"),
            "report_markdown": report_markdown,
            "pipeline_version": "project_analysis_v1",
        }

    async def _enrich_missing(self, state: AnalysisState) -> None:
        by_owner: dict[str, list[str]] = defaultdict(list)
        for item in state.missing_fields:
            by_owner[item.owner].append(item.field)

        cg_missing = by_owner.get("coingecko") or []
        if cg_missing:
            cg_payload = await self.sources.fetch_coingecko_metrics(
                asset_input=state.asset_input,
                coingecko_id=state.resolved_entity.coingecko_id,
                required_metrics=cg_missing,
            )
            if cg_payload:
                state.sources_used.coingecko = True
                self._apply_owner_payload(
                    state,
                    payload=cg_payload,
                    owner="coingecko",
                    source="coingecko:second_pass",
                    stage="enrichment",
                )
                if cg_payload.get("coingecko_id"):
                    state.resolved_entity.coingecko_id = str(cg_payload["coingecko_id"])

        dl_missing = by_owner.get("defillama") or []
        first_pass_covered = set(state.first_pass_covered_metrics)
        dl_non_skill_missing = [metric for metric in dl_missing if metric not in first_pass_covered]
        if dl_non_skill_missing:
            dl_payload = await self.sources.fetch_defillama_metrics(
                asset_input=state.asset_input,
                sector=state.sector,
                candidate_slug=state.resolved_entity.defillama_slug,
                coingecko_id=state.resolved_entity.coingecko_id,
                token_symbol=state.resolved_entity.token_symbol,
                required_metrics=dl_non_skill_missing,
            )
            dl_source_audit = []
            if isinstance(dl_payload, dict) and isinstance(dl_payload.get("_audit"), list):
                dl_source_audit = [item for item in dl_payload.get("_audit") or [] if isinstance(item, dict)]
                dl_payload = {k: v for k, v in dl_payload.items() if k != "_audit"}
            for item in dl_source_audit:
                entry = dict(item)
                entry.setdefault("stage", "second_pass_source")
                state.fetch_audit.append(entry)
            if dl_payload:
                state.sources_used.defillama = True
                self._apply_owner_payload(
                    state,
                    payload=dl_payload,
                    owner="defillama",
                    source="defillama:second_pass",
                    stage="enrichment",
                )
                if dl_payload.get("defillama_slug"):
                    state.resolved_entity.defillama_slug = str(dl_payload["defillama_slug"])

            # Optional Dune gap-fill for non-skill fields only (disabled by default).
            still_missing = [metric for metric in dl_non_skill_missing if get_metric_value(state, metric) is None]
            if self.enable_dune_gap_fill and still_missing and hasattr(self.sources, "fetch_dune_metrics"):
                dune_payload = await self.sources.fetch_dune_metrics(
                    asset_input=state.asset_input,
                    sector=state.sector,
                    coingecko_id=state.resolved_entity.coingecko_id,
                    token_symbol=state.resolved_entity.token_symbol,
                    required_metrics=still_missing,
                )
                if dune_payload:
                    self._apply_owner_payload(
                        state,
                        payload=dune_payload,
                        owner="defillama",
                        source="dune:second_pass_gap_fill",
                        stage="enrichment",
                    )

        self._refresh_missing_fields(state, stage="post_enrichment")

    def _refresh_missing_fields(self, state: AnalysisState, *, stage: str) -> None:
        required = required_metrics_for_sector(state.sector)
        missing: list[MissingField] = []
        for metric in required:
            value = get_metric_value(state, metric)
            if value is None:
                policy = policy_for_metric(metric)
                owner = str(policy.get("owner") or owner_for_metric(metric))
                fallback = [
                    str(item)
                    for item in (policy.get("fallback_sources") or [])
                    if str(item).strip()
                ]
                if owner == "defillama" and self.enable_dune_gap_fill:
                    fallback = [*fallback, "dune"]
                reason = self._reason_for_missing_metric(state=state, metric=metric) or (
                    "field is null after deterministic source routing"
                )
                missing.append(
                    MissingField(
                        field=metric,
                        owner=owner,
                        stage=stage,
                        reason=reason,
                        attempted_sources=[owner, *fallback],
                    )
                )
        state.missing_fields = missing

    @staticmethod
    def _reason_for_missing_metric(*, state: AnalysisState, metric: str) -> str | None:
        for entry in reversed(state.fetch_audit):
            if not isinstance(entry, dict):
                continue
            event = str(entry.get("event") or "")
            if event == "metric_unavailable" and str(entry.get("metric") or "") == metric:
                reason = str(entry.get("reason") or "").strip()
                attempted = entry.get("attempted_slugs")
                if isinstance(attempted, list) and attempted:
                    return f"{reason}; attempted_slugs={attempted}"
                return reason or None
            if event == "defillama_budget_exhausted":
                missing_metrics = entry.get("missing_metrics")
                if isinstance(missing_metrics, list) and metric in missing_metrics:
                    limit = entry.get("limit")
                    return f"defillama call budget exhausted (limit={limit})"
        return None

    def _apply_owner_payload(
        self,
        state: AnalysisState,
        *,
        payload: dict[str, Any],
        owner: str,
        source: str,
        stage: str,
    ) -> None:
        for metric, value in payload.items():
            metric_owner = owner_for_metric(metric)
            if metric_owner != owner:
                state.fetch_audit.append(
                    {
                        "event": "metric_rejected_wrong_owner",
                        "metric": metric,
                        "payload_owner": owner,
                        "registry_owner": metric_owner,
                        "source": source,
                        "stage": stage,
                    }
                )
                continue
            set_metric_value(
                state,
                metric=metric,
                value=value,
                source=source,
                stage=stage,
            )
