"""Typed contracts for Market Intel Agent v1 internals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceFetchResult:
    source: str
    metrics: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    citation_url: str | None = None
    status: str = "ok"
    note: str | None = None


@dataclass
class ResolvedTarget:
    id: int | None
    name: str
    ticker: str | None = None
    category: str | None = None
    coingecko_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourcePlan:
    profile: str
    allowed_sources: list[str]
    required_metrics: list[str]
