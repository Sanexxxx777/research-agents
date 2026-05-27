"""Source adapters for CoinGecko and DefiLlama with dedup and cache."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterable
from typing import Any

import httpx
from loguru import logger

from market_intel_agent.project_analysis.cache import Cache
from market_intel_agent.project_analysis.models import SectorType


class DefiLlamaBudgetExceeded(RuntimeError):
    """Raised when configured per-run DefiLlama call budget is exhausted."""


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _slugify(value: str) -> str:
    return "-".join(value.strip().lower().split())


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
    points = [
        (
            int(item.get("date")),
            _safe_float(item.get("totalLiquidityUSD")),
        )
        for item in tvl_series
        if isinstance(item, dict) and item.get("date") is not None
    ]
    points = [(ts, value) for ts, value in points if value is not None]
    if len(points) < 2:
        return None
    points.sort(key=lambda x: x[0])
    latest_ts, latest_value = points[-1]
    if latest_value is None or latest_value <= 0:
        return None
    cutoff = latest_ts - 90 * 24 * 60 * 60
    base = None
    for ts, value in points:
        if ts <= cutoff and value is not None and value > 0:
            base = value
    if base is None or base <= 0:
        return None
    return (latest_value / base) - 1.0


class ProjectAnalysisSources:
    """Shared source adapter with request-level deduplication."""

    _DEFAULT_PROTOCOL_ALIASES: dict[str, str] = {
        "aave": "aave-v3",
        "aave-token": "aave-v3",
    }

    def __init__(self, *, config: dict[str, Any], cache: Cache | None = None):
        self.config = config
        self.cache = cache
        self.coingecko_base = (
            str(config.get("project_analysis", {}).get("coingecko_base_url") or "")
            or "https://api.coingecko.com/api/v3"
        ).rstrip("/")
        self.defillama_base = (
            str(config.get("project_analysis", {}).get("defillama_base_url") or "")
            or "https://api.llama.fi"
        ).rstrip("/")
        self.dune_base = (
            str(config.get("project_analysis", {}).get("dune_base_url") or "")
            or "https://api.dune.com/api/v1"
        ).rstrip("/")
        self.dune_api_key = str(config.get("project_analysis", {}).get("dune_api_key") or "").strip()
        self.dune_query_timeout = float(config.get("project_analysis", {}).get("dune_query_timeout_sec", 25))
        self.dune_poll_interval = float(config.get("project_analysis", {}).get("dune_poll_interval_sec", 2))
        self.dune_query_ids = self._parse_query_ids(config.get("project_analysis", {}).get("dune_query_ids"))
        self.http_timeout = float(config.get("project_analysis", {}).get("http_timeout_sec", 12))
        self.cache_ttl = int(config.get("project_analysis", {}).get("cache_ttl_sec", 900))
        self.error_cache_ttl = max(
            0.0,
            float(config.get("project_analysis", {}).get("error_cache_ttl_sec", 30)),
        )
        self.defillama_min_interval_sec = max(
            0.0,
            float(config.get("project_analysis", {}).get("defillama_min_interval_ms", 250)) / 1000.0,
        )
        self.defillama_summary_max_candidates = max(
            1,
            int(config.get("project_analysis", {}).get("defillama_summary_max_candidates", 2)),
        )
        self.defillama_max_calls_per_run = max(
            0,
            int(config.get("project_analysis", {}).get("defillama_max_calls_per_run", 20)),
        )
        self.defillama_retry_max = max(
            0,
            int(config.get("project_analysis", {}).get("defillama_retry_max", 2)),
        )
        self.defillama_retry_backoff_sec = max(
            0.0,
            float(config.get("project_analysis", {}).get("defillama_retry_backoff_ms", 400)) / 1000.0,
        )
        self.coingecko_retry_max = max(
            0,
            int(config.get("project_analysis", {}).get("coingecko_retry_max", 2)),
        )
        self.coingecko_retry_backoff_sec = max(
            0.0,
            float(config.get("project_analysis", {}).get("coingecko_retry_backoff_ms", 400)) / 1000.0,
        )

        self._memo: dict[str, Any] = {}
        self._error_memo: dict[str, float] = {}
        self.call_counters: dict[str, int] = {"coingecko": 0, "defillama": 0, "dune": 0}
        self._network_call_counters: dict[str, int] = {"coingecko": 0, "defillama": 0, "dune": 0}
        self._throttle_lock = asyncio.Lock()
        self._last_request_ts: dict[str, float] = {}
        self._defillama_budget_exhausted = False
        self.protocol_aliases = self._parse_protocol_aliases(
            config.get("project_analysis", {}).get("defillama_protocol_aliases"),
        )

    @staticmethod
    def _parse_query_ids(value: Any) -> dict[str, int]:
        if isinstance(value, dict):
            raw = value
        else:
            text = str(value or "").strip()
            if not text:
                return {}
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                return {}
            if not isinstance(loaded, dict):
                return {}
            raw = loaded

        out: dict[str, int] = {}
        for key, val in raw.items():
            try:
                numeric = int(val)
            except (TypeError, ValueError):
                continue
            if numeric > 0:
                out[str(key).strip().lower()] = numeric
        return out

    @classmethod
    def _parse_protocol_aliases(cls, value: Any) -> dict[str, str]:
        raw: dict[str, Any] = {}
        if isinstance(value, dict):
            raw = value
        else:
            text = str(value or "").strip()
            if text:
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError:
                    decoded = {}
                if isinstance(decoded, dict):
                    raw = decoded

        aliases = dict(cls._DEFAULT_PROTOCOL_ALIASES)
        for key, slug in raw.items():
            alias = str(key or "").strip().lower()
            resolved = str(slug or "").strip().lower()
            if alias and resolved:
                aliases[alias] = resolved
        return aliases

    async def _cached_get_json(
        self,
        *,
        cache_key: str,
        url: str,
        params: dict[str, Any] | None = None,
        source: str = "unknown",
    ) -> Any:
        if self._is_error_cached(cache_key):
            logger.debug(f"project_analysis skip recently failed fetch for {source} ({cache_key})")
            return None

        if cache_key in self._memo:
            return self._memo[cache_key]

        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                self._memo[cache_key] = cached
                return cached

        attempts = 0
        while True:
            self._register_network_call(source)
            await self._throttle(source)
            try:
                async with httpx.AsyncClient(timeout=self.http_timeout) as client:
                    response = await client.get(url, params=params)
                if response.status_code == 404:
                    self._memo[cache_key] = None
                    return None
                response.raise_for_status()
                payload = response.json()
                break
            except httpx.HTTPStatusError as exc:
                retry_max, retry_backoff_sec = self._retry_policy(source)
                status = exc.response.status_code
                if retry_max <= 0 or attempts >= retry_max or status not in {429, 500, 502, 503, 504}:
                    if self._fail_open(source):
                        self._memoize_error(cache_key)
                        logger.debug(
                            f"project_analysis {source} fail-open for {url} ({status}); "
                            f"error_ttl={self.error_cache_ttl:.1f}s"
                        )
                        return None
                    raise
                attempts += 1
                wait_sec = self._retry_delay(
                    response=exc.response,
                    attempt=attempts,
                    backoff_sec=retry_backoff_sec,
                )
                logger.debug(
                    f"project_analysis {source} retry {attempts}/{retry_max} "
                    f"for {url} ({status}), wait={wait_sec:.2f}s"
                )
                await asyncio.sleep(wait_sec)
            except httpx.RequestError:
                retry_max, retry_backoff_sec = self._retry_policy(source)
                if retry_max <= 0 or attempts >= retry_max:
                    if self._fail_open(source):
                        self._memoize_error(cache_key)
                        logger.debug(
                            f"project_analysis {source} fail-open transport error for {url}; "
                            f"error_ttl={self.error_cache_ttl:.1f}s"
                        )
                        return None
                    raise
                attempts += 1
                wait_sec = self._retry_delay(
                    response=None,
                    attempt=attempts,
                    backoff_sec=retry_backoff_sec,
                )
                logger.debug(
                    f"project_analysis {source} transport retry {attempts}/{retry_max} "
                    f"for {url}, wait={wait_sec:.2f}s"
                )
                await asyncio.sleep(wait_sec)

        if self.cache and payload is not None:
            await self.cache.set(cache_key, payload, ttl=self.cache_ttl)
        self._memo[cache_key] = payload
        return payload

    def _register_network_call(self, source: str) -> None:
        src = str(source or "").strip().lower() or "unknown"
        if src == "defillama" and self.defillama_max_calls_per_run > 0:
            used = int(self._network_call_counters.get("defillama", 0))
            if used >= self.defillama_max_calls_per_run:
                self._defillama_budget_exhausted = True
                raise DefiLlamaBudgetExceeded(
                    f"defillama call budget exhausted ({used}/{self.defillama_max_calls_per_run})"
                )
        self._network_call_counters[src] = int(self._network_call_counters.get(src, 0)) + 1
        if src in self.call_counters:
            self.call_counters[src] = int(self.call_counters.get(src, 0)) + 1

    def _retry_policy(self, source: str) -> tuple[int, float]:
        src = str(source or "").strip().lower()
        if src == "defillama":
            return self.defillama_retry_max, self.defillama_retry_backoff_sec
        if src == "coingecko":
            return self.coingecko_retry_max, self.coingecko_retry_backoff_sec
        return 0, 0.0

    @staticmethod
    def _fail_open(source: str) -> bool:
        src = str(source or "").strip().lower()
        return src in {"defillama", "coingecko"}

    def _is_error_cached(self, cache_key: str) -> bool:
        until = self._error_memo.get(cache_key)
        if until is None:
            return False
        if time.monotonic() >= until:
            self._error_memo.pop(cache_key, None)
            return False
        return True

    def _memoize_error(self, cache_key: str) -> None:
        if self.error_cache_ttl <= 0:
            return
        self._error_memo[cache_key] = time.monotonic() + self.error_cache_ttl

    def _retry_delay(self, *, response: httpx.Response | None, attempt: int, backoff_sec: float) -> float:
        header = None
        if response is not None:
            header = (response.headers or {}).get("retry-after")
        if header:
            text = str(header).strip()
            if text.isdigit():
                return max(0.0, float(int(text)))
            try:
                return max(0.0, float(text))
            except ValueError:
                pass
        return backoff_sec * max(1, attempt)

    def _defillama_retry_delay(self, *, response: httpx.Response | None, attempt: int) -> float:
        return self._retry_delay(
            response=response,
            attempt=attempt,
            backoff_sec=self.defillama_retry_backoff_sec,
        )

    def _coingecko_retry_delay(self, *, response: httpx.Response | None, attempt: int) -> float:
        return self._retry_delay(
            response=response,
            attempt=attempt,
            backoff_sec=self.coingecko_retry_backoff_sec,
        )

    async def _throttle(self, source: str) -> None:
        if source != "defillama" or self.defillama_min_interval_sec <= 0:
            return
        async with self._throttle_lock:
            now = time.monotonic()
            last = self._last_request_ts.get(source)
            if last is not None:
                wait = self.defillama_min_interval_sec - (now - last)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_request_ts[source] = time.monotonic()

    async def search_coingecko(self, query: str) -> dict[str, Any] | None:
        safe_query = query.strip()
        if not safe_query:
            return None
        try:
            cache_key = f"pa:cg:search:{safe_query.lower()}"
            payload = await self._cached_get_json(
                cache_key=cache_key,
                url=f"{self.coingecko_base}/search",
                params={"query": safe_query},
                source="coingecko",
            )
        except Exception as exc:
            logger.warning(f"project_analysis coingecko search failed for '{safe_query}': {exc}")
            return None

        coins = list((payload or {}).get("coins") or [])
        if not coins:
            return None

        exact_symbol = [
            coin for coin in coins
            if str(coin.get("symbol") or "").lower() == safe_query.lower()
        ]
        if exact_symbol:
            exact_name = [
                coin for coin in exact_symbol
                if str(coin.get("name") or "").lower() == safe_query.lower()
            ]
            return (exact_name or exact_symbol)[0]
        return coins[0]

    async def fetch_coingecko_metrics(
        self,
        *,
        asset_input: str,
        coingecko_id: str | None,
        required_metrics: Iterable[str],
    ) -> dict[str, Any]:
        try:
            required = set(required_metrics)
            resolved_id = (coingecko_id or "").strip().lower()
            if not resolved_id:
                found = await self.search_coingecko(asset_input)
                resolved_id = str((found or {}).get("id") or "").strip().lower()
            if not resolved_id:
                return {}

            coin_key = f"pa:cg:coin:{resolved_id}"
            payload = await self._cached_get_json(
                cache_key=coin_key,
                url=f"{self.coingecko_base}/coins/{resolved_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "true",
                    "community_data": "false",
                    "developer_data": "false",
                    "sparkline": "false",
                },
                source="coingecko",
            )
            if not payload:
                return {}

            md = payload.get("market_data") or {}
            result: dict[str, Any] = {
                "coingecko_id": resolved_id,
                "name": payload.get("name"),
                "token_symbol": str(payload.get("symbol") or "").upper() or None,
                "categories": list(payload.get("categories") or []),
                "market_cap": _safe_float((md.get("market_cap") or {}).get("usd")),
                "fdv": _safe_float((md.get("fully_diluted_valuation") or {}).get("usd")),
                "current_price": _safe_float((md.get("current_price") or {}).get("usd")),
                "circulating_supply": _safe_float(md.get("circulating_supply")),
                "total_supply": _safe_float(md.get("total_supply")),
                "max_supply": _safe_float(md.get("max_supply")),
            }

            if "spot_volume_30d" in required:
                mc_key = f"pa:cg:chart30d:{resolved_id}"
                chart = await self._cached_get_json(
                    cache_key=mc_key,
                    url=f"{self.coingecko_base}/coins/{resolved_id}/market_chart",
                    params={"vs_currency": "usd", "days": "30", "interval": "daily"},
                    source="coingecko",
                )
                volumes = (chart or {}).get("total_volumes") or []
                spot_volume_30d = sum(
                    _safe_float(item[1]) or 0.0
                    for item in volumes
                    if isinstance(item, list) and len(item) >= 2
                )
                result["spot_volume_30d"] = spot_volume_30d if spot_volume_30d > 0 else None

            return {
                k: v
                for k, v in result.items()
                if v is not None or k in {"coingecko_id", "categories", "name", "token_symbol"}
            }
        except Exception as exc:
            logger.warning(f"project_analysis coingecko metrics fetch failed ({asset_input}): {exc}")
            return {}

    async def _fetch_protocol(self, slug: str) -> dict[str, Any] | None:
        if not slug:
            return None
        cache_key = f"pa:dl:protocol:{slug}"
        try:
            payload = await self._cached_get_json(
                cache_key=cache_key,
                url=f"{self.defillama_base}/protocol/{slug}",
                source="defillama",
            )
            if isinstance(payload, dict) and payload:
                payload = dict(payload)
                payload.setdefault("slug", slug)
            return payload
        except DefiLlamaBudgetExceeded:
            logger.warning("project_analysis defillama budget exhausted before protocol fetch")
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {400, 404}:
                return None
            raise
        except Exception as exc:
            logger.debug(f"project_analysis defillama protocol fetch failed ({slug}): {exc}")
            return None

    async def _fetch_protocols_list(self) -> list[dict[str, Any]]:
        try:
            cache_key = "pa:dl:protocols"
            payload = await self._cached_get_json(
                cache_key=cache_key,
                url=f"{self.defillama_base}/protocols",
                source="defillama",
            )
        except DefiLlamaBudgetExceeded:
            logger.warning("project_analysis defillama budget exhausted before protocols list fetch")
            return []
        except Exception as exc:
            logger.warning(f"project_analysis defillama protocols list fetch failed: {exc}")
            return []
        if not isinstance(payload, list):
            return []
        return payload

    async def resolve_defillama_protocol(
        self,
        *,
        asset_input: str,
        candidate_slug: str | None,
        coingecko_id: str | None,
        token_symbol: str | None,
    ) -> dict[str, Any] | None:
        candidates = []
        if candidate_slug:
            candidates.append(candidate_slug.strip().lower())
        if coingecko_id:
            candidates.append(coingecko_id.strip().lower())
        if asset_input:
            candidates.append(_slugify(asset_input))
        if token_symbol:
            candidates.append(_slugify(token_symbol))

        seen: set[str] = set()
        fallback_payload: dict[str, Any] | None = None
        for slug in candidates:
            if not slug or slug in seen:
                continue
            seen.add(slug)
            payload = await self._fetch_protocol(slug)
            if not payload:
                continue
            if payload.get("slug") and payload.get("category"):
                return payload
            if fallback_payload is None:
                fallback_payload = payload

        alias_candidates = self._alias_candidate_slugs(
            asset_input=asset_input,
            coingecko_id=coingecko_id,
            token_symbol=token_symbol,
        )
        for slug in alias_candidates:
            if not slug or slug in seen:
                continue
            seen.add(slug)
            payload = await self._fetch_protocol(slug)
            if not payload:
                continue
            if payload.get("slug") and payload.get("category"):
                return payload
            if fallback_payload is None:
                fallback_payload = payload

        protocols = await self._fetch_protocols_list()
        query_name = asset_input.strip().lower()
        query_symbol = (token_symbol or "").strip().lower()
        query_cg = (coingecko_id or "").strip().lower()

        if query_cg:
            for row in protocols:
                if str(row.get("gecko_id") or "").strip().lower() == query_cg:
                    slug = str(row.get("slug") or "").strip().lower()
                    if slug:
                        payload = await self._fetch_protocol(slug)
                        if payload and payload.get("slug") and payload.get("category"):
                            return payload
                        if payload and fallback_payload is None:
                            fallback_payload = payload

        by_symbol = [
            row
            for row in protocols
            if query_symbol and str(row.get("symbol") or "").strip().lower() == query_symbol
        ]
        if by_symbol:
            by_symbol.sort(key=lambda x: _safe_float(x.get("tvl")) or 0.0, reverse=True)
            slug = str((by_symbol[0] or {}).get("slug") or "").strip().lower()
            if slug:
                payload = await self._fetch_protocol(slug)
                if payload and payload.get("slug") and payload.get("category"):
                    return payload
                if payload and fallback_payload is None:
                    fallback_payload = payload

        by_name = [
            row
            for row in protocols
            if query_name and query_name in str(row.get("name") or "").strip().lower()
        ]
        if by_name:
            by_name.sort(key=lambda x: _safe_float(x.get("tvl")) or 0.0, reverse=True)
            slug = str((by_name[0] or {}).get("slug") or "").strip().lower()
            if slug:
                payload = await self._fetch_protocol(slug)
                if payload and payload.get("slug") and payload.get("category"):
                    return payload
                if payload and fallback_payload is None:
                    fallback_payload = payload

        return fallback_payload

    def _alias_candidate_slugs(
        self,
        *,
        asset_input: str,
        coingecko_id: str | None,
        token_symbol: str | None,
    ) -> list[str]:
        keys = [
            str(asset_input or "").strip().lower(),
            _slugify(str(asset_input or "")),
            str(coingecko_id or "").strip().lower(),
            _slugify(str(token_symbol or "")),
            str(token_symbol or "").strip().lower(),
        ]
        out: list[str] = []
        seen: set[str] = set()
        for key in keys:
            if not key:
                continue
            mapped = str(self.protocol_aliases.get(key) or "").strip().lower()
            if not mapped or mapped in seen:
                continue
            seen.add(mapped)
            out.append(mapped)
        return out

    async def _fetch_summary(self, group: str, slug: str) -> dict[str, Any] | None:
        cache_key = f"pa:dl:summary:{group}:{slug}"
        try:
            payload = await self._cached_get_json(
                cache_key=cache_key,
                url=f"{self.defillama_base}/summary/{group}/{slug}",
                source="defillama",
            )
            return payload
        except DefiLlamaBudgetExceeded:
            logger.warning(f"project_analysis defillama budget exhausted before summary fetch ({group}/{slug})")
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {402, 404}:
                return None
            logger.debug(f"project_analysis defillama summary fetch failed ({group}/{slug}): {exc}")
            return None
        except Exception as exc:
            logger.debug(f"project_analysis defillama summary fetch failed ({group}/{slug}): {exc}")
            return None

    def _summary_candidate_slugs(
        self,
        *,
        primary_slug: str,
        protocol: dict[str, Any],
        asset_input: str,
        coingecko_id: str | None,
        token_symbol: str | None,
    ) -> list[str]:
        parent_raw = str(protocol.get("parentProtocol") or "").strip()
        parent_slug = ""
        if parent_raw:
            left, sep, right = parent_raw.partition("#")
            left = left.strip().lower()
            right = right.strip().lower()
            if left == "parent" and right:
                parent_slug = right
            elif left:
                parent_slug = left
        if parent_slug and " " in parent_slug:
            parent_slug = _slugify(parent_slug)
        candidates = [
            str(primary_slug or "").strip().lower(),
            parent_slug,
            str(coingecko_id or "").strip().lower(),
            str(token_symbol or "").strip().lower(),
            _slugify(str(asset_input or "")),
        ]
        seen: set[str] = set()
        out: list[str] = []
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            out.append(candidate)
            if len(out) >= self.defillama_summary_max_candidates:
                break
        return out

    async def _fetch_summary_with_candidates(
        self,
        *,
        group: str,
        primary_slug: str,
        protocol: dict[str, Any],
        asset_input: str,
        coingecko_id: str | None,
        token_symbol: str | None,
    ) -> tuple[dict[str, Any] | None, str | None, list[str]]:
        candidates = self._summary_candidate_slugs(
            primary_slug=primary_slug,
            protocol=protocol,
            asset_input=asset_input,
            coingecko_id=coingecko_id,
            token_symbol=token_symbol,
        )
        attempts: list[str] = []
        for candidate in candidates:
            attempts.append(candidate)
            payload = await self._fetch_summary(group, candidate)
            if payload:
                return payload, candidate, attempts
        return None, None, attempts

    async def fetch_defillama_metrics(
        self,
        *,
        asset_input: str,
        sector: SectorType,
        candidate_slug: str | None,
        coingecko_id: str | None,
        token_symbol: str | None,
        required_metrics: Iterable[str],
    ) -> dict[str, Any]:
        try:
            required = set(required_metrics)
            audit: list[dict[str, Any]] = []
            protocol = await self.resolve_defillama_protocol(
                asset_input=asset_input,
                candidate_slug=candidate_slug,
                coingecko_id=coingecko_id,
                token_symbol=token_symbol,
            )
            if not protocol:
                return {}

            slug = str(protocol.get("slug") or candidate_slug or "").strip().lower()
            if not slug:
                return {}

            tvl_raw = protocol.get("tvl")
            if isinstance(tvl_raw, list) and tvl_raw:
                tvl = _safe_float((tvl_raw[-1] or {}).get("totalLiquidityUSD"))
            else:
                tvl = _safe_float(tvl_raw)

            result: dict[str, Any] = {
                "defillama_slug": slug,
                "protocol_name": protocol.get("name"),
                "defillama_category": protocol.get("category"),
                "tvl": tvl,
                "hacks": _normalize_hacks(protocol.get("audits")),
                "treasury": protocol.get("treasury") if isinstance(protocol.get("treasury"), dict) else None,
            }

            current_chain_tvls = protocol.get("currentChainTvls") or {}
            borrowed = _safe_float(current_chain_tvls.get("borrowed"))
            supplied = _safe_float(current_chain_tvls.get("staking")) or tvl

            if sector == "lending":
                result["supplied_tvl"] = supplied
                result["borrowed_tvl"] = borrowed
                result["main_demand_kpi"] = borrowed
                result["bad_debt"] = _safe_float(protocol.get("badDebt"))
                result["collateral_mix"] = (
                    protocol.get("collateral")
                    if isinstance(protocol.get("collateral"), list)
                    else None
                )
                result["borrow_mix"] = (
                    protocol.get("borrowTokens")
                    if isinstance(protocol.get("borrowTokens"), list)
                    else None
                )
                if result.get("concentration_metric") is None:
                    chain_values = [
                        _safe_float(v)
                        for k, v in current_chain_tvls.items()
                        if str(k).lower() not in {"borrowed", "staking", "pool2", "borrowed tvl"}
                    ]
                    chain_values = [v for v in chain_values if v is not None and v > 0]
                    total_chain = sum(chain_values)
                    if total_chain > 0 and chain_values:
                        result["concentration_metric"] = max(chain_values) / total_chain

            daily_revenue = _safe_float(protocol.get("dailyRevenue") or protocol.get("revenue_24h"))
            daily_holder_revenue = _safe_float(
                protocol.get("dailyUserFees") or protocol.get("holder_revenue_24h")
            )
            if daily_revenue is not None:
                result["annualized_protocol_revenue"] = daily_revenue * 365
            if daily_holder_revenue is not None:
                result["annualized_tokenholder_revenue"] = daily_holder_revenue * 365

            if "volume" in required or sector in {"spot_dex", "perp_dex"}:
                vol24 = _safe_float(protocol.get("volume24h") or protocol.get("dailyVolume"))
                if vol24 is not None:
                    result["volume"] = vol24 * 30
                    if sector in {"spot_dex", "perp_dex"}:
                        result["main_demand_kpi"] = result["volume"]

            if "open_interest" in required or sector == "perp_dex":
                oi = _safe_float(protocol.get("openInterest"))
                if oi is not None:
                    result["open_interest"] = oi

            summary_revenue, revenue_slug, revenue_attempts = await self._fetch_summary_with_candidates(
                group="revenue",
                primary_slug=slug,
                protocol=protocol,
                asset_input=asset_input,
                coingecko_id=coingecko_id,
                token_symbol=token_symbol,
            )
            if summary_revenue and summary_revenue.get("total30d") is not None:
                val30 = _safe_float(summary_revenue.get("total30d"))
                if val30 is not None:
                    result["annualized_protocol_revenue"] = val30 * 12
                    audit.append(
                        {
                            "event": "metric_source",
                            "metric": "annualized_protocol_revenue",
                            "method": "defillama.summary.revenue.total30d",
                            "slug": revenue_slug or slug,
                            "attempted_slugs": revenue_attempts,
                        }
                    )
                change_90d = _safe_float(summary_revenue.get("change_3m"))
                if change_90d is not None:
                    result["main_demand_kpi_growth_90d"] = change_90d
                    audit.append(
                        {
                            "event": "metric_source",
                            "metric": "main_demand_kpi_growth_90d",
                            "method": "defillama.summary.revenue.change_3m",
                            "slug": revenue_slug or slug,
                            "attempted_slugs": revenue_attempts,
                        }
                    )

            summary_fees = await self._fetch_summary("fees", slug)
            protocol_revenue_30d = _safe_float((summary_fees or {}).get("protocolRevenue30d"))
            fees_total_30d = _safe_float((summary_fees or {}).get("total30d"))
            if result.get("annualized_protocol_revenue") is None:
                if protocol_revenue_30d is not None:
                    result["annualized_protocol_revenue"] = protocol_revenue_30d * 12
                    audit.append(
                        {
                            "event": "metric_fallback_applied",
                            "metric": "annualized_protocol_revenue",
                            "method": "defillama.summary.fees.protocolRevenue30d",
                            "reason": "revenue summary unavailable",
                            "slug": slug,
                        }
                    )
                elif fees_total_30d is not None:
                    result["annualized_protocol_revenue"] = fees_total_30d * 12
                    audit.append(
                        {
                            "event": "metric_fallback_applied",
                            "metric": "annualized_protocol_revenue",
                            "method": "defillama.summary.fees.total30d_proxy",
                            "reason": "revenue summary unavailable",
                            "slug": slug,
                        }
                    )
            if summary_fees and result.get("annualized_tokenholder_revenue") is None:
                val30 = fees_total_30d
                if val30 is not None:
                    result["annualized_tokenholder_revenue"] = val30 * 12
                    audit.append(
                        {
                            "event": "metric_source",
                            "metric": "annualized_tokenholder_revenue",
                            "method": "defillama.summary.fees.total30d",
                            "slug": slug,
                        }
                    )

            if sector == "spot_dex":
                summary_dex, dex_slug, dex_attempts = await self._fetch_summary_with_candidates(
                    group="dexs",
                    primary_slug=slug,
                    protocol=protocol,
                    asset_input=asset_input,
                    coingecko_id=coingecko_id,
                    token_symbol=token_symbol,
                )
                if summary_dex:
                    val30 = _safe_float(summary_dex.get("total30d"))
                    if val30 is not None:
                        result["volume"] = val30
                        result["main_demand_kpi"] = val30
                        audit.append(
                            {
                                "event": "metric_source",
                                "metric": "volume",
                                "method": "defillama.summary.dexs.total30d",
                                "slug": dex_slug or slug,
                                "attempted_slugs": dex_attempts,
                            }
                        )
                    change_90d = _safe_float(summary_dex.get("change_3m"))
                    if change_90d is not None:
                        result["main_demand_kpi_growth_90d"] = change_90d

            if sector == "perp_dex":
                summary_perp, perp_slug, perp_attempts = await self._fetch_summary_with_candidates(
                    group="derivatives",
                    primary_slug=slug,
                    protocol=protocol,
                    asset_input=asset_input,
                    coingecko_id=coingecko_id,
                    token_symbol=token_symbol,
                )
                if summary_perp:
                    vol30 = _safe_float(summary_perp.get("total30d"))
                    if vol30 is not None:
                        result["volume"] = vol30
                        result["main_demand_kpi"] = vol30
                        audit.append(
                            {
                                "event": "metric_source",
                                "metric": "volume",
                                "method": "defillama.summary.derivatives.total30d",
                                "slug": perp_slug or slug,
                                "attempted_slugs": perp_attempts,
                            }
                        )
                    oi = _safe_float(summary_perp.get("openInterest"))
                    if oi is not None:
                        result["open_interest"] = oi
                        audit.append(
                            {
                                "event": "metric_source",
                                "metric": "open_interest",
                                "method": "defillama.summary.derivatives.openInterest",
                                "slug": perp_slug or slug,
                                "attempted_slugs": perp_attempts,
                            }
                        )
                    markets = summary_perp.get("markets")
                    if isinstance(markets, list):
                        result["markets_count"] = len(markets)
                        audit.append(
                            {
                                "event": "metric_source",
                                "metric": "markets_count",
                                "method": "defillama.summary.derivatives.markets",
                                "slug": perp_slug or slug,
                                "attempted_slugs": perp_attempts,
                            }
                        )
                    change_90d = _safe_float(summary_perp.get("change_3m"))
                    if change_90d is not None:
                        result["main_demand_kpi_growth_90d"] = change_90d
                else:
                    audit.append(
                        {
                            "event": "metric_unavailable",
                            "metric": "volume",
                            "owner": "defillama",
                            "reason": "defillama.summary.derivatives unavailable",
                            "attempted_slugs": perp_attempts,
                        }
                    )
                    audit.append(
                        {
                            "event": "metric_unavailable",
                            "metric": "open_interest",
                            "owner": "defillama",
                            "reason": "defillama.summary.derivatives unavailable",
                            "attempted_slugs": perp_attempts,
                        }
                    )
                    audit.append(
                        {
                            "event": "metric_unavailable",
                            "metric": "markets_count",
                            "owner": "defillama",
                            "reason": "defillama.summary.derivatives unavailable",
                            "attempted_slugs": perp_attempts,
                        }
                    )

            summary_unlocks, unlocks_slug, unlocks_attempts = await self._fetch_summary_with_candidates(
                group="unlocks",
                primary_slug=slug,
                protocol=protocol,
                asset_input=asset_input,
                coingecko_id=coingecko_id,
                token_symbol=token_symbol,
            )
            if summary_unlocks:
                unlock_12m = _safe_float(
                    summary_unlocks.get("total12m") or summary_unlocks.get("total12mUsd")
                )
                if unlock_12m is not None:
                    result["token_unlocks_12m"] = unlock_12m
                    audit.append(
                        {
                            "event": "metric_source",
                            "metric": "token_unlocks_12m",
                            "method": "defillama.summary.unlocks.total12m",
                            "slug": unlocks_slug or slug,
                            "attempted_slugs": unlocks_attempts,
                        }
                    )
                recipients = summary_unlocks.get("recipients")
                if isinstance(recipients, list):
                    result["unlock_recipients"] = recipients
                    audit.append(
                        {
                            "event": "metric_source",
                            "metric": "unlock_recipients",
                            "method": "defillama.summary.unlocks.recipients",
                            "slug": unlocks_slug or slug,
                            "attempted_slugs": unlocks_attempts,
                        }
                    )
            else:
                audit.append(
                    {
                        "event": "metric_unavailable",
                        "metric": "token_unlocks_12m",
                        "owner": "defillama",
                        "reason": "defillama.summary.unlocks unavailable",
                        "attempted_slugs": unlocks_attempts,
                    }
                )

            if result.get("main_demand_kpi_growth_90d") is None:
                change = _safe_float(protocol.get("change_3m") or protocol.get("change_1m"))
                if change is not None:
                    result["main_demand_kpi_growth_90d"] = change
            if result.get("main_demand_kpi_growth_90d") is None:
                growth_90d = _series_growth_90d(tvl_raw)
                if growth_90d is not None:
                    result["main_demand_kpi_growth_90d"] = growth_90d

            if sector in {"spot_dex", "perp_dex"}:
                result.setdefault("market_depth_or_liquidity", tvl)
                result.setdefault("retention", None)

            if sector == "perp_dex" and result.get("markets_count") is None:
                markets = protocol.get("markets")
                if isinstance(markets, list):
                    result["markets_count"] = len(markets)

            if result.get("value_capture_type") is None and protocol.get("tokenTax"):
                result["value_capture_type"] = "buyback"

            unavailable_seen = {
                str(item.get("metric") or "")
                for item in audit
                if isinstance(item, dict) and str(item.get("event") or "") == "metric_unavailable"
            }
            unavailable_reason_map = {
                "annualized_protocol_revenue": "defillama.revenue unavailable from protocol+summary payloads",
                "annualized_tokenholder_revenue": "defillama.tokenholder_revenue unavailable from protocol+summary payloads",
                "token_unlocks_12m": "defillama.summary.unlocks.total12m unavailable",
                "unlock_recipients": "defillama.summary.unlocks.recipients unavailable",
                "value_capture_type": "defillama token value-capture signal unavailable",
                "main_demand_kpi": f"defillama main demand KPI unavailable for sector={sector}",
                "main_demand_kpi_growth_90d": "defillama main demand KPI 90d growth unavailable",
                "supplied_tvl": "defillama supplied_tvl unavailable",
                "borrowed_tvl": "defillama borrowed_tvl unavailable",
                "bad_debt": "defillama protocol.badDebt unavailable",
                "collateral_mix": "defillama protocol.collateral unavailable",
                "borrow_mix": "defillama protocol.borrowTokens unavailable",
                "concentration_metric": "defillama concentration metric unavailable",
                "volume": "defillama volume unavailable for this protocol/sector",
                "open_interest": "defillama open_interest unavailable for this protocol/sector",
                "retention": "defillama retention unavailable on current free endpoints",
                "market_depth_or_liquidity": "defillama market depth/liquidity unavailable",
                "markets_count": "defillama markets_count unavailable",
            }
            metric_attempts_map = {
                "token_unlocks_12m": unlocks_attempts,
                "unlock_recipients": unlocks_attempts,
                "annualized_protocol_revenue": revenue_attempts,
                "main_demand_kpi_growth_90d": revenue_attempts,
            }
            for metric in sorted(required):
                if result.get(metric) is not None or metric in unavailable_seen:
                    continue
                event: dict[str, Any] = {
                    "event": "metric_unavailable",
                    "metric": metric,
                    "owner": "defillama",
                    "reason": unavailable_reason_map.get(metric, "defillama metric unavailable or null"),
                }
                attempts = metric_attempts_map.get(metric)
                if isinstance(attempts, list) and attempts:
                    event["attempted_slugs"] = attempts
                audit.append(event)

            if self._defillama_budget_exhausted:
                missing_required = sorted(
                    metric for metric in required
                    if result.get(metric) is None
                )
                if missing_required:
                    audit.append(
                        {
                            "event": "defillama_budget_exhausted",
                            "limit": self.defillama_max_calls_per_run,
                            "missing_metrics": missing_required,
                        }
                    )

            filtered = {k: v for k, v in result.items() if v is not None}
            if audit:
                filtered["_audit"] = audit
            return filtered
        except Exception as exc:
            logger.warning(f"project_analysis defillama metrics fetch failed ({asset_input}): {exc}")
            return {}

    async def discover_peer_group(
        self,
        *,
        sector: SectorType,
        target_slug: str | None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        protocols = await self._fetch_protocols_list()
        if not protocols:
            return []

        def _sector_match(category: str | None) -> bool:
            text = str(category or "").lower()
            if sector == "lending":
                return "lend" in text
            if sector == "spot_dex":
                return "dex" in text and "deriv" not in text and "perp" not in text
            if sector == "perp_dex":
                return "deriv" in text or "perp" in text
            return False

        peers = []
        for row in protocols:
            slug = str(row.get("slug") or "").strip().lower()
            if not slug or slug == (target_slug or "").lower():
                continue
            if not _sector_match(row.get("category")):
                continue
            peers.append(
                {
                    "name": row.get("name"),
                    "slug": slug,
                    "category": row.get("category"),
                    "tvl": _safe_float(row.get("tvl")),
                }
            )

        peers.sort(key=lambda x: x.get("tvl") or 0.0, reverse=True)
        return peers[: max(1, limit)]

    def estimated_cost(self) -> dict[str, int]:
        return {
            "coingecko_estimated_calls": int(self._network_call_counters.get("coingecko", 0)),
            "defillama_estimated_calls": int(self._network_call_counters.get("defillama", 0)),
            "dune_estimated_calls": int(self._network_call_counters.get("dune", 0)),
        }

    async def fetch_dune_metrics(
        self,
        *,
        asset_input: str,
        sector: SectorType,
        coingecko_id: str | None,
        token_symbol: str | None,
        required_metrics: Iterable[str],
    ) -> dict[str, Any]:
        if not self.dune_api_key:
            return {}

        query_id = self._resolve_dune_query_id(sector)
        if query_id is None:
            return {}

        try:
            rows = await self._execute_dune_query(query_id=query_id)
        except Exception as exc:
            logger.warning(f"project_analysis dune metrics fetch failed ({asset_input}): {exc}")
            return {}

        row = self._match_dune_row(
            rows=rows,
            asset_input=asset_input,
            coingecko_id=coingecko_id,
            token_symbol=token_symbol,
        )
        if not row:
            return {}

        required = set(required_metrics)
        out: dict[str, Any] = {}
        for metric in required:
            value = row.get(metric)
            if value is None:
                for alt in self._dune_metric_aliases(metric):
                    if row.get(alt) is not None:
                        value = row.get(alt)
                        break
            if value is None:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[metric] = float(value)
            else:
                out[metric] = value
        return out

    def _resolve_dune_query_id(self, sector: SectorType) -> int | None:
        key_map = {
            "lending": ("lending", "defi_lending", "default"),
            "spot_dex": ("spot_dex", "dex_spot", "dex", "default"),
            "perp_dex": ("perp_dex", "perps", "derivatives", "default"),
            "unknown": ("default",),
        }
        for key in key_map.get(sector, ("default",)):
            if key in self.dune_query_ids:
                return self.dune_query_ids[key]
        return None

    @staticmethod
    def _dune_metric_aliases(metric: str) -> tuple[str, ...]:
        aliases = {
            "annualized_protocol_revenue": ("annualized_revenue",),
            "annualized_tokenholder_revenue": ("annualized_holder_revenue", "annualized_holders_revenue"),
            "token_unlocks_12m": ("unlocks_12m", "unlocks_12m_usd"),
            "supplied_tvl": ("supplied_usd",),
            "borrowed_tvl": ("borrowed_usd",),
            "main_demand_kpi_growth_90d": ("growth_90d",),
            "market_depth_or_liquidity": ("market_depth_usd", "liquidity_usd"),
        }
        return aliases.get(metric, tuple())

    async def _execute_dune_query(self, *, query_id: int) -> list[dict[str, Any]]:
        headers = {"X-Dune-API-Key": self.dune_api_key}
        timeout = max(self.http_timeout, self.dune_query_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            self._register_network_call("dune")
            execute = await client.post(
                f"{self.dune_base}/query/{query_id}/execute",
                headers=headers,
                json={},
            )
            execute.raise_for_status()
            payload = execute.json()
            execution_id = (
                payload.get("execution_id")
                or (payload.get("execution") or {}).get("execution_id")
                or (payload.get("state") or {}).get("execution_id")
            )
            if not execution_id:
                return []

            deadline = time.monotonic() + self.dune_query_timeout
            while time.monotonic() < deadline:
                self._register_network_call("dune")
                status_resp = await client.get(
                    f"{self.dune_base}/execution/{execution_id}/status",
                    headers=headers,
                )
                status_resp.raise_for_status()
                status_payload = status_resp.json()
                state = str(
                    status_payload.get("state")
                    or status_payload.get("status")
                    or (status_payload.get("execution") or {}).get("state")
                    or ""
                ).upper()
                if state in {"QUERY_STATE_COMPLETED", "COMPLETED"}:
                    break
                if state in {"QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "FAILED", "CANCELLED"}:
                    return []
                await asyncio.sleep(self.dune_poll_interval)
            else:
                return []

            self._register_network_call("dune")
            results_resp = await client.get(
                f"{self.dune_base}/execution/{execution_id}/results",
                headers=headers,
            )
            results_resp.raise_for_status()
            results_payload = results_resp.json()
            rows = ((results_payload.get("result") or {}).get("rows")) or results_payload.get("rows") or []
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
            return []

    @staticmethod
    def _match_dune_row(
        *,
        rows: list[dict[str, Any]],
        asset_input: str,
        coingecko_id: str | None,
        token_symbol: str | None,
    ) -> dict[str, Any] | None:
        if not rows:
            return None

        q_name = asset_input.strip().lower()
        q_cg = str(coingecko_id or "").strip().lower()
        q_ticker = str(token_symbol or "").strip().lower()

        def _score(row: dict[str, Any]) -> int:
            score = 0
            name = str(row.get("name") or row.get("protocol") or row.get("project") or "").strip().lower()
            symbol = str(row.get("symbol") or row.get("ticker") or "").strip().lower()
            gecko = str(row.get("coingecko_id") or row.get("gecko_id") or "").strip().lower()
            slug = str(row.get("slug") or "").strip().lower()

            if q_cg and gecko == q_cg:
                score += 5
            if q_ticker and symbol == q_ticker:
                score += 4
            if q_name and (name == q_name or slug == q_name):
                score += 4
            if q_name and q_name in name:
                score += 2
            return score

        ranked = sorted(rows, key=_score, reverse=True)
        return ranked[0] if _score(ranked[0]) > 0 else None
