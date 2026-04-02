"""Source planning for constrained v1 Market Intel."""

from __future__ import annotations

from market_intel_agent.config import (
    PROFILE_GENERIC_TOKEN,
    PROFILE_REQUIRED_METRICS,
    PROFILE_SOURCE_REGISTRY,
)
from market_intel_agent.contracts import SourcePlan


class SourcePlanner:
    def build(self, profile: str) -> SourcePlan:
        safe_profile = profile if profile in PROFILE_SOURCE_REGISTRY else PROFILE_GENERIC_TOKEN
        return SourcePlan(
            profile=safe_profile,
            allowed_sources=list(PROFILE_SOURCE_REGISTRY[safe_profile]),
            required_metrics=list(PROFILE_REQUIRED_METRICS[safe_profile]),
        )
