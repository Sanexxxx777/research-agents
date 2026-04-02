"""API-first source adapters for the external collector agent."""

from __future__ import annotations

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
            metadata={"resolved_coin_id": coin_id},
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
        for protocol in protocols:
            name = str(protocol.get("name") or "").lower()
            symbol = str(protocol.get("symbol") or "").lower()
            gecko_id = str(protocol.get("gecko_id") or "").lower()
            if request.target.coingecko_id and gecko_id == request.target.coingecko_id.lower():
                slug = protocol.get("slug")
                if slug:
                    return await self._fetch_protocol(str(slug), client=client, deadline_at=deadline_at)
            if name == target_name or (target_ticker and symbol == target_ticker):
                slug = protocol.get("slug")
                if slug:
                    return await self._fetch_protocol(str(slug), client=client, deadline_at=deadline_at)
        return None

    def _build_metrics(self, protocol: dict[str, Any]) -> dict[str, Any]:
        tvl = _normalize_tvl(protocol.get("tvl"))
        if tvl is None:
            tvl = _fallback_tvl(protocol.get("currentChainTvls"))
        metrics = {
            "tvl": tvl,
            "market_cap": _safe_float(protocol.get("mcap")),
            "fdv": _safe_float(protocol.get("fdv")),
            "volume_24h": _safe_float(protocol.get("volume24h") or protocol.get("dailyVolume")),
        }
        return {key: value for key, value in metrics.items() if value is not None}

    def _build_protocol_item(self, protocol: dict[str, Any], request: CollectorRequest) -> dict[str, Any]:
        description = _truncate(str(protocol.get("description") or "").strip() or None)
        chains = protocol.get("chains") or []
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
            },
        }


class DuneSource(BaseSourceAdapter):
    source_name = "dune"

    async def collect(
        self,
        request: CollectorRequest,
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> SourceResult:
        del request, client, deadline_at
        return failed_source_result(
            source=self.source_name,
            elapsed_ms=0,
            code="not_implemented",
            message="Dune integration is reserved as a v1 extension point and is not implemented",
            retryable=False,
            warnings=["query-based adapters will be added later"],
            provider="dune",
            endpoint=None,
        )


def build_default_adapters(settings: Settings) -> dict[str, BaseSourceAdapter]:
    return {
        "coingecko": CoinGeckoSource(settings),
        "defillama": DefiLlamaSource(settings),
        "dune": DuneSource(settings),
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
