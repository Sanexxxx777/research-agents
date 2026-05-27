"""State mutation helpers with ownership and overwrite guards."""

from __future__ import annotations

from typing import Any

from market_intel_agent.project_analysis.models import AnalysisState
from market_intel_agent.project_analysis.registry import location_for_metric, owner_for_metric


def get_metric_value(state: AnalysisState, metric: str) -> Any:
    loc = location_for_metric(metric)
    if not loc:
        return None
    section, field = loc
    return getattr(getattr(state, section), field)


def set_metric_value(
    state: AnalysisState,
    *,
    metric: str,
    value: Any,
    source: str,
    stage: str,
    allow_overwrite: bool = False,
) -> bool:
    if value is None:
        return False
    loc = location_for_metric(metric)
    if not loc:
        return False

    section, field = loc
    owner = owner_for_metric(metric)
    prior_value = getattr(getattr(state, section), field)
    prior_source = state.field_sources.get(metric)

    if prior_value is not None and not allow_overwrite:
        return False
    if prior_source and prior_source != owner and not allow_overwrite:
        return False

    setattr(getattr(state, section), field, value)
    state.field_sources[metric] = owner
    state.fetch_audit.append(
        {
            "event": "metric_set",
            "metric": metric,
            "source": source,
            "owner": owner,
            "stage": stage,
            "overwrote": prior_value is not None,
        }
    )
    return True
