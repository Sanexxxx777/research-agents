#!/usr/bin/env python3
"""Execute one first-pass skill deterministically and emit JSON payload."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


_SKILL_ALIASES = {
    "protocol-deep-dive": "protocol-deep-dive",
    "defillama-openapi-skill": "protocol-deep-dive",
    "market-analysis": "market-analysis",
    "defillama-api": "market-analysis",
    "market-analysis-cn": "market-analysis",
    "risk-assessment": "risk-assessment",
}


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _slugify(value: str) -> str:
    return "-".join(str(value or "").strip().lower().split())


def _parse_parent_slug(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    left, sep, right = raw.partition("#")
    if left == "parent" and right:
        return _slugify(right)
    if left:
        return _slugify(left)
    return _slugify(raw)


def _extract_tvl(value: Any) -> float | None:
    if isinstance(value, list) and value:
        tail = value[-1] if isinstance(value[-1], dict) else {}
        return _safe_float((tail or {}).get("totalLiquidityUSD"))
    return _safe_float(value)


def _normalize_hacks(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, list):
        out = [item for item in value if isinstance(item, dict)]
        return out or None
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [{"count": int(value)}]
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return [{"count": int(text)}]
    return None


def _series_growth_90d(tvl_series: Any) -> float | None:
    if not isinstance(tvl_series, list) or len(tvl_series) < 2:
        return None
    points: list[tuple[int, float]] = []
    for item in tvl_series:
        if not isinstance(item, dict):
            continue
        ts_raw = item.get("date")
        value = _safe_float(item.get("totalLiquidityUSD"))
        if ts_raw is None or value is None or value <= 0:
            continue
        try:
            ts = int(ts_raw)
        except (TypeError, ValueError):
            continue
        points.append((ts, value))
    if len(points) < 2:
        return None
    points.sort(key=lambda x: x[0])
    latest_ts, latest_value = points[-1]
    cutoff = latest_ts - 90 * 24 * 60 * 60
    base = None
    for ts, value in points:
        if ts <= cutoff:
            base = value
    if base is None or base <= 0:
        return None
    return (latest_value / base) - 1.0


def _canonical_skill(skill: str, canonical: str | None) -> str:
    if canonical:
        key = str(canonical).strip().lower()
        if key:
            return _SKILL_ALIASES.get(key, key)
    key = str(skill or "").strip().lower()
    return _SKILL_ALIASES.get(key, key)


class _FileCache:
    def __init__(self, *, cache_dir: Path, cache_key: str, ttl_sec: int):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.cache_dir / f"{cache_key}.json"
        self.ttl_sec = max(1, int(ttl_sec))
        self._payload: dict[str, Any] = {"entries": {}}
        self._load()

    def _load(self) -> None:
        try:
            if not self.path.exists():
                return
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                self._payload = payload
        except Exception:
            self._payload = {"entries": {}}

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            return

    def get(self, key: str) -> Any | None:
        entries = self._payload.get("entries")
        if not isinstance(entries, dict):
            return None
        item = entries.get(key)
        if not isinstance(item, dict):
            return None
        ts = float(item.get("ts") or 0.0)
        if (time.time() - ts) > self.ttl_sec:
            return None
        return item.get("payload")

    def put(self, key: str, payload: Any) -> None:
        entries = self._payload.setdefault("entries", {})
        if not isinstance(entries, dict):
            return
        entries[key] = {"ts": time.time(), "payload": payload}
        self._save()


class DefiLlamaSkillBridge:
    def __init__(self, *, run_py: str, uv_bin: str, base_url: str, cache: _FileCache):
        self.run_py = run_py
        self.uv_bin = uv_bin
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        try:
            self._has_runner = bool(self.run_py) and Path(self.run_py).exists()
        except PermissionError:
            self._has_runner = False

    def _json_from_mixed(self, text: str) -> Any | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        decoder = json.JSONDecoder()
        start_positions = [idx for idx, ch in enumerate(raw) if ch in "[{"]
        for start in start_positions:
            try:
                obj, _ = decoder.raw_decode(raw[start:])
                return obj
            except json.JSONDecodeError:
                continue
        return None

    def _run_defillama_api(self, args: list[str]) -> Any | None:
        if not self._has_runner:
            return None
        cmd = [self.uv_bin, "run", self.run_py, *args]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return None
        if proc.returncode != 0:
            return None
        return self._json_from_mixed(proc.stdout)

    def _fetch_http_json(self, path: str) -> Any | None:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url=url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                body = resp.read().decode("utf-8", errors="ignore")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            return None
        return self._json_from_mixed(body)

    def _fetch_cached(self, key: str, producer) -> Any | None:
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        payload = producer()
        self.cache.put(key, payload)
        return payload

    def protocols_list(self) -> list[dict[str, Any]]:
        payload = self._fetch_cached(
            "protocols:list",
            lambda: self._fetch_http_json("/protocols"),
        )
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def protocol(self, slug: str) -> dict[str, Any] | None:
        key = f"protocol:{slug}"
        payload = self._fetch_cached(
            key,
            lambda: self._run_defillama_api(["tvl", "protocol", "--protocol", slug])
            or self._fetch_http_json(f"/protocol/{urllib.parse.quote(slug)}"),
        )
        return payload if isinstance(payload, dict) else None

    def resolve_protocol(
        self,
        *,
        explicit_slug: str,
        coingecko_id: str,
        symbol: str,
        asset: str,
    ) -> tuple[dict[str, Any] | None, str, list[str]]:
        base_candidates = [
            _slugify(explicit_slug),
            _slugify(coingecko_id),
            _slugify(symbol),
            _slugify(asset),
        ]
        attempts: list[str] = []
        seen: set[str] = set()
        for candidate in base_candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            attempts.append(candidate)
            payload = self.protocol(candidate)
            if isinstance(payload, dict) and payload:
                return payload, candidate, attempts

        rows = self.protocols_list()
        if not rows:
            return None, "", attempts
        q_name = str(asset or "").strip().lower()
        q_symbol = str(symbol or "").strip().lower()
        q_cg = str(coingecko_id or "").strip().lower()

        matched: list[dict[str, Any]] = []
        for row in rows:
            row_slug = _slugify(str(row.get("slug") or ""))
            if not row_slug:
                continue
            row_name = str(row.get("name") or "").strip().lower()
            row_symbol = str(row.get("symbol") or "").strip().lower()
            row_cg = str(row.get("gecko_id") or "").strip().lower()
            if q_cg and row_cg == q_cg:
                matched.append(row)
                continue
            if q_symbol and row_symbol == q_symbol:
                matched.append(row)
                continue
            if q_name and (row_name == q_name or row_slug == _slugify(q_name) or q_name in row_name):
                matched.append(row)
                continue

        matched.sort(key=lambda x: _safe_float(x.get("tvl")) or 0.0, reverse=True)
        for row in matched[:6]:
            row_slug = _slugify(str(row.get("slug") or ""))
            if not row_slug or row_slug in seen:
                continue
            seen.add(row_slug)
            attempts.append(row_slug)
            payload = self.protocol(row_slug)
            if isinstance(payload, dict) and payload:
                return payload, row_slug, attempts

        return None, "", attempts

    def related_slug_candidates(
        self,
        *,
        primary_slug: str,
        protocol: dict[str, Any],
        coingecko_id: str,
        symbol: str,
        asset: str,
        max_candidates: int = 6,
    ) -> list[str]:
        primary = _slugify(primary_slug)
        parent = _parse_parent_slug(protocol.get("parentProtocol"))
        candidates = [
            primary,
            parent,
            _slugify(coingecko_id),
            _slugify(symbol),
            _slugify(asset),
        ]

        rows = self.protocols_list()
        if rows:
            q_cg = _slugify(coingecko_id)
            q_symbol = _slugify(symbol)
            q_name = str(asset or "").strip().lower()
            group: list[dict[str, Any]] = []
            for row in rows:
                row_slug = _slugify(str(row.get("slug") or ""))
                if not row_slug:
                    continue
                row_parent = _parse_parent_slug(row.get("parentProtocol"))
                row_cg = _slugify(str(row.get("gecko_id") or ""))
                row_symbol = _slugify(str(row.get("symbol") or ""))
                row_name = str(row.get("name") or "").strip().lower()
                if parent and row_parent and row_parent == parent:
                    group.append(row)
                    continue
                if q_cg and row_cg == q_cg:
                    group.append(row)
                    continue
                if q_symbol and row_symbol == q_symbol:
                    group.append(row)
                    continue
                if q_name and q_name in row_name:
                    group.append(row)
                    continue
            group.sort(key=lambda x: _safe_float(x.get("tvl")) or 0.0, reverse=True)
            candidates.extend([_slugify(str(item.get("slug") or "")) for item in group])

        out: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            out.append(candidate)
            if len(out) >= max_candidates:
                break
        return out

    def summary_with_candidates(
        self,
        *,
        group: str,
        slugs: list[str],
    ) -> tuple[dict[str, Any] | None, str | None, list[str]]:
        attempts: list[str] = []
        for slug in slugs:
            attempts.append(slug)
            if group == "fees":
                payload = self.fees_summary(slug)
            elif group == "dexs":
                payload = self.dex_summary(slug)
            elif group == "derivatives":
                payload = self.derivatives_summary(slug)
            elif group == "unlocks":
                payload = self.unlocks_summary(slug)
            else:
                payload = None
            if isinstance(payload, dict) and payload:
                return payload, slug, attempts
        return None, None, attempts

    def fees_summary(self, slug: str) -> dict[str, Any] | None:
        key = f"summary:fees:{slug}"
        payload = self._fetch_cached(
            key,
            lambda: self._run_defillama_api(["fees", "summary", "--protocol", slug])
            or self._fetch_http_json(f"/summary/fees/{urllib.parse.quote(slug)}"),
        )
        return payload if isinstance(payload, dict) else None

    def dex_summary(self, slug: str) -> dict[str, Any] | None:
        key = f"summary:dexs:{slug}"
        payload = self._fetch_cached(
            key,
            lambda: self._run_defillama_api(["volumes", "dex-summary", "--protocol", slug])
            or self._fetch_http_json(f"/summary/dexs/{urllib.parse.quote(slug)}"),
        )
        return payload if isinstance(payload, dict) else None

    def derivatives_summary(self, slug: str) -> dict[str, Any] | None:
        key = f"summary:derivatives:{slug}"
        payload = self._fetch_cached(
            key,
            lambda: self._run_defillama_api(["perps", "derivatives-summary", "--protocol", slug])
            or self._fetch_http_json(f"/summary/derivatives/{urllib.parse.quote(slug)}"),
        )
        return payload if isinstance(payload, dict) else None

    def unlocks_summary(self, slug: str) -> dict[str, Any] | None:
        key = f"summary:unlocks:{slug}"
        payload = self._fetch_cached(
            key,
            lambda: self._run_defillama_api(["unlocks", "protocol", "--protocol", slug])
            or self._fetch_http_json(f"/summary/unlocks/{urllib.parse.quote(slug)}"),
        )
        return payload if isinstance(payload, dict) else None


def _concentration_metric(current_chain_tvls: Any) -> float | None:
    if not isinstance(current_chain_tvls, dict):
        return None
    values = [
        _safe_float(v)
        for k, v in current_chain_tvls.items()
        if str(k).lower() not in {"borrowed", "staking", "pool2", "borrowed tvl"}
    ]
    nums = [x for x in values if x is not None and x > 0]
    total = sum(nums)
    if total <= 0 or not nums:
        return None
    return max(nums) / total


def _build_protocol_deep_dive(
    *,
    sector: str,
    protocol: dict[str, Any],
    detail_fallback: dict[str, Any] | None,
    fees: dict[str, Any] | None,
    fees_attempts: list[str] | None,
    unlocks: dict[str, Any] | None,
    unlocks_attempts: list[str] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tvl = _extract_tvl(protocol.get("tvl"))
    current_chain_tvls = protocol.get("currentChainTvls") or {}
    borrowed = _safe_float((current_chain_tvls or {}).get("borrowed"))
    supplied = _safe_float((current_chain_tvls or {}).get("staking")) or tvl
    daily_revenue = _safe_float(protocol.get("dailyRevenue") or protocol.get("revenue_24h"))
    daily_holders = _safe_float(protocol.get("dailyHoldersRevenue") or protocol.get("dailyUserFees"))
    fees_total_30d = _safe_float((fees or {}).get("total30d"))
    fees_protocol_30d = _safe_float((fees or {}).get("protocolRevenue30d"))

    out: dict[str, Any] = {"tvl": tvl}
    audit: list[dict[str, Any]] = []
    if daily_revenue is not None:
        out["annualized_protocol_revenue"] = daily_revenue * 365
    if daily_holders is not None:
        out["annualized_tokenholder_revenue"] = daily_holders * 365
    if out.get("annualized_protocol_revenue") is None:
        if fees_protocol_30d is not None:
            out["annualized_protocol_revenue"] = fees_protocol_30d * 12
        elif fees_total_30d is not None:
            out["annualized_protocol_revenue"] = fees_total_30d * 12
    if out.get("annualized_tokenholder_revenue") is None and fees_total_30d is not None:
        out["annualized_tokenholder_revenue"] = fees_total_30d * 12

    if sector == "lending":
        out["supplied_tvl"] = supplied
        out["borrowed_tvl"] = borrowed
        out["bad_debt"] = _safe_float(protocol.get("badDebt"))
        if out["bad_debt"] is None and isinstance(detail_fallback, dict):
            out["bad_debt"] = _safe_float(detail_fallback.get("badDebt"))
        if isinstance(protocol.get("collateral"), list):
            out["collateral_mix"] = protocol.get("collateral")
        elif isinstance((detail_fallback or {}).get("collateral"), list):
            out["collateral_mix"] = (detail_fallback or {}).get("collateral")
        if isinstance(protocol.get("borrowTokens"), list):
            out["borrow_mix"] = protocol.get("borrowTokens")
        elif isinstance((detail_fallback or {}).get("borrowTokens"), list):
            out["borrow_mix"] = (detail_fallback or {}).get("borrowTokens")
        cm = _concentration_metric(current_chain_tvls)
        if cm is not None:
            out["concentration_metric"] = cm
        out["main_demand_kpi"] = borrowed
        if out.get("bad_debt") is None:
            audit.append(
                {
                    "event": "metric_unavailable",
                    "metric": "bad_debt",
                    "owner": "defillama",
                    "reason": "defillama.protocol.badDebt unavailable on related protocol slugs",
                }
            )
        if out.get("collateral_mix") is None:
            audit.append(
                {
                    "event": "metric_unavailable",
                    "metric": "collateral_mix",
                    "owner": "defillama",
                    "reason": "defillama.protocol.collateral unavailable on related protocol slugs",
                }
            )
        if out.get("borrow_mix") is None:
            audit.append(
                {
                    "event": "metric_unavailable",
                    "metric": "borrow_mix",
                    "owner": "defillama",
                    "reason": "defillama.protocol.borrowTokens unavailable on related protocol slugs",
                }
            )

    change_90d = _safe_float((fees or {}).get("change_3m")) or _safe_float(protocol.get("change_3m"))
    if change_90d is None:
        change_90d = _series_growth_90d(protocol.get("tvl"))
    if change_90d is not None:
        out["main_demand_kpi_growth_90d"] = change_90d
    else:
        audit.append(
            {
                "event": "metric_unavailable",
                "metric": "main_demand_kpi_growth_90d",
                "owner": "defillama",
                "reason": "defillama.change_3m and local 90d series growth unavailable",
            }
        )

    unlock_12m = _safe_float((unlocks or {}).get("total12m") or (unlocks or {}).get("total12mUsd"))
    if unlock_12m is not None:
        out["token_unlocks_12m"] = unlock_12m
    else:
        audit.append(
            {
                "event": "metric_unavailable",
                "metric": "token_unlocks_12m",
                "owner": "defillama",
                "reason": f"defillama.summary.unlocks unavailable; attempted_slugs={unlocks_attempts or []}",
            }
        )
    recipients = (unlocks or {}).get("recipients")
    if isinstance(recipients, list):
        out["unlock_recipients"] = recipients
    else:
        audit.append(
            {
                "event": "metric_unavailable",
                "metric": "unlock_recipients",
                "owner": "defillama",
                "reason": f"defillama.summary.unlocks.recipients unavailable; attempted_slugs={unlocks_attempts or []}",
            }
        )

    if protocol.get("tokenTax"):
        out["value_capture_type"] = "buyback"
    elif _safe_float(out.get("annualized_tokenholder_revenue")) not in {None, 0.0}:
        out["value_capture_type"] = "revshare"

    if out.get("annualized_protocol_revenue") is None:
        audit.append(
            {
                "event": "metric_unavailable",
                "metric": "annualized_protocol_revenue",
                "owner": "defillama",
                "reason": f"defillama.revenue/fees summary unavailable; attempted_slugs={fees_attempts or []}",
            }
        )
    if out.get("annualized_tokenholder_revenue") is None:
        audit.append(
            {
                "event": "metric_unavailable",
                "metric": "annualized_tokenholder_revenue",
                "owner": "defillama",
                "reason": f"defillama.fees summary unavailable; attempted_slugs={fees_attempts or []}",
            }
        )

    return {k: v for k, v in out.items() if v is not None}, audit


def _build_market_analysis(
    *,
    sector: str,
    protocol: dict[str, Any],
    dex_summary: dict[str, Any] | None,
    dex_attempts: list[str] | None,
    perps_summary: dict[str, Any] | None,
    perps_attempts: list[str] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tvl = _extract_tvl(protocol.get("tvl"))
    out: dict[str, Any] = {
        "market_depth_or_liquidity": tvl,
        "retention": None,
    }
    audit: list[dict[str, Any]] = []
    vol24 = _safe_float(protocol.get("volume24h") or protocol.get("dailyVolume"))
    if vol24 is not None:
        out["volume"] = vol24 * 30
    oi = _safe_float(protocol.get("openInterest"))
    if oi is not None:
        out["open_interest"] = oi

    if sector == "spot_dex":
        v30 = _safe_float((dex_summary or {}).get("total30d"))
        if v30 is not None:
            out["volume"] = v30
        if _safe_float(out.get("volume")) is not None:
            out["main_demand_kpi"] = _safe_float(out.get("volume"))
        change = _safe_float((dex_summary or {}).get("change_3m"))
        if change is not None:
            out["main_demand_kpi_growth_90d"] = change
        if out.get("retention") is None:
            audit.append(
                {
                    "event": "metric_unavailable",
                    "metric": "retention",
                    "owner": "defillama",
                    "reason": f"defillama retention unavailable on free endpoints; attempted_slugs={dex_attempts or []}",
                }
            )

    if sector == "perp_dex":
        v30 = _safe_float((perps_summary or {}).get("total30d"))
        if v30 is not None:
            out["volume"] = v30
        if _safe_float(out.get("volume")) is not None:
            out["main_demand_kpi"] = _safe_float(out.get("volume"))
        oi = _safe_float((perps_summary or {}).get("openInterest"))
        if oi is not None:
            out["open_interest"] = oi
        markets = (perps_summary or {}).get("markets")
        if isinstance(markets, list):
            out["markets_count"] = len(markets)
        change = _safe_float((perps_summary or {}).get("change_3m"))
        if change is not None:
            out["main_demand_kpi_growth_90d"] = change
        if out.get("volume") is None:
            audit.append(
                {
                    "event": "metric_unavailable",
                    "metric": "volume",
                    "owner": "defillama",
                    "reason": (
                        "defillama.summary.derivatives.total30d unavailable or paywalled on free plan; "
                        f"attempted_slugs={perps_attempts or []}"
                    ),
                }
            )
        if out.get("open_interest") is None:
            audit.append(
                {
                    "event": "metric_unavailable",
                    "metric": "open_interest",
                    "owner": "defillama",
                    "reason": (
                        "defillama.summary.derivatives.openInterest unavailable or paywalled on free plan; "
                        f"attempted_slugs={perps_attempts or []}"
                    ),
                }
            )
        if out.get("markets_count") is None:
            audit.append(
                {
                    "event": "metric_unavailable",
                    "metric": "markets_count",
                    "owner": "defillama",
                    "reason": (
                        "defillama.summary.derivatives.markets unavailable or paywalled on free plan; "
                        f"attempted_slugs={perps_attempts or []}"
                    ),
                }
            )
        if out.get("main_demand_kpi") is None:
            audit.append(
                {
                    "event": "metric_unavailable",
                    "metric": "main_demand_kpi",
                    "owner": "defillama",
                    "reason": (
                        "defillama perp demand KPI unavailable because derivatives volume is unavailable; "
                        f"attempted_slugs={perps_attempts or []}"
                    ),
                }
            )
        if out.get("retention") is None:
            audit.append(
                {
                    "event": "metric_unavailable",
                    "metric": "retention",
                    "owner": "defillama",
                    "reason": (
                        "defillama perp retention unavailable on free endpoints; "
                        f"attempted_slugs={perps_attempts or []}"
                    ),
                }
            )

    return {k: v for k, v in out.items() if v is not None}, audit


def _build_risk_assessment(protocol: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    out: dict[str, Any] = {}
    hacks = _normalize_hacks(protocol.get("audits"))
    if hacks is not None:
        out["hacks"] = hacks
    treasury = protocol.get("treasury")
    if isinstance(treasury, dict):
        out["treasury"] = treasury
    oracle = protocol.get("oraclesBreakdown") or protocol.get("oracleDependency")
    if isinstance(oracle, list):
        providers = sorted(
            {
                str(item.get("name")).strip().lower()
                for item in oracle
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            }
        )
        out["oracle_dependency"] = {"providers": providers, "count": len(providers)}
    elif isinstance(oracle, dict):
        out["oracle_dependency"] = oracle
    return out, []


def _resolve_slug(explicit_slug: str, coingecko_id: str, symbol: str, asset: str) -> str:
    candidates = [
        explicit_slug.strip().lower(),
        coingecko_id.strip().lower(),
        symbol.strip().lower(),
        "-".join(asset.strip().lower().split()),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute one first-pass skill deterministically.")
    parser.add_argument("--skill", required=True)
    parser.add_argument("--canonical-skill", default="")
    parser.add_argument("--asset", required=True)
    parser.add_argument("--sector", default="unknown")
    parser.add_argument("--defillama-slug", default="")
    parser.add_argument("--coingecko-id", default="")
    parser.add_argument("--symbol", default="")
    args = parser.parse_args()

    canonical = _canonical_skill(args.skill, args.canonical_skill)
    slug = _resolve_slug(args.defillama_slug, args.coingecko_id, args.symbol, args.asset)
    if not slug:
        print("{}")
        return 0

    cache_dir = Path(os.getenv("MARKET_INTEL_FIRST_PASS_CACHE_DIR", "/tmp/market-intel-first-pass"))
    cache_ttl = int(os.getenv("MARKET_INTEL_FIRST_PASS_CACHE_TTL_SEC", "300"))
    run_py = os.getenv(
        "MARKET_INTEL_DEFILLAMA_API_RUN_PY",
        "/srv/projects/dev-workspace/openclaw-system/workspaces/products/market-intel-agent/main/skills/defillama-api/src/run.py",
    )
    uv_bin = os.getenv("MARKET_INTEL_UV_BIN", "uv")
    base_url = os.getenv("MARKET_INTEL_DEFILLAMA_BASE_URL", "https://api.llama.fi")

    cache = _FileCache(cache_dir=cache_dir, cache_key=f"{slug}-first-pass", ttl_sec=cache_ttl)
    bridge = DefiLlamaSkillBridge(run_py=run_py, uv_bin=uv_bin, base_url=base_url, cache=cache)

    protocol, resolved_slug, protocol_attempts = bridge.resolve_protocol(
        explicit_slug=slug,
        coingecko_id=args.coingecko_id,
        symbol=args.symbol,
        asset=args.asset,
    )
    if not protocol:
        print(
            json.dumps(
                {
                    "error": "protocol_not_found",
                    "slug": slug,
                    "_audit": [
                        {
                            "event": "metric_unavailable",
                            "metric": "protocol",
                            "owner": "defillama",
                            "reason": f"defillama.protocol unavailable; attempted_slugs={protocol_attempts}",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 0

    sector = str(args.sector or "unknown").strip().lower()
    related_slugs = bridge.related_slug_candidates(
        primary_slug=resolved_slug or slug,
        protocol=protocol,
        coingecko_id=args.coingecko_id,
        symbol=args.symbol,
        asset=args.asset,
    )
    detail_fallback = None
    if sector == "lending":
        for candidate in related_slugs:
            if candidate == resolved_slug:
                continue
            alt = bridge.protocol(candidate)
            if not isinstance(alt, dict) or not alt:
                continue
            if (
                alt.get("badDebt") is not None
                or isinstance(alt.get("collateral"), list)
                or isinstance(alt.get("borrowTokens"), list)
            ):
                detail_fallback = alt
                break

    payload: dict[str, Any]
    audit: list[dict[str, Any]]
    if canonical == "protocol-deep-dive":
        fees, _fees_slug, fees_attempts = bridge.summary_with_candidates(
            group="fees",
            slugs=related_slugs,
        )
        unlocks, _unlocks_slug, unlocks_attempts = bridge.summary_with_candidates(
            group="unlocks",
            slugs=related_slugs,
        )
        payload, audit = _build_protocol_deep_dive(
            sector=sector,
            protocol=protocol,
            detail_fallback=detail_fallback,
            fees=fees,
            fees_attempts=fees_attempts,
            unlocks=unlocks,
            unlocks_attempts=unlocks_attempts,
        )
    elif canonical == "market-analysis":
        dex_summary = None
        dex_attempts: list[str] | None = None
        perps_summary = None
        perps_attempts: list[str] | None = None
        if sector == "spot_dex":
            dex_summary, _dex_slug, dex_attempts = bridge.summary_with_candidates(
                group="dexs",
                slugs=related_slugs,
            )
        elif sector == "perp_dex":
            perps_summary, _perps_slug, perps_attempts = bridge.summary_with_candidates(
                group="derivatives",
                slugs=related_slugs,
            )
        payload, audit = _build_market_analysis(
            sector=sector,
            protocol=protocol,
            dex_summary=dex_summary,
            dex_attempts=dex_attempts,
            perps_summary=perps_summary,
            perps_attempts=perps_attempts,
        )
    elif canonical == "risk-assessment":
        payload, audit = _build_risk_assessment(protocol)
    else:
        payload = {}
        audit = []

    payload["_meta"] = {
        "skill": args.skill,
        "canonical_skill": canonical,
        "slug": resolved_slug or slug,
        "source": "defillama_skill_bridge",
        "protocol_attempted_slugs": protocol_attempts,
    }
    if audit:
        payload["_audit"] = audit
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
