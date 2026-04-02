"""Service orchestrator for the external collector agent."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import httpx
from loguru import logger

from collector_agent.config import Settings, get_settings
from collector_agent.contracts import CollectorError, CollectorRequest, CollectorResponse, SourceResult
from collector_agent.normalizer import failed_source_result, utc_now
from collector_agent.sources import BaseSourceAdapter, build_default_adapters


class CollectorAgentService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        adapters: dict[str, BaseSourceAdapter] | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.adapters = adapters or build_default_adapters(self.settings)
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=None))

    async def collect(self, request: CollectorRequest) -> CollectorResponse:
        deadline_at = time.monotonic() + request.deadline_sec
        async with self.client_factory() as client:
            tasks = [
                self._collect_one(
                    source_name=source_name,
                    request=request,
                    client=client,
                    deadline_at=deadline_at,
                )
                for source_name in request.sources
            ]
            results = await asyncio.gather(*tasks)

        usable_any = any(bool(result.metrics or result.items) for result in results)
        failed_any = any(not result.success for result in results)
        top_errors = [result.error for result in results if result.error is not None]

        if usable_any and failed_any:
            status = "partial"
        elif usable_any:
            status = "ok"
        else:
            status = "error"

        return CollectorResponse(
            status=status,
            target=request.target,
            collected_at=utc_now(),
            source_results=results,
            errors=[error for error in top_errors if isinstance(error, CollectorError)],
        )

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
