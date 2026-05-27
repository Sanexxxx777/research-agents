"""Service orchestrator for the external collector agent."""

from __future__ import annotations

import asyncio
import time
from typing import Callable

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

        async with self.client_factory() as client:
            project_profile = await self._build_project_profile(
                request=request,
                client=client,
                deadline_at=deadline_at,
            )

            results_by_source: dict[str, SourceResult] = {}

            if requested_sources:
                tasks = [
                    self._collect_one(
                        source_name=source_name,
                        request=request,
                        client=client,
                        deadline_at=deadline_at,
                    )
                    for source_name in requested_sources
                ]
                base_results = await asyncio.gather(*tasks)
                for result in base_results:
                    results_by_source[result.source] = result

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
        diagnostics.pop("unavailable_until_dune", None)
        by_metric = diagnostics.get("by_metric")
        if isinstance(by_metric, dict):
            for row in by_metric.values():
                if not isinstance(row, dict):
                    continue
                if row.get("status") == "unavailable_until_dune":
                    row["status"] = "not_found"
                preferred = row.get("preferred_sources")
                if isinstance(preferred, list):
                    row["preferred_sources"] = [src for src in preferred if "dune" not in str(src).lower()]
                attempted = row.get("attempted_sources")
                if isinstance(attempted, list):
                    row["attempted_sources"] = [src for src in attempted if "dune" not in str(src).lower()]
                future = row.get("future_sources")
                if isinstance(future, list):
                    row["future_sources"] = [src for src in future if "dune" not in str(src).lower()]
        return CollectorResponse(
            status=status,
            target=request.target,
            collected_at=utc_now(),
            source_results=results,
            errors=[error for error in top_errors if isinstance(error, CollectorError)],
            diagnostics=diagnostics,
        )

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
