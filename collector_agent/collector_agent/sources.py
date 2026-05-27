"""API-first source adapters for the external collector agent."""

from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Any

import httpx

from collector_agent.config import Settings
from collector_agent.contracts import CollectorRequest, Provenance, Quality, SourceResult
from collector_agent.normalizer import failed_source_result, utc_now

_COINGECKO_FIELDS = {
    "localization": "false",
    "tickers": "false",
    "market_data": "true",
    "community_data": "true",
    "developer_data": "false",
    "sparkline": "false",
}
_DEFILLAMA_SLUG_ALIASES = {
    "curve-dao-token": "curve-dex",
    "curve-finance": "curve-dex",
    "gmx": "gmx-v2",
    "lido-dao": "lido",
    "maker": "makerdao",
    "the-graph": "the-graph-protocol",
}


class BaseSourceAdapter:
    source_name: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def collect(
        self,
        request: CollectorRequest,
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> SourceResult:
        raise NotImplementedError

    def _request_timeout(self, deadline_at: float) -> float:
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("deadline exceeded")
        return max(0.1, min(self.settings.http_timeout_seconds, remaining))


class CoinGeckoSource(BaseSourceAdapter):
    source_name = "coingecko"

    async def collect(
        self,
        request: CollectorRequest,
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> SourceResult:
        coin_id = await self._resolve_coin_id(request, client=client, deadline_at=deadline_at)
        if not coin_id:
            return failed_source_result(
                source=self.source_name,
                elapsed_ms=0,
                code="target_not_found",
                message="CoinGecko id could not be resolved for target",
                retryable=False,
                warnings=["browser fallback is not implemented in v1"],
                provider="coingecko",
                endpoint=f"{self.settings.coingecko_base_url}/search",
            )

        response = await client.get(
            f"{self.settings.coingecko_base_url}/coins/{coin_id}",
            params=_COINGECKO_FIELDS,
            timeout=self._request_timeout(deadline_at),
        )
        response.raise_for_status()
        payload = response.json()

        market_data = payload.get("market_data") or {}
        metrics = {
            "price_usd": _safe_float((market_data.get("current_price") or {}).get("usd")),
            "market_cap": _safe_float((market_data.get("market_cap") or {}).get("usd")),
            "volume_24h": _safe_float((market_data.get("total_volume") or {}).get("usd")),
            "price_change_24h": _safe_float(market_data.get("price_change_percentage_24h")),
            "price_change_7d": _safe_float(market_data.get("price_change_percentage_7d")),
            "fdv": _safe_float((market_data.get("fully_diluted_valuation") or {}).get("usd")),
            "circulating_supply": _safe_float(market_data.get("circulating_supply")),
            "total_supply": _safe_float(market_data.get("total_supply")),
            "max_supply": _safe_float(market_data.get("max_supply")),
            "twitter_followers": _safe_float((payload.get("community_data") or {}).get("twitter_followers")),
            "reddit_subscribers": _safe_float((payload.get("community_data") or {}).get("reddit_subscribers")),
        }
        metrics = {key: value for key, value in metrics.items() if value is not None}

        item = None
        if request.criteria.need_protocol or request.criteria.need_metrics:
            item = {
                "source": self.source_name,
                "source_id": coin_id,
                "content_type": "metric",
                "title": f"{payload.get('name') or request.target.name} — CoinGecko",
                "content": _truncate((payload.get("description") or {}).get("en")),
                "url": f"https://www.coingecko.com/en/coins/{coin_id}",
                "metadata": {
                    "symbol": payload.get("symbol"),
                    "categories": payload.get("categories") or [],
                    "asset_platform": payload.get("asset_platform_id"),
                    "platforms": payload.get("platforms") or {},
                    "official_links": _coingecko_official_links(payload.get("links") or {}),
                },
            }

        quality_warnings: list[str] = []
        if not metrics:
            quality_warnings.append("market_data was empty")

        return SourceResult(
            source=self.source_name,
            method="api",
            elapsed_ms=0,
            success=bool(metrics or item),
            timed_out=False,
            metrics=metrics or None,
            items=[item] if item else None,
            metadata={
                "resolved_coin_id": coin_id,
                "categories": payload.get("categories") or [],
                "symbol": payload.get("symbol"),
                "asset_platform": payload.get("asset_platform_id"),
                "official_links": _coingecko_official_links(payload.get("links") or {}),
                "available_metrics": sorted(metrics.keys()),
            },
            provenance=Provenance(
                method="api",
                provider="coingecko",
                endpoint=f"{self.settings.coingecko_base_url}/coins/{coin_id}",
                fetched_at=utc_now(),
            ),
            quality=Quality(
                status="complete" if metrics else "warnings",
                confidence=0.95 if metrics else 0.6,
                stale=False,
                warnings=quality_warnings,
            ),
        )

    async def _resolve_coin_id(
        self,
        request: CollectorRequest,
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> str | None:
        direct = (request.target.coingecko_id or "").strip().lower()
        if direct:
            return direct

        for query in filter(None, [request.target.name, request.target.ticker]):
            response = await client.get(
                f"{self.settings.coingecko_base_url}/search",
                params={"query": query},
                timeout=self._request_timeout(deadline_at),
            )
            response.raise_for_status()
            payload = response.json()
            coins = payload.get("coins") or []
            if not coins:
                continue
            ticker = (request.target.ticker or "").strip().lower()
            exact = next(
                (
                    coin
                    for coin in coins
                    if ticker and str(coin.get("symbol") or "").strip().lower() == ticker
                ),
                None,
            )
            candidate = exact or coins[0]
            coin_id = str(candidate.get("id") or "").strip().lower()
            if coin_id:
                return coin_id
        return None


class DefiLlamaSource(BaseSourceAdapter):
    source_name = "defillama"

    async def collect(
        self,
        request: CollectorRequest,
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> SourceResult:
        slug = _candidate_slug(request.target.coingecko_id, request.target.name, request.target.ticker)
        protocol = await self._fetch_protocol_by_candidates(
            slug=slug,
            request=request,
            client=client,
            deadline_at=deadline_at,
        )
        if protocol is None:
            return failed_source_result(
                source=self.source_name,
                elapsed_ms=0,
                code="target_not_found",
                message="DefiLlama protocol could not be resolved for target",
                retryable=False,
                warnings=["browser fallback is not implemented in v1"],
                provider="defillama",
                endpoint=f"{self.settings.defillama_base_url}/protocols",
            )

        metrics = self._build_metrics(protocol)
        items: list[dict[str, Any]] = []
        warnings: list[str] = []

        summary_metrics, summary_warnings = await self._collect_summary_metrics(
            protocol=protocol,
            request=request,
            client=client,
            deadline_at=deadline_at,
        )
        warnings.extend(summary_warnings)
        summary_sources = summary_metrics.pop("_summary_sources", [])
        metrics.update({key: value for key, value in summary_metrics.items() if value is not None})

        if request.criteria.need_protocol:
            items.append(self._build_protocol_item(protocol, request))

        if request.criteria.need_yields:
            yield_result = await self._build_yield_items(protocol, client=client, deadline_at=deadline_at)
            items.extend(yield_result["items"])
            warnings.extend(yield_result["warnings"])

        if request.criteria.need_competitors:
            competitor_item = await self._build_competitor_item(
                protocol,
                client=client,
                deadline_at=deadline_at,
            )
            if competitor_item is not None:
                items.append(competitor_item)
            else:
                warnings.append("competitor comparison unavailable")

        quality_status = "complete" if not warnings else "warnings"
        confidence = 0.9 if metrics else 0.65
        return SourceResult(
            source=self.source_name,
            method="api",
            elapsed_ms=0,
            success=bool(metrics or items),
            metrics=metrics or None,
            items=items or None,
            metadata={
                "resolved_slug": protocol.get("slug"),
                "category": protocol.get("category"),
                "chains": protocol.get("chains") or [],
                "website": protocol.get("url"),
                "summary_sources": sorted(summary_sources),
                "available_metrics": sorted(metrics.keys()),
            },
            provenance=Provenance(
                method="api",
                provider="defillama",
                endpoint=f"{self.settings.defillama_base_url}/protocol/{protocol.get('slug')}",
                fetched_at=utc_now(),
            ),
            quality=Quality(
                status=quality_status,
                confidence=confidence,
                stale=False,
                warnings=warnings,
            ),
        )

    async def _collect_summary_metrics(
        self,
        *,
        protocol: dict[str, Any],
        request: CollectorRequest,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> tuple[dict[str, Any], list[str]]:
        candidates = self._summary_slug_candidates(protocol, request)
        warnings: list[str] = []
        metrics: dict[str, Any] = {}
        summary_sources: set[str] = set()

        fees_payload, fees_source, fees_warning = await self._fetch_first_summary_payload(
            group="fees",
            data_type="dailyFees",
            candidates=candidates,
            client=client,
            deadline_at=deadline_at,
        )
        if fees_warning:
            warnings.append(fees_warning)
        if fees_payload:
            summary_sources.add(fees_source)
            metrics.update(_summary_metrics(fees_payload, "fees"))

        revenue_payload, revenue_source, revenue_warning = await self._fetch_first_summary_payload(
            group="fees",
            data_type="dailyRevenue",
            candidates=candidates,
            client=client,
            deadline_at=deadline_at,
        )
        if revenue_warning:
            warnings.append(revenue_warning)
        if revenue_payload:
            summary_sources.add(revenue_source)
            metrics.update(_summary_metrics(revenue_payload, "revenue"))

        holders_payload, holders_source, holders_warning = await self._fetch_first_summary_payload(
            group="fees",
            data_type="dailyHoldersRevenue",
            candidates=candidates,
            client=client,
            deadline_at=deadline_at,
        )
        if holders_warning:
            warnings.append(holders_warning)
        if holders_payload:
            summary_sources.add(holders_source)
            metrics.update(_summary_metrics(holders_payload, "holder_revenue"))

        dexs_payload, dexs_source, dexs_warning = await self._fetch_first_summary_payload(
            group="dexs",
            data_type="dailyVolume",
            candidates=candidates,
            client=client,
            deadline_at=deadline_at,
        )
        if dexs_warning:
            warnings.append(dexs_warning)
        if dexs_payload:
            summary_sources.add(dexs_source)
            metrics.update(_summary_metrics(dexs_payload, "dex_volume"))
            metrics.setdefault("trading_volume_24h", _safe_float(dexs_payload.get("total24h")))
            metrics.setdefault("volume_24h", _safe_float(dexs_payload.get("total24h")))
            metrics["dex_volume_24h"] = _safe_float(dexs_payload.get("total24h"))
            metrics["dex_volume_7d"] = _safe_float(dexs_payload.get("total7d"))
            metrics["dex_volume_30d"] = _safe_float(dexs_payload.get("total30d"))

        category_text = str(protocol.get("category") or "").strip().lower()
        if any(keyword in category_text for keyword in ("derivative", "perp")):
            # Keep this hook explicit: derivatives summary endpoints are often paywalled (HTTP 402).
            _, _, derivatives_warning = await self._fetch_first_summary_payload(
                group="derivatives",
                data_type="openInterest",
                candidates=candidates,
                client=client,
                deadline_at=deadline_at,
            )
            if derivatives_warning:
                warnings.append(derivatives_warning)

        cleaned = {key: value for key, value in metrics.items() if value is not None}
        if summary_sources:
            cleaned["_summary_sources"] = sorted(summary_sources)
        return cleaned, warnings

    def _summary_slug_candidates(self, protocol: dict[str, Any], request: CollectorRequest) -> list[str]:
        values = [
            protocol.get("slug"),
            protocol.get("name"),
            request.target.coingecko_id,
            request.target.name,
            request.target.ticker,
        ]
        candidates: list[str] = []
        seen: set[str] = set()
        for value in values:
            candidate = _candidate_slug(str(value or ""))
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
        return candidates

    async def _fetch_first_summary_payload(
        self,
        *,
        group: str,
        data_type: str,
        candidates: list[str],
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> tuple[dict[str, Any] | None, str, str | None]:
        for candidate in candidates:
            response = await client.get(
                f"{self.settings.defillama_base_url}/summary/{group}/{candidate}",
                params={"dataType": data_type},
                timeout=self._request_timeout(deadline_at),
            )
            if response.status_code in {400, 404}:
                continue
            if response.status_code == 402:
                return None, "", f"defillama summary {group}/{data_type} is unavailable on current API plan"
            if response.status_code >= 500:
                response.raise_for_status()
            if response.status_code != 200:
                continue
            payload = response.json()
            if isinstance(payload, dict):
                return payload, f"{group}:{candidate}:{data_type}", None
        return None, "", None

    async def _fetch_protocol_by_candidates(
        self,
        *,
        slug: str | None,
        request: CollectorRequest,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> dict[str, Any] | None:
        candidates = [
            slug,
            _candidate_slug(request.target.name),
            _candidate_slug(request.target.ticker),
        ]
        for candidate in [item for item in candidates if item]:
            protocol = await self._fetch_protocol(candidate, client=client, deadline_at=deadline_at)
            if protocol is not None:
                return protocol
        return await self._search_protocol(request, client=client, deadline_at=deadline_at)

    async def _fetch_protocol(
        self,
        slug: str,
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> dict[str, Any] | None:
        response = await client.get(
            f"{self.settings.defillama_base_url}/protocol/{slug}",
            timeout=self._request_timeout(deadline_at),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def _search_protocol(
        self,
        request: CollectorRequest,
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> dict[str, Any] | None:
        response = await client.get(
            f"{self.settings.defillama_base_url}/protocols",
            timeout=self._request_timeout(deadline_at),
        )
        response.raise_for_status()
        protocols = response.json()
        target_name = request.target.name.lower()
        target_ticker = (request.target.ticker or "").lower()
        target_slug = _candidate_slug(request.target.coingecko_id, request.target.name, request.target.ticker)
        scored_candidates: list[tuple[int, dict[str, Any]]] = []
        for protocol in protocols:
            name = str(protocol.get("name") or "").lower()
            symbol = str(protocol.get("symbol") or "").lower()
            gecko_id = str(protocol.get("gecko_id") or "").lower()
            slug = str(protocol.get("slug") or "").lower()
            if request.target.coingecko_id and gecko_id == request.target.coingecko_id.lower():
                if slug:
                    return await self._fetch_protocol(str(slug), client=client, deadline_at=deadline_at)
            if name == target_name or (target_ticker and symbol == target_ticker):
                if slug:
                    return await self._fetch_protocol(str(slug), client=client, deadline_at=deadline_at)
            score = _protocol_candidate_score(
                protocol_name=name,
                protocol_slug=slug,
                protocol_symbol=symbol,
                protocol_gecko_id=gecko_id,
                target_name=target_name,
                target_ticker=target_ticker,
                target_slug=target_slug,
                target_gecko_id=(request.target.coingecko_id or "").lower(),
            )
            if score >= 4 and slug:
                scored_candidates.append((score, protocol))
        scored_candidates.sort(key=lambda item: item[0], reverse=True)
        if scored_candidates:
            best_score, best_protocol = scored_candidates[0]
            runner_up = scored_candidates[1][0] if len(scored_candidates) > 1 else -1
            if best_score >= 6 and best_score >= runner_up + 2:
                return await self._fetch_protocol(str(best_protocol.get("slug")), client=client, deadline_at=deadline_at)
        return None

    def _build_metrics(self, protocol: dict[str, Any]) -> dict[str, Any]:
        tvl = _normalize_tvl(protocol.get("tvl"))
        if tvl is None:
            tvl = _fallback_tvl(protocol.get("currentChainTvls"))
        volume_24h = _safe_float(
            protocol.get("volume24h")
            or protocol.get("dailyVolume")
        )
        fees_24h = _safe_float(
            protocol.get("fees24h")
            or protocol.get("dailyFees")
        )
        revenue_24h = _safe_float(
            protocol.get("revenue24h")
            or protocol.get("dailyRevenue")
        )
        open_interest_usd = _extract_open_interest_usd(protocol.get("openInterest"))
        chains = _extract_chains(protocol)
        chain_distribution = _extract_chain_distribution(
            protocol.get("currentChainTvls"),
            protocol.get("chainTvls"),
        )
        metrics = {
            "tvl": tvl,
            "market_cap": _safe_float(protocol.get("mcap")),
            "fdv": _safe_float(protocol.get("fdv")),
            "volume_24h": volume_24h,
            "trading_volume_24h": volume_24h,
            "fees_24h": fees_24h,
            "revenue_24h": revenue_24h,
            "protocol_revenue_24h": revenue_24h,
            "holder_revenue_24h": _safe_float(protocol.get("holdersRevenue24h")),
            "open_interest_usd": open_interest_usd,
            "open_interest": open_interest_usd,
            "change_1d": _safe_float(protocol.get("change_1d")),
            "change_7d": _safe_float(protocol.get("change_7d")),
            "change_1m": _safe_float(protocol.get("change_1m")),
            "chain_count": float(len(chains)) if chains else None,
            "liquidity_usd": tvl,
        }
        if chain_distribution:
            metrics["chain_distribution"] = chain_distribution
        return {key: value for key, value in metrics.items() if value is not None}

    def _build_protocol_item(self, protocol: dict[str, Any], request: CollectorRequest) -> dict[str, Any]:
        description = _truncate(str(protocol.get("description") or "").strip() or None)
        chains = _extract_chains(protocol)
        chain_distribution = _extract_chain_distribution(
            protocol.get("currentChainTvls"),
            protocol.get("chainTvls"),
        )
        content_parts = [part for part in [description, _format_category(protocol.get("category")), _format_chains(chains)] if part]
        return {
            "source": self.source_name,
            "source_id": protocol.get("slug"),
            "content_type": "protocol_data",
            "title": f"{protocol.get('name') or request.target.name} — DeFiLlama",
            "content": "\n".join(content_parts) if content_parts else None,
            "url": f"https://defillama.com/protocol/{protocol.get('slug')}",
            "metadata": {
                "slug": protocol.get("slug"),
                "category": protocol.get("category"),
                "chains": chains[:20] if isinstance(chains, list) else [],
                "website": protocol.get("url"),
                "chain_distribution": chain_distribution,
            },
        }

    async def _build_yield_items(
        self,
        protocol: dict[str, Any],
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> dict[str, Any]:
        response = await client.get(
            "https://yields.llama.fi/pools",
            timeout=self._request_timeout(deadline_at),
        )
        response.raise_for_status()
        payload = response.json()
        pools = payload.get("data") or []
        target_name = str(protocol.get("name") or "").lower()
        if not target_name:
            return {"items": [], "warnings": ["yield matching skipped because target name is empty"]}

        matched: list[dict[str, Any]] = []
        for pool in pools:
            project = str(pool.get("project") or "").lower()
            tvl_usd = _safe_float(pool.get("tvlUsd")) or 0.0
            if tvl_usd < 500_000:
                continue
            if project == target_name or target_name in project:
                matched.append(pool)

        matched.sort(key=lambda item: _safe_float(item.get("tvlUsd")) or 0.0, reverse=True)
        items = []
        for pool in matched[:3]:
            url = _pool_url(pool)
            items.append(
                {
                    "source": self.source_name,
                    "source_id": pool.get("pool"),
                    "content_type": "protocol_data",
                    "title": f"{pool.get('symbol') or protocol.get('name')} yield pool — DeFiLlama",
                    "content": None,
                    "url": url,
                    "metadata": {
                        "yield_pool": True,
                        "pool": pool.get("pool"),
                        "chain": pool.get("chain"),
                        "apy": _safe_float(pool.get("apy")),
                        "apy_base": _safe_float(pool.get("apyBase")),
                        "apy_reward": _safe_float(pool.get("apyReward")),
                        "tvl_usd": _safe_float(pool.get("tvlUsd")),
                        "pool_url": url,
                    },
                }
            )
        warnings = [] if items else ["no matching yield pools found"]
        return {"items": items, "warnings": warnings}

    async def _build_competitor_item(
        self,
        protocol: dict[str, Any],
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> dict[str, Any] | None:
        category = str(protocol.get("category") or "").strip()
        if not category:
            return None

        response = await client.get(
            f"{self.settings.defillama_base_url}/protocols",
            timeout=self._request_timeout(deadline_at),
        )
        response.raise_for_status()
        protocols = response.json()
        peers = [
            item
            for item in protocols
            if str(item.get("category") or "").strip().lower() == category.lower()
            and str(item.get("slug") or "").strip().lower() != str(protocol.get("slug") or "").strip().lower()
        ]
        peers.sort(key=lambda item: _safe_float(item.get("tvl")) or 0.0, reverse=True)
        top_peers = []
        for peer in peers[:5]:
            top_peers.append(
                {
                    "name": peer.get("name"),
                    "slug": peer.get("slug"),
                    "tvl": _safe_float(peer.get("tvl")),
                    "volume_24h": _safe_float(peer.get("volume24h") or peer.get("dailyVolume")),
                    "market_cap": _safe_float(peer.get("mcap")),
                    "url": f"https://defillama.com/protocol/{peer.get('slug')}",
                }
            )
        if not top_peers:
            return None
        return {
            "source": self.source_name,
            "source_id": f"{protocol.get('slug')}:competitors",
            "content_type": "protocol_data",
            "title": f"{protocol.get('name')} category peers — DeFiLlama",
            "content": None,
            "url": f"https://defillama.com/protocol/{protocol.get('slug')}",
            "metadata": {
                "competitor_data": True,
                "category": category,
                "competitors": top_peers,
                "target_snapshot": {
                    "tvl": _safe_float(protocol.get("tvl")) or _fallback_tvl(protocol.get("currentChainTvls")),
                    "volume_24h": _safe_float(protocol.get("volume24h") or protocol.get("dailyVolume")),
                    "market_cap": _safe_float(protocol.get("mcap")),
                },
            },
        }


def build_default_adapters(settings: Settings) -> dict[str, BaseSourceAdapter]:
    return {
        "coingecko": CoinGeckoSource(settings),
        "defillama": DefiLlamaSource(settings),
    }


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
        return float(value)
    return None


def _candidate_slug(*values: str | None) -> str | None:
    for value in values:
        text = str(value or "").strip().lower()
        if not text:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        slug = _DEFILLAMA_SLUG_ALIASES.get(slug, slug)
        if slug:
            return slug
    return None


def _normalize_tvl(value: Any) -> float | None:
    if isinstance(value, list) and value:
        latest = value[-1]
        if isinstance(latest, dict):
            return _safe_float(latest.get("totalLiquidityUSD"))
    return _safe_float(value)


def _fallback_tvl(current_chain_tvls: Any) -> float | None:
    if not isinstance(current_chain_tvls, dict):
        return None
    total = 0.0
    for chain, value in current_chain_tvls.items():
        if "-" in str(chain):
            continue
        numeric = _safe_float(value)
        if numeric is not None:
            total += numeric
    return total or None


def _extract_open_interest_usd(value: Any) -> float | None:
    direct = _safe_float(value)
    if direct is not None:
        return direct
    if isinstance(value, dict):
        for key in ("total", "usd", "openInterest", "open_interest", "oi"):
            parsed = _safe_float(value.get(key))
            if parsed is not None:
                return parsed
    return None


def _extract_chains(protocol: dict[str, Any]) -> list[str]:
    chains = protocol.get("chains")
    if isinstance(chains, list) and chains:
        normalized = [str(chain).strip() for chain in chains if str(chain).strip()]
        if normalized:
            return normalized
    inferred: list[str] = []
    for source in (protocol.get("currentChainTvls"), protocol.get("chainTvls")):
        if not isinstance(source, dict):
            continue
        for chain in source.keys():
            chain_text = str(chain).strip()
            if not chain_text or "-" in chain_text:
                continue
            if chain_text not in inferred:
                inferred.append(chain_text)
    return inferred


def _extract_chain_distribution(*sources: Any) -> dict[str, float] | None:
    chain_values: dict[str, float] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for chain, raw_value in source.items():
            chain_name = str(chain).strip()
            if not chain_name or "-" in chain_name:
                continue
            value = _safe_float(raw_value)
            if value is None:
                continue
            chain_values[chain_name] = value
    return chain_values or None


def _summary_metrics(payload: dict[str, Any], namespace: str) -> dict[str, float | None]:
    total_24h = _safe_float(payload.get("total24h"))
    total_7d = _safe_float(payload.get("total7d"))
    total_30d = _safe_float(payload.get("total30d"))
    total_1y = _safe_float(payload.get("total1y"))
    change_1d = _safe_float(payload.get("change_1d"))
    change_7d = _safe_float(payload.get("change_7d"))
    change_1m = _safe_float(payload.get("change_1m"))

    metrics: dict[str, float | None] = {
        f"{namespace}_24h": total_24h,
        f"{namespace}_7d": total_7d,
        f"{namespace}_30d": total_30d,
        f"{namespace}_1y": total_1y,
        f"{namespace}_change_1d": change_1d,
        f"{namespace}_change_7d": change_7d,
        f"{namespace}_change_1m": change_1m,
    }
    if namespace == "fees":
        metrics["fees_24h"] = total_24h
        metrics["annualized_fees"] = total_1y if total_1y is not None else (total_24h * 365.0 if total_24h is not None else None)
    elif namespace == "revenue":
        metrics["revenue_24h"] = total_24h
        metrics["protocol_revenue_24h"] = total_24h
        metrics["annualized_revenue"] = (
            total_1y if total_1y is not None else (total_24h * 365.0 if total_24h is not None else None)
        )
    elif namespace == "holder_revenue":
        metrics["holder_revenue_24h"] = total_24h
        metrics["annualized_holder_revenue"] = (
            total_1y if total_1y is not None else (total_24h * 365.0 if total_24h is not None else None)
        )
    elif namespace == "dex_volume":
        metrics["trading_volume_24h"] = total_24h
        metrics["volume_24h"] = total_24h

    return {key: value for key, value in metrics.items() if value is not None}


def _truncate(value: Any, limit: int = 600) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def _coingecko_official_links(links: dict[str, Any]) -> dict[str, str]:
    official_links: dict[str, str] = {}
    homepage = links.get("homepage") or []
    if isinstance(homepage, list) and homepage and homepage[0]:
        official_links["website"] = homepage[0]
    twitter = str(links.get("twitter_screen_name") or "").strip()
    if twitter:
        official_links["twitter"] = f"https://x.com/{twitter}"
    telegram = str(links.get("telegram_channel_identifier") or "").strip()
    if telegram:
        official_links["telegram"] = f"https://t.me/{telegram}"
    reddit = str(links.get("subreddit_url") or "").strip()
    if reddit:
        official_links["reddit"] = reddit
    github_urls = ((links.get("repos_url") or {}).get("github") or [])
    if isinstance(github_urls, list) and github_urls and github_urls[0]:
        official_links["github"] = github_urls[0]
    return official_links


def _format_category(category: Any) -> str | None:
    text = str(category or "").strip()
    return f"Category: {text}" if text else None


def _format_chains(chains: Any) -> str | None:
    if not isinstance(chains, list) or not chains:
        return None
    return f"Chains: {', '.join(str(chain) for chain in chains[:10])}"


def _pool_url(pool: dict[str, Any]) -> str | None:
    chain = str(pool.get("chain") or "").strip().lower().replace(" ", "-")
    project = str(pool.get("project") or "").strip().lower().replace(" ", "-")
    if chain and project:
        return f"https://defillama.com/yields/pool/{chain}/{project}"
    return "https://defillama.com/yields"


def _protocol_candidate_score(
    *,
    protocol_name: str,
    protocol_slug: str,
    protocol_symbol: str,
    protocol_gecko_id: str,
    target_name: str,
    target_ticker: str,
    target_slug: str | None,
    target_gecko_id: str,
) -> int:
    score = 0
    normalized_target_name = _normalize_lookup_text(target_name)
    normalized_protocol_name = _normalize_lookup_text(protocol_name)
    normalized_target_slug = _normalize_lookup_text(target_slug or "")
    normalized_protocol_slug = _normalize_lookup_text(protocol_slug)

    if target_gecko_id and target_gecko_id == protocol_gecko_id:
        score += 10
    if normalized_target_name and normalized_target_name == normalized_protocol_name:
        score += 8
    if normalized_target_slug and normalized_target_slug == normalized_protocol_slug:
        score += 8
    if target_ticker and target_ticker == protocol_symbol:
        score += 4
    if normalized_target_name and normalized_protocol_name:
        if normalized_target_name in normalized_protocol_name or normalized_protocol_name in normalized_target_name:
            score += 4
    if normalized_target_slug and normalized_protocol_slug:
        if normalized_target_slug in normalized_protocol_slug or normalized_protocol_slug in normalized_target_slug:
            score += 4

    target_tokens = set(_lookup_tokens(target_name))
    protocol_tokens = set(_lookup_tokens(protocol_name)) | set(_lookup_tokens(protocol_slug))
    token_overlap = len(target_tokens & protocol_tokens)
    if token_overlap:
        score += min(4, token_overlap * 2)
    return score


def _normalize_lookup_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value or "")


def _lookup_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", (value or "").lower()) if token]
