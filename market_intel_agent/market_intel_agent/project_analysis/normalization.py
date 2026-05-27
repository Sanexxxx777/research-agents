"""Normalization for first-pass skill outputs."""

from __future__ import annotations

import re
from typing import Any


_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "annualized_protocol_revenue": ("annualized_protocol_revenue", "annualized revenue", "protocol revenue annualized"),
    "annualized_tokenholder_revenue": ("annualized_tokenholder_revenue", "tokenholder revenue annualized", "holder revenue annualized"),
    "token_unlocks_12m": ("token_unlocks_12m", "unlocks 12m", "12m unlocks"),
    "supplied_tvl": ("supplied_tvl", "supplied tvl", "supply tvl"),
    "borrowed_tvl": ("borrowed_tvl", "borrowed tvl", "borrow tvl"),
    "bad_debt": ("bad_debt", "bad debt"),
    "volume": ("volume", "trading volume", "volume 30d"),
    "open_interest": ("open_interest", "open interest"),
    "tvl": ("tvl",),
    "main_demand_kpi_growth_90d": ("main_demand_kpi_growth_90d", "kpi growth 90d", "growth 90d"),
}


def normalize_first_pass_output(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return _normalize_dict_payload(payload)
    if isinstance(payload, str):
        return _normalize_text_payload(payload)
    return {}


def _normalize_dict_payload(payload: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}

    for key, value in payload.items():
        if isinstance(value, dict):
            for sub_k, sub_v in value.items():
                flattened[sub_k] = sub_v
        else:
            flattened[key] = value

    out: dict[str, Any] = {}
    for canonical, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if alias in flattened and flattened[alias] is not None:
                out[canonical] = flattened[alias]
                break

    for passthrough in (
        "unlock_recipients",
        "value_capture_type",
        "main_demand_kpi",
        "collateral_mix",
        "borrow_mix",
        "concentration_metric",
        "retention",
        "market_depth_or_liquidity",
        "markets_count",
        "hacks",
        "treasury",
        "oracle_dependency",
    ):
        if passthrough in flattened and flattened[passthrough] is not None:
            out[passthrough] = flattened[passthrough]

    return out


def _normalize_text_payload(text: str) -> dict[str, Any]:
    lower = text.lower()
    out: dict[str, Any] = {}

    for canonical, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            pattern = rf"{re.escape(alias)}\s*[:=]\s*([$€£])?\s*([-+]?\d[\d,]*(?:\.\d+)?)"
            match = re.search(pattern, lower)
            if not match:
                continue
            raw = match.group(2).replace(",", "")
            try:
                out[canonical] = float(raw)
            except ValueError:
                continue
            break

    value_capture = re.search(r"value\s*capture\s*[:=]\s*(none|buyback|burn|revshare|staking|mixed)", lower)
    if value_capture:
        out["value_capture_type"] = value_capture.group(1)

    return out
