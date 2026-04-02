"""Normalization helpers for collector-agent source responses."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from collector_agent.contracts import CollectorError, CollectorResponse, Provenance, Quality, SourceResult, TargetRef


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def response_target(raw_target: dict[str, Any] | None) -> TargetRef:
    target = raw_target or {}
    name = str(target.get("name") or "").strip() or "unknown"
    ticker = _strip_optional_text(target.get("ticker"))
    coingecko_id = _strip_optional_text(target.get("coingecko_id"))
    return TargetRef(name=name, ticker=ticker, coingecko_id=coingecko_id)


def error_response(
    *,
    target: dict[str, Any] | None,
    code: str,
    message: str,
    retryable: bool,
    details: Any | None = None,
) -> CollectorResponse:
    return CollectorResponse(
        status="error",
        target=response_target(target),
        collected_at=utc_now(),
        source_results=[],
        errors=[CollectorError(code=code, message=message, retryable=retryable, details=details)],
    )


def failed_source_result(
    *,
    source: str,
    method: str = "api",
    elapsed_ms: int,
    code: str,
    message: str,
    retryable: bool,
    timed_out: bool = False,
    details: Any | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    provider: str | None = None,
    endpoint: str | None = None,
) -> SourceResult:
    return SourceResult(
        source=source,
        method=method,
        elapsed_ms=elapsed_ms,
        success=False,
        timed_out=timed_out,
        error=CollectorError(code=code, message=message, retryable=retryable, details=details),
        metadata=metadata or {},
        provenance=Provenance(
            method=method,
            provider=provider,
            endpoint=endpoint,
            fetched_at=utc_now(),
        ),
        quality=Quality(
            status="fallback" if timed_out else "warnings",
            stale=None,
            warnings=list(warnings or []),
        ),
    )


def _strip_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
