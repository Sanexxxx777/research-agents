"""Service orchestrator for the external collector agent."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import httpx
from loguru import logger

from collector_agent.config import Settings, get_settings
from collector_agent.contracts import CollectorError, CollectorRequest, CollectorResponse, SourceResult
from collector_agent.docs_profile import DocumentationProfileBuilder, ProjectProfile
from collector_agent.normalizer import failed_source_result, utc_now
from collector_agent.rules import build_agent_diagnostics
from collector_agent.sources import BaseSourceAdapter, build_default_adapters


class CollectorAgentService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        adapters: dict[str, BaseSourceAdapter] | None = None,
        profile_builder: DocumentationProfileBuilder | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.adapters = adapters or build_default_adapters(self.settings)
        self.profile_builder = profile_builder or DocumentationProfileBuilder(self.settings)
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=None))

    async def collect(self, request: CollectorRequest) -> CollectorResponse:
        deadline_at = time.monotonic() + request.deadline_sec
        requested_sources = list(request.sources)
        non_dune_sources = [source for source in requested_sources if source != "dune"]
        dune_requested = "dune" in requested_sources

        async with self.client_factory() as client:
            project_profile = await self._build_project_profile(
                request=request,
                client=client,
                deadline_at=deadline_at,
            )

            results_by_source: dict[str, SourceResult] = {}

            if non_dune_sources:
                tasks = [
                    self._collect_one(
                        source_name=source_name,
                        request=request,
                        client=client,
                        deadline_at=deadline_at,
                    )
                    for source_name in non_dune_sources
                ]
                base_results = await asyncio.gather(*tasks)
                for result in base_results:
                    results_by_source[result.source] = result

            if dune_requested:
                prelim_results = [results_by_source[name] for name in non_dune_sources if name in results_by_source]
                prelim_diagnostics = build_agent_diagnostics(
                    request,
                    prelim_results,
                    project_profile=project_profile,
                )
                dune_gap_metrics = self._dune_gap_metrics(prelim_diagnostics)
                dune_asset_type = str(prelim_diagnostics.get("asset_type") or "unknown_other")

                dune_result = await self._collect_one(
                    source_name="dune",
                    request=request,
                    client=client,
                    deadline_at=deadline_at,
                    dune_gap_metrics=dune_gap_metrics,
                    dune_asset_type=dune_asset_type,
                )
                results_by_source["dune"] = dune_result

            results = [results_by_source[name] for name in requested_sources if name in results_by_source]

        usable_any = any(bool(result.metrics or result.items) for result in results)
        failed_any = any(not result.success for result in results)
        top_errors = [result.error for result in results if result.error is not None]

        if usable_any and failed_any:
            status = "partial"
        elif usable_any:
            status = "ok"
        else:
            status = "error"

        diagnostics = build_agent_diagnostics(request, results, project_profile=project_profile)
        return CollectorResponse(
            status=status,
            target=request.target,
            collected_at=utc_now(),
            source_results=results,
            errors=[error for error in top_errors if isinstance(error, CollectorError)],
            diagnostics=diagnostics,
        )

    def _dune_gap_metrics(self, diagnostics: dict[str, Any]) -> list[str]:
        by_metric = diagnostics.get("by_metric")
        if not isinstance(by_metric, dict):
            return []

        gaps: list[str] = []
        for metric, row in by_metric.items():
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").strip().lower()
            if status == "found":
                continue
            preferred = [str(item).strip().lower() for item in (row.get("preferred_sources") or [])]
            attempted = [str(item).strip().lower() for item in (row.get("attempted_sources") or [])]
            future = [str(item).strip().lower() for item in (row.get("future_sources") or [])]
            all_sources = preferred + attempted + future
            if any("dune" in source for source in all_sources):
                gaps.append(str(metric))
        return sorted(dict.fromkeys(gaps))

    async def _build_project_profile(
        self,
        *,
        request: CollectorRequest,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> ProjectProfile | None:
        profile_deadline_at = min(
            deadline_at,
            time.monotonic() + min(self.settings.docs_stage_cap_seconds, max(request.deadline_sec * 0.5, 0.5)),
        )
        try:
            return await self.profile_builder.build(
                request,
                client=client,
                deadline_at=profile_deadline_at,
                refresh=request.refresh_profile,
            )
        except Exception as exc:
            logger.warning(f"[collector_agent] docs profile build failed: {exc}")
            return None

    async def _collect_one(
        self,
        *,
        source_name: str,
        request: CollectorRequest,
        client: httpx.AsyncClient,
        deadline_at: float,
        dune_gap_metrics: list[str] | None = None,
        dune_asset_type: str | None = None,
    ) -> SourceResult:
        adapter = self.adapters[source_name]
        start = time.perf_counter()
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            return failed_source_result(
                source=source_name,
                elapsed_ms=0,
                code="timeout",
                message="deadline exceeded before source started",
                retryable=True,
                timed_out=True,
                warnings=["browser fallback is not implemented in v1"],
                provider=source_name,
            )

        try:
            if source_name == "dune":
                result = await asyncio.wait_for(
                    adapter.collect(
                        request,
                        client=client,
                        deadline_at=deadline_at,
                        gap_metrics=dune_gap_metrics or [],
                        asset_type=dune_asset_type or "unknown_other",
                    ),
                    timeout=remaining,
                )
            else:
                result = await asyncio.wait_for(
                    adapter.collect(request, client=client, deadline_at=deadline_at),
                    timeout=remaining,
                )
        except asyncio.TimeoutError:
            result = failed_source_result(
                source=source_name,
                elapsed_ms=0,
                code="timeout",
                message="deadline exceeded while collecting source",
                retryable=True,
                timed_out=True,
                warnings=["browser fallback is not implemented in v1"],
                provider=source_name,
            )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            retryable = status_code >= 500 or status_code == 429
            result = failed_source_result(
                source=source_name,
                elapsed_ms=0,
                code="upstream_http_error",
                message=f"upstream returned HTTP {status_code}",
                retryable=retryable,
                details={"status_code": status_code},
                warnings=["browser fallback is not implemented in v1"],
                provider=source_name,
                endpoint=str(exc.request.url),
            )
        except httpx.HTTPError as exc:
            result = failed_source_result(
                source=source_name,
                elapsed_ms=0,
                code="upstream_transport_error",
                message=str(exc),
                retryable=True,
                warnings=["browser fallback is not implemented in v1"],
                provider=source_name,
            )
        except TimeoutError:
            result = failed_source_result(
                source=source_name,
                elapsed_ms=0,
                code="timeout",
                message="deadline exceeded while preparing source request",
                retryable=True,
                timed_out=True,
                warnings=["browser fallback is not implemented in v1"],
                provider=source_name,
            )
        except Exception as exc:
            logger.exception(f"[collector_agent] unexpected {source_name} failure")
            result = failed_source_result(
                source=source_name,
                elapsed_ms=0,
                code="internal_error",
                message=str(exc) or exc.__class__.__name__,
                retryable=True,
                warnings=["browser fallback is not implemented in v1"],
                provider=source_name,
            )

        elapsed_ms = max(0, int((time.perf_counter() - start) * 1000))
        return result.model_copy(update={"elapsed_ms": elapsed_ms})
