"""Pydantic contracts for the external collector HTTP service."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

SourceName = Literal["coingecko", "defillama", "dune"]
MethodName = Literal["api", "browser"]
StrategyName = Literal["api_first_browser_second"]
QualityStatus = Literal["complete", "fallback", "warnings"]


class TargetRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    ticker: str | None = None
    coingecko_id: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("name is required")
        return text

    @field_validator("ticker", "coingecko_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class Criteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    need_metrics: bool
    need_protocol: bool
    need_yields: bool = False
    need_competitors: bool = False


class CollectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: TargetRef
    sources: list[SourceName]
    criteria: Criteria
    strategy: StrategyName
    deadline_sec: float
    period_days: int | None = None

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: list[SourceName]) -> list[SourceName]:
        if not value:
            raise ValueError("at least one source is required")
        unique = list(dict.fromkeys(value))
        if len(unique) != len(value):
            raise ValueError("sources must be unique")
        return unique

    @field_validator("deadline_sec")
    @classmethod
    def validate_deadline(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("deadline_sec must be > 0")
        return value


class CollectorError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool
    details: Any | None = None


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: MethodName
    provider: str | None = None
    endpoint: str | None = None
    fetched_at: datetime | None = None


class Quality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: QualityStatus
    confidence: float | None = None
    stale: bool | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float | None, info: ValidationInfo) -> float | None:
        del info
        if value is None:
            return None
        return max(0.0, min(1.0, value))


class SourceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SourceName
    method: MethodName
    elapsed_ms: int
    success: bool
    timed_out: bool = False
    error: CollectorError | None = None
    metrics: dict[str, Any] | None = None
    items: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    provenance: Provenance
    quality: Quality


class CollectorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "partial", "error"]
    target: TargetRef
    collected_at: datetime
    source_results: list[SourceResult]
    errors: list[CollectorError] = Field(default_factory=list)
