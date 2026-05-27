"""Constrained source collectors for Market Intel Agent v1."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from market_intel_agent.config import (
    ALERTS_SECTOR_API_KEY,
    ALERTS_SECTOR_API_URL,
    COINGECKO_BASE_URL,
    DEFILLAMA_BASE_URL,
    HTTP_TIMEOUT_SECONDS,
)
from market_intel_agent.contracts import SourceFetchResult
from market_intel_agent.hub_client import HubClient
from market_intel_agent.sector_schema import SECTOR_SCHEMA, normalize_alerts_sector_name

LENDING_SCHEMA = SECTOR_SCHEMA["defi_lending"]
LENDING_SECTOR_METRICS = LENDING_SCHEMA["sector_metrics"]
LENDING_DERIVED_METRICS = LENDING_SCHEMA["derived_metrics"]
LENDING_COMPETITOR_METRICS = LENDING_SCHEMA["competitor_comparison"]
DEX_SCHEMA = SECTOR_SCHEMA["dex_spot"]
DEX_SECTOR_METRICS = DEX_SCHEMA["sector_metrics"]
DEX_DERIVED_METRICS = DEX_SCHEMA["derived_metrics"]
DEX_COMPETITOR_METRICS = DEX_SCHEMA["competitor_comparison"]
PERP_SCHEMA = SECTOR_SCHEMA["perp_dex"]
PERP_SECTOR_METRICS = PERP_SCHEMA["sector_metrics"]
PERP_DERIVED_METRICS = PERP_SCHEMA["derived_metrics"]
PERP_COMPETITOR_METRICS = PERP_SCHEMA["competitor_comparison"]
L1L2_SCHEMA = SECTOR_SCHEMA["l1_l2"]
L1L2_SECTOR_METRICS = L1L2_SCHEMA["sector_metrics"]
L1L2_DERIVED_METRICS = L1L2_SCHEMA["derived_metrics"]
L1L2_COMPETITOR_METRICS = L1L2_SCHEMA["competitor_comparison"]
ORACLE_SCHEMA = SECTOR_SCHEMA["oracles"]
ORACLE_SECTOR_METRICS = ORACLE_SCHEMA["sector_metrics"]
ORACLE_DERIVED_METRICS = ORACLE_SCHEMA["derived_metrics"]
ORACLE_COMPETITOR_METRICS = ORACLE_SCHEMA["competitor_comparison"]


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _target_identifiers(target: dict[str, Any]) -> set[str]:
    values = {
        str(target.get("coingecko_id") or ""),
        str(target.get("id") or ""),
        str(target.get("symbol") or ""),
        str(target.get("ticker") or ""),
        str(target.get("name") or ""),
    }
    identifiers = {item.strip().lower() for item in values if item.strip()}
    for item in list(identifiers):
        slug = "-".join(part for part in re.split(r"[^a-z0-9]+", item.lower()) if part)
        if slug:
            identifiers.add(slug)
    return identifiers


def _find_alerts_sector_for_target(payload: dict[str, Any], target: dict[str, Any]) -> tuple[str | None, str | None]:
    identifiers = _target_identifiers(target)
    sector_tokens = payload.get("sectorTokens") or {}
    if not isinstance(sector_tokens, dict):
        return None, None
    for display_name, tokens in sector_tokens.items():
        token_ids = {str(item or "").strip().lower() for item in (tokens or []) if str(item or "").strip()}
        if identifiers & token_ids:
            return str(display_name), normalize_alerts_sector_name(str(display_name))
    return None, None


def _build_alerts_sector_block(payload: dict[str, Any], target: dict[str, Any]) -> dict[str, Any] | None:
    display_name, normalized_name = _find_alerts_sector_for_target(payload, target)
    if not display_name or not normalized_name:
        return None
    sectors = payload.get("sectors") or {}
    sector_row = sectors.get(display_name) if isinstance(sectors, dict) else None
    if not isinstance(sector_row, dict):
        return None
    sector_tokens = payload.get("sectorTokens") or {}
    peers = list((sector_tokens.get(display_name) if isinstance(sector_tokens, dict) else None) or [])
    token_id = str(target.get("coingecko_id") or target.get("id") or "").strip().lower()
    token_row = (payload.get("data") or {}).get(token_id) if token_id else None
    token_change_24h = _safe_float((token_row or {}).get("change_24h")) if isinstance(token_row, dict) else None
    sector_avg_24h = _safe_float(sector_row.get("avg24h"))
    target_alpha_24h = (
        token_change_24h - sector_avg_24h
        if token_change_24h is not None and sector_avg_24h is not None
        else None
    )
    metrics = {
        "sector_mcap": _safe_float(sector_row.get("mcap")),
        "sector_avg_24h": sector_avg_24h,
        "sector_avg_7d": _safe_float(sector_row.get("avg7d")),
        "sector_avg_30d": _safe_float(sector_row.get("avg30d")),
        "sector_token_count": _safe_float(sector_row.get("tokenCount")),
        "sector_best_token_change_24h": _safe_float((sector_row.get("best") or {}).get("value")) if isinstance(sector_row.get("best"), dict) else None,
        "sector_target_alpha_24h": target_alpha_24h,
        "sector_peer_count": float(len(peers)) if peers else None,
    }
    metrics = {key: value for key, value in metrics.items() if value is not None}
    return {
        "sector": normalized_name,
        "source_sector": display_name,
        "sector_metrics": {"must": metrics, "should": {}, "optional_later": {}},
        "derived_metrics": {
            "must": {"sector_target_alpha_24h": target_alpha_24h} if target_alpha_24h is not None else {},
            "should": {},
            "optional_later": {},
        },
        "competitor_comparison": {"must": {}, "should": {}, "optional_later": {}},
        "peers": peers,
        "target_token": token_row if isinstance(token_row, dict) else None,
        "gaps": [
            {
                "group": "gaps",
                "tier": "must",
                "metric": "missing_deep_sector_fundamentals",
                "reason": "Alerts sector map provides market momentum coverage; deep sector fundamentals need dedicated source adapters.",
            }
        ],
    }


class HubMarketStatusSource:
    def __init__(self, hub_client: HubClient) -> None:
        self.hub_client = hub_client

    async def collect(self) -> SourceFetchResult:
        payload = await self.hub_client.get_market_status()
        return SourceFetchResult(
            source="hub_market_status",
            metrics={
                "market_state": payload.get("state"),
                "btc_24h": payload.get("btc_24h"),
                "btc_price": payload.get("btc_price"),
            },
            raw_payload=payload,
            citation_url=None,
            status="ok",
            note="Internal market regime overview from Hub",
        )


class AlertsSectorSource:
    def __init__(
        self,
        *,
        base_url: str = ALERTS_SECTOR_API_URL,
        api_key: str = ALERTS_SECTOR_API_KEY,
        timeout_seconds: float = HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def collect(self, target: dict[str, Any]) -> SourceFetchResult:
        params = {"key": self.api_key} if self.api_key else {}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
            payload = response.json()

        if not payload.get("success"):
            return SourceFetchResult(
                source="alerts_sector",
                status="partial",
                raw_payload=payload if isinstance(payload, dict) else {},
                citation_url=self.base_url,
                note="Alerts sector API returned an unsuccessful payload",
            )

        sector_block = _build_alerts_sector_block(payload, target)
        if sector_block is None:
            return SourceFetchResult(
                source="alerts_sector",
                status="partial",
                raw_payload={
                    "known_sectors": list((payload.get("sectors") or {}).keys()) if isinstance(payload.get("sectors"), dict) else [],
                    "token_count": payload.get("tokenCount"),
                    "timestamp": payload.get("timestamp"),
                },
                citation_url=self.base_url,
                note="Target was not found in Alerts sector map",
            )

        metrics = dict((sector_block.get("sector_metrics") or {}).get("must") or {})
        raw_payload = {
            "sector_block": sector_block,
            "alerts_sector": sector_block.get("source_sector"),
            "normalized_sector": sector_block.get("sector"),
            "known_sectors": list((payload.get("sectors") or {}).keys()) if isinstance(payload.get("sectors"), dict) else [],
            "token_count": payload.get("tokenCount"),
            "timestamp": payload.get("timestamp"),
        }
        return SourceFetchResult(
            source="alerts_sector",
            metrics=metrics,
            raw_payload=raw_payload,
            citation_url=self.base_url,
            status="ok",
            note="Sector momentum metrics from AlertsBot sector map",
        )


class CoinGeckoSource:
    def __init__(
        self,
        *,
        base_url: str = COINGECKO_BASE_URL,
        timeout_seconds: float = HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def collect(self, target: dict[str, Any]) -> SourceFetchResult:
        coin_id = await self._resolve_coin_id(target)
        if not coin_id:
            return SourceFetchResult(
                source="coingecko",
                status="skipped",
                note="CoinGecko id is not resolvable for target",
            )

        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "false",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/coins/{coin_id}", params=params)
            response.raise_for_status()
            payload = response.json()

        market_data = payload.get("market_data") or {}
        metrics = {
            "price_usd": _safe_float((market_data.get("current_price") or {}).get("usd")),
            "market_cap": _safe_float((market_data.get("market_cap") or {}).get("usd")),
            "volume_24h": _safe_float((market_data.get("total_volume") or {}).get("usd")),
            "fdv": _safe_float((market_data.get("fully_diluted_valuation") or {}).get("usd")),
            "circulating_supply": _safe_float(market_data.get("circulating_supply")),
            "total_supply": _safe_float(market_data.get("total_supply")),
            "price_change_24h": _safe_float(market_data.get("price_change_percentage_24h")),
            "price_change_7d": _safe_float(market_data.get("price_change_percentage_7d")),
        }
        metrics = {k: v for k, v in metrics.items() if v is not None}
        citation_url = payload.get("links", {}).get("homepage", [None])[0]
        if not citation_url:
            citation_url = f"https://www.coingecko.com/en/coins/{coin_id}"
        return SourceFetchResult(
            source="coingecko",
            metrics=metrics,
            raw_payload={
                "id": payload.get("id"),
                "symbol": payload.get("symbol"),
                "name": payload.get("name"),
                "categories": payload.get("categories") or [],
                "market_data": market_data,
            },
            citation_url=citation_url,
            status="ok",
        )

    async def _resolve_coin_id(self, target: dict[str, Any]) -> str | None:
        direct = str(target.get("coingecko_id") or "").strip().lower()
        if direct:
            return direct

        query = str(target.get("name") or target.get("ticker") or "").strip()
        if not query:
            return None

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(
                f"{self.base_url}/search",
                params={"query": query},
            )
            response.raise_for_status()
            payload = response.json()
        coins = payload.get("coins") or []
        if not coins:
            return None

        ticker = str(target.get("ticker") or "").strip().lower()
        exact = next(
            (
                coin
                for coin in coins
                if (coin.get("symbol") or "").strip().lower() == ticker and ticker
            ),
            None,
        )
        return str((exact or coins[0]).get("id") or "").strip().lower() or None


class DefiLlamaSource:
    def __init__(
        self,
        *,
        base_url: str = DEFILLAMA_BASE_URL,
        timeout_seconds: float = HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def collect(self, target: dict[str, Any]) -> SourceFetchResult:
        slug = self._candidate_slug(target)
        payload = await self._fetch_protocol(slug)
        if payload is None:
            payload = await self._find_and_fetch_protocol(target)

        chain_identity = await self._resolve_l1_l2_chain_identity(target=target, payload=payload)
        if payload is None and chain_identity is None:
            return SourceFetchResult(
                source="defillama",
                status="skipped",
                note="Protocol data not found in DefiLlama",
            )

        payload_obj = payload or {}
        tvl = self._normalize_tvl(payload_obj.get("tvl"))
        mcap = _safe_float(payload_obj.get("mcap"))
        fdv = _safe_float(payload_obj.get("fdv"))
        volume_24h = _safe_float(payload_obj.get("volume24h") or payload_obj.get("dailyVolume"))
        protocol_row = await self._resolve_protocol_row(
            target_slug=str(payload_obj.get("slug") or slug),
            target_name=str(payload_obj.get("name") or target.get("name") or ""),
            target_ticker=str(target.get("ticker") or payload_obj.get("symbol") or ""),
        )
        if tvl is None:
            tvl = _safe_float((protocol_row or {}).get("tvl"))
        if volume_24h is None:
            volume_24h = _safe_float(
                (protocol_row or {}).get("volume24h")
                or (protocol_row or {}).get("total24h")
            )
        resolved_category = str(
            payload_obj.get("category")
            or (protocol_row or {}).get("category")
            or target.get("category")
            or ""
        ).strip() or None
        is_lending_sector = self._is_lending_sector(
            category=resolved_category,
            borrowed_usd_hint=None,
        )
        is_dex_spot_sector = self._is_dex_spot_sector(category=resolved_category)
        is_perp_sector = self._is_perp_sector(
            category=resolved_category,
            target=target,
            payload=payload_obj,
        )
        is_oracle_sector = self._is_oracle_sector(
            category=resolved_category,
            target=target,
            payload=payload_obj,
            target_slug=str(payload_obj.get("slug") or slug),
        )
        target_prefers_l1_l2 = self._is_l1_l2_sector(
            category=None,
            target=target,
        )
        is_l1_l2_sector = target_prefers_l1_l2 or (
            chain_identity is not None and not (is_lending_sector or is_dex_spot_sector or is_oracle_sector)
        )

        borrowed_usd, supplied_usd = self._extract_lending_depth(payload_obj)
        lending_activity = self._resolve_lending_activity_metrics(payload_obj)
        net_borrow_flow_30d = _safe_float(lending_activity.get("net_borrow_flow_30d"))
        borrowed_growth_30d = _safe_float(lending_activity.get("borrowed_growth_30d"))
        if borrowed_usd is not None:
            is_lending_sector = True
        summary_slug = str(payload_obj.get("slug") or (chain_identity or {}).get("slug") or slug)
        summary_name = str(payload_obj.get("name") or (chain_identity or {}).get("name") or target.get("name") or "")
        business = await self._resolve_business_metrics(
            target_slug=summary_slug,
            target_name=summary_name,
            tvl_payload=payload_obj.get("tvl"),
            prefer_dex_volume=is_dex_spot_sector,
        )
        fees_24h = _safe_float(business.get("fees_24h"))
        fees_30d = _safe_float(business.get("fees_30d"))
        fees_90d = _safe_float(business.get("fees_90d"))
        fees_1y = _safe_float(business.get("fees_1y"))
        revenue_24h = _safe_float(business.get("revenue_24h"))
        revenue_30d = _safe_float(business.get("revenue_30d"))
        revenue_90d = _safe_float(business.get("revenue_90d"))
        revenue_1y = _safe_float(business.get("revenue_1y"))
        holder_revenue_24h = _safe_float(business.get("holder_revenue_24h"))
        holder_revenue_30d = _safe_float(business.get("holder_revenue_30d"))
        holder_revenue_90d = _safe_float(business.get("holder_revenue_90d"))
        holder_revenue_1y = _safe_float(business.get("holder_revenue_1y"))
        growth_30d = _safe_float(business.get("growth_30d"))
        growth_90d = _safe_float(business.get("growth_90d"))
        growth_1y = _safe_float(business.get("growth_1y"))
        growth_basis = str(business.get("growth_basis") or "").strip() or None
        annualized_revenue = _safe_float(business.get("annualized_revenue"))
        annualized_holder_revenue = _safe_float(business.get("annualized_holder_revenue"))
        annualized_fees = _safe_float(business.get("annualized_fees"))
        volume_30d = _safe_float(business.get("volume_30d"))
        volume_90d = _safe_float(business.get("volume_90d"))
        volume_1y = _safe_float(business.get("volume_1y"))
        volume_24h = volume_24h or _safe_float(business.get("volume_24h"))
        top_yields: list[dict[str, Any]] = []
        avg_apy: float | None = None
        avg_supply_apy: float | None = None
        avg_borrow_apy: float | None = None
        utilization_rate: float | None = None

        sector_metrics_block: dict[str, Any] = {}
        derived_metrics_block: dict[str, Any] = {}
        competitor_comparison: dict[str, Any] = {}
        quality_layer: dict[str, Any] = {}
        sector_gaps: list[dict[str, str]] = []
        metrics: dict[str, float] = {}
        sector_name: str | None = None
        sector_block_key: str | None = None
        output_slug_override: str | None = None
        output_name_override: str | None = None

        if is_lending_sector:
            top_yields, avg_apy, avg_supply_apy, avg_borrow_apy = await self._resolve_yields(
                target_name=str(target.get("name") or payload_obj.get("name") or ""),
            )
            utilization_rate = self._compute_utilization_rate(
                borrowed_usd=borrowed_usd,
                supplied_usd=supplied_usd,
                top_yields=top_yields,
            )
            competitors_universe = await self._resolve_competitors(
                category=str(resolved_category or ""),
                target_slug=str(payload_obj.get("slug") or slug),
                target_name=str(payload_obj.get("name") or target.get("name") or ""),
            )
            target_snapshot = {
                "name": str(payload_obj.get("name") or target.get("name") or ""),
                "slug": str(payload_obj.get("slug") or slug),
                "tvl": tvl,
                "fees_30d": fees_30d,
                "revenue_30d": revenue_30d,
                "growth_30d": growth_30d,
                "borrowed_usd": borrowed_usd,
                "utilization_rate": utilization_rate,
                "avg_apy": avg_apy,
                "is_target": True,
            }
            competitor_comparison = self._build_lending_competitor_comparison(
                competitors=competitors_universe,
                target_snapshot=target_snapshot,
                max_peers=5,
            )
            sector_metrics_block = self._build_lending_sector_metrics(
                tvl=tvl,
                borrowed_usd=borrowed_usd,
                supplied_usd=supplied_usd,
                fees_30d=fees_30d,
                fees_90d=fees_90d,
                fees_1y=fees_1y,
                revenue_30d=revenue_30d,
                revenue_90d=revenue_90d,
                revenue_1y=revenue_1y,
                holder_revenue_30d=holder_revenue_30d,
                holder_revenue_90d=holder_revenue_90d,
                holder_revenue_1y=holder_revenue_1y,
                annualized_revenue=annualized_revenue,
                annualized_holder_revenue=annualized_holder_revenue,
                net_borrow_flow_30d=net_borrow_flow_30d,
                borrowed_growth_30d=borrowed_growth_30d,
                growth_30d=growth_30d,
                growth_90d=growth_90d,
                growth_1y=growth_1y,
                avg_apy=avg_apy,
                market_cap=mcap,
                volume_30d=volume_30d,
                utilization_rate=utilization_rate,
                avg_borrow_apy=avg_borrow_apy,
                avg_supply_apy=avg_supply_apy,
                fees_24h=fees_24h,
                revenue_24h=revenue_24h,
                holder_revenue_24h=holder_revenue_24h,
                volume_24h=volume_24h,
                liquidations_24h=None,
                bad_debt_usd=None,
            )
            derived_metrics_block = self._build_lending_derived_metrics(
                tvl=tvl,
                market_cap=mcap,
                borrowed_usd=borrowed_usd,
                supplied_usd=supplied_usd,
                revenue_30d=revenue_30d,
                avg_borrow_apy=avg_borrow_apy,
                avg_supply_apy=avg_supply_apy,
                liquidations_24h=None,
                bad_debt_usd=None,
            )
            quality_layer = self._build_lending_quality_layer(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
            )
            sector_gaps = self._build_lending_gaps(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
                competitor_comparison=competitor_comparison,
                is_lending_sector=True,
            )
            metrics = self._build_lending_flat_metrics(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
                include_non_lending_defaults=False,
            )
            if "mcap_to_tvl_ratio" in metrics and "mcap_tvl" not in metrics:
                metrics["mcap_tvl"] = metrics["mcap_to_tvl_ratio"]
            sector_name = "defi_lending"
            sector_block_key = "lending_block"
        elif (
            (target_prefers_l1_l2 and chain_identity is not None)
            or (is_l1_l2_sector and not is_dex_spot_sector)
        ) and not is_perp_sector:
            chain_name = str((chain_identity or {}).get("name") or payload_obj.get("name") or target.get("name") or "")
            chain_slug = str((chain_identity or {}).get("slug") or payload_obj.get("slug") or slug)
            l1 = await self._resolve_l1_l2_metrics(
                chain_name=chain_name,
                chain_slug=chain_slug,
                chain_tvl_hint=_safe_float((chain_identity or {}).get("tvl")),
                fees_30d=fees_30d,
                fees_90d=fees_90d,
                fees_1y=fees_1y,
                revenue_30d=revenue_30d,
                revenue_90d=revenue_90d,
                revenue_1y=revenue_1y,
                growth_30d=growth_30d,
                growth_90d=growth_90d,
                growth_1y=growth_1y,
                annualized_fees=annualized_fees,
                annualized_revenue=annualized_revenue,
            )
            competitors_universe = await self._resolve_l1_l2_competitors(
                target_chain_name=chain_name,
                target_chain_slug=chain_slug,
                max_universe=15,
            )
            target_snapshot = {
                "name": chain_name,
                "slug": chain_slug,
                "ecosystem_tvl": _safe_float(l1.get("ecosystem_tvl")),
                "active_addresses_30d": _safe_float(l1.get("active_addresses_30d")),
                "fees_30d": _safe_float(l1.get("fees_30d")),
                "revenue_30d": _safe_float(l1.get("revenue_30d")),
                "stablecoin_supply_usd": _safe_float(l1.get("stablecoin_supply_usd")),
                "growth_30d": _safe_float(l1.get("growth_30d")),
                "app_count_30d": _safe_float(l1.get("app_count_30d")),
                "is_target": True,
            }
            competitor_comparison = self._build_l1_l2_competitor_comparison(
                competitors=competitors_universe,
                target_snapshot=target_snapshot,
                max_peers=5,
            )
            sector_metrics_block = self._build_l1_l2_sector_metrics(
                l1=l1,
            )
            derived_metrics_block = self._build_l1_l2_derived_metrics(
                l1=l1,
            )
            quality_layer = self._build_l1_l2_quality_layer(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
            )
            sector_gaps = self._build_l1_l2_gaps(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
                competitor_comparison=competitor_comparison,
                is_l1_l2_sector=True,
            )
            metrics = self._build_l1_l2_flat_metrics(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
                include_non_l1_defaults=False,
            )
            sector_name = "l1_l2"
            sector_block_key = "l1_l2_block"
        elif is_perp_sector:
            perp = await self._resolve_perp_metrics(
                target=target,
                payload=payload_obj,
                fees_30d=fees_30d,
                fees_90d=fees_90d,
                fees_1y=fees_1y,
                revenue_30d=revenue_30d,
                revenue_90d=revenue_90d,
                revenue_1y=revenue_1y,
                growth_30d=growth_30d,
                growth_90d=growth_90d,
                growth_1y=growth_1y,
                annualized_fees=annualized_fees,
                annualized_revenue=annualized_revenue,
            )
            competitors_universe = await self._resolve_perp_competitors(
                target_perp_slug=str(perp.get("perp_slug") or ""),
                max_universe=20,
            )
            target_snapshot = {
                "name": str(perp.get("perp_name") or payload_obj.get("name") or target.get("name") or ""),
                "slug": str(perp.get("perp_slug") or payload_obj.get("slug") or slug),
                "open_interest_usd": _safe_float(perp.get("open_interest_usd")),
                "open_interest_share_30d": _safe_float(perp.get("open_interest_share_30d")),
                "fees_30d": _safe_float(perp.get("fees_30d")),
                "revenue_30d": _safe_float(perp.get("revenue_30d")),
                "growth_30d": _safe_float(perp.get("growth_30d")),
                "active_users_30d": _safe_float(perp.get("active_users_30d")),
                "perp_volume_30d": _safe_float(perp.get("perp_volume_30d")),
                "is_target": True,
            }
            competitor_comparison = self._build_perp_competitor_comparison(
                competitors=competitors_universe,
                target_snapshot=target_snapshot,
                max_peers=5,
            )
            sector_metrics_block = self._build_perp_sector_metrics(perp=perp)
            derived_metrics_block = self._build_perp_derived_metrics(perp=perp)
            quality_layer = self._build_perp_quality_layer(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
            )
            sector_gaps = self._build_perp_gaps(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
                competitor_comparison=competitor_comparison,
                is_perp_sector=True,
            )
            metrics = self._build_perp_flat_metrics(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
                include_non_perp_defaults=False,
            )
            sector_name = "perp_dex"
            sector_block_key = "perp_block"
            output_slug_override = str(perp.get("perp_slug") or "").strip() or None
            output_name_override = str(perp.get("perp_name") or "").strip() or None
        elif is_oracle_sector and not is_dex_spot_sector:
            oracle = await self._resolve_oracle_metrics(
                target=target,
                payload=payload_obj,
                target_slug=summary_slug,
                target_name=summary_name,
                fees_30d=fees_30d,
                fees_90d=fees_90d,
                fees_1y=fees_1y,
                revenue_30d=revenue_30d,
                revenue_90d=revenue_90d,
                revenue_1y=revenue_1y,
                growth_30d=growth_30d,
                growth_90d=growth_90d,
                growth_1y=growth_1y,
                annualized_fees=annualized_fees,
                annualized_revenue=annualized_revenue,
            )
            competitors_universe = await self._resolve_oracle_competitors(
                target_oracle_slug=str(oracle.get("oracle_slug") or summary_slug or ""),
                target_oracle_name=str(oracle.get("oracle_name") or summary_name or ""),
                max_universe=20,
            )
            target_snapshot = {
                "name": str(oracle.get("oracle_name") or summary_name or target.get("name") or ""),
                "slug": str(oracle.get("oracle_slug") or summary_slug or ""),
                "integrations_count": _safe_float(oracle.get("integrations_count")),
                "secured_value_usd": _safe_float(oracle.get("secured_value_usd")),
                "usage_30d": _safe_float(oracle.get("usage_30d")),
                "fees_30d": _safe_float(oracle.get("fees_30d")),
                "revenue_30d": _safe_float(oracle.get("revenue_30d")),
                "chain_count": _safe_float(oracle.get("chain_count")),
                "client_protocols_count": _safe_float(oracle.get("client_protocols_count")),
                "growth_30d": _safe_float(oracle.get("growth_30d")),
                "network_diversification_score": _safe_float(oracle.get("network_diversification_score")),
                "token_dependency_score": _safe_float(oracle.get("token_dependency_score")),
                "is_target": True,
            }
            competitor_comparison = self._build_oracle_competitor_comparison(
                competitors=competitors_universe,
                target_snapshot=target_snapshot,
                max_peers=5,
            )
            sector_metrics_block = self._build_oracle_sector_metrics(oracle=oracle)
            derived_metrics_block = self._build_oracle_derived_metrics(oracle=oracle)
            quality_layer = self._build_oracle_quality_layer(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
            )
            sector_gaps = self._build_oracle_gaps(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
                competitor_comparison=competitor_comparison,
                is_oracle_sector=True,
            )
            metrics = self._build_oracle_flat_metrics(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
                include_non_oracle_defaults=False,
            )
            sector_name = "oracles"
            sector_block_key = "oracle_block"
            output_slug_override = str(oracle.get("oracle_slug") or summary_slug or "").strip() or None
            output_name_override = str(oracle.get("oracle_name") or summary_name or "").strip() or None
        elif is_dex_spot_sector:
            competitors_universe = await self._resolve_dex_competitors(
                category=str(resolved_category or ""),
                target_slug=str(payload_obj.get("slug") or slug),
                target_name=str(payload_obj.get("name") or target.get("name") or ""),
            )
            target_snapshot = {
                "name": str(payload_obj.get("name") or target.get("name") or ""),
                "slug": str(payload_obj.get("slug") or slug),
                "tvl": tvl,
                "dex_volume_30d": volume_30d,
                "fees_30d": fees_30d,
                "revenue_30d": revenue_30d,
                "growth_30d": growth_30d,
                "is_target": True,
            }
            competitor_comparison = self._build_dex_competitor_comparison(
                competitors=competitors_universe,
                target_snapshot=target_snapshot,
                max_peers=5,
            )
            sector_metrics_block = self._build_dex_sector_metrics(
                tvl=tvl,
                market_cap=mcap,
                dex_volume_24h=volume_24h,
                dex_volume_30d=volume_30d,
                dex_volume_90d=volume_90d,
                dex_volume_1y=volume_1y,
                fees_24h=fees_24h,
                fees_30d=fees_30d,
                fees_90d=fees_90d,
                fees_1y=fees_1y,
                revenue_24h=revenue_24h,
                revenue_30d=revenue_30d,
                revenue_90d=revenue_90d,
                revenue_1y=revenue_1y,
                holder_revenue_30d=holder_revenue_30d,
                holder_revenue_90d=holder_revenue_90d,
                holder_revenue_1y=holder_revenue_1y,
                growth_30d=growth_30d,
                growth_90d=growth_90d,
                growth_1y=growth_1y,
                annualized_fees=annualized_fees,
                annualized_revenue=annualized_revenue,
            )
            derived_metrics_block = self._build_dex_derived_metrics(
                tvl=tvl,
                market_cap=mcap,
                dex_volume_30d=volume_30d,
                fees_30d=fees_30d,
                revenue_30d=revenue_30d,
            )
            quality_layer = self._build_dex_quality_layer(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
            )
            sector_gaps = self._build_dex_gaps(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
                competitor_comparison=competitor_comparison,
                is_dex_spot_sector=True,
            )
            metrics = self._build_dex_flat_metrics(
                sector_metrics=sector_metrics_block,
                derived_metrics=derived_metrics_block,
                include_non_dex_defaults=False,
            )
            sector_name = "dex_spot"
            sector_block_key = "dex_block"
        else:
            competitor_comparison = {"projects": [], "target_ranks": {}, "universe_size": 0}
            metrics = {
                "tvl": tvl,
                "market_cap": mcap,
                "fees_30d": fees_30d,
                "revenue_30d": revenue_30d,
                "volume_30d": volume_30d,
                "growth_30d": growth_30d,
            }

        metrics["fdv"] = fdv
        metrics = {k: v for k, v in metrics.items() if v is not None}

        sector_block: dict[str, Any] | None = None
        if sector_name and sector_block_key:
            sector_block = {
                "sector": sector_name,
                "sector_metrics": sector_metrics_block,
                "derived_metrics": derived_metrics_block,
                "competitor_comparison": competitor_comparison,
                "gaps": sector_gaps,
                "quality_layer": quality_layer,
            }

        slug_out = output_slug_override or payload_obj.get("slug") or slug
        raw_payload = {
            "id": payload_obj.get("id"),
            "slug": slug_out,
            "name": output_name_override or payload_obj.get("name") or (chain_identity or {}).get("name"),
            "chain_identity": chain_identity,
            "category": resolved_category,
            "chain": payload_obj.get("chain") or (chain_identity or {}).get("name"),
            "chains": payload_obj.get("chains") or [],
            "tvl": payload_obj.get("tvl"),
            "mcap": payload_obj.get("mcap"),
            "fdv": payload_obj.get("fdv"),
            "volume24h": volume_24h,
            "volume30d": volume_30d,
            "volume90d": volume_90d,
            "volume1y": volume_1y,
            "fees24h": payload_obj.get("fees24h"),
            "fees30d": fees_30d,
            "fees90d": fees_90d,
            "fees1y": fees_1y,
            "revenue24h": payload_obj.get("revenue24h"),
            "revenue30d": revenue_30d,
            "revenue90d": revenue_90d,
            "revenue1y": revenue_1y,
            "holder_revenue24h": holder_revenue_24h,
            "holder_revenue30d": holder_revenue_30d,
            "holder_revenue90d": holder_revenue_90d,
            "holder_revenue1y": holder_revenue_1y,
            "growth_30d": growth_30d,
            "growth_90d": growth_90d,
            "growth_1y": growth_1y,
            "growth_basis": growth_basis,
            "annualized_fees": annualized_fees,
            "annualized_revenue": annualized_revenue,
            "annualized_holder_revenue": annualized_holder_revenue,
            "net_borrow_flow_30d": net_borrow_flow_30d,
            "borrowed_growth_30d": borrowed_growth_30d,
            "borrowed_usd_30d_ago": _safe_float(lending_activity.get("borrowed_usd_30d_ago")),
            "borrowed_usd": borrowed_usd,
            "supplied_usd": supplied_usd,
            "top_yields": top_yields,
            "avg_apy": avg_apy,
            "avg_supply_apy": avg_supply_apy,
            "avg_borrow_apy": avg_borrow_apy,
            "utilization_rate": utilization_rate,
            "short_term_context": {
                "fees_24h": fees_24h,
                "revenue_24h": revenue_24h,
                "holder_revenue_24h": holder_revenue_24h,
                "volume_24h": volume_24h,
            },
            "competitors": competitor_comparison.get("projects", []),
            "competitor_comparison": competitor_comparison,
            "gaps": sector_gaps,
            "quality_layer": quality_layer,
        }
        if sector_block is not None:
            raw_payload["sector_block"] = sector_block
            if sector_block_key:
                raw_payload[sector_block_key] = sector_block

        return SourceFetchResult(
            source="defillama",
            metrics=metrics,
            raw_payload=raw_payload,
            citation_url=f"https://defillama.com/protocol/{slug_out}",
            status="ok",
        )

    def _normalize_tvl(self, raw_tvl: Any) -> float | None:
        numeric = _safe_float(raw_tvl)
        if numeric is not None:
            return numeric
        if isinstance(raw_tvl, list) and raw_tvl:
            last = raw_tvl[-1] or {}
            return _safe_float(last.get("totalLiquidityUSD"))
        return None

    async def _fetch_protocol(self, slug: str) -> dict[str, Any] | None:
        if not slug:
            return None
        request_timeout = max(self.timeout_seconds, 60.0)
        for _ in range(3):
            try:
                async with httpx.AsyncClient(timeout=request_timeout) as client:
                    resp = await client.get(f"{self.base_url}/protocol/{slug}")
            except Exception as exc:
                _ = exc
                continue
            if resp.status_code == 404:
                return None
            try:
                resp.raise_for_status()
            except Exception as exc:
                _ = exc
                continue
            return resp.json()
        return None

    async def _find_and_fetch_protocol(self, target: dict[str, Any]) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.get(f"{self.base_url}/protocols")
            resp.raise_for_status()
            protocols = resp.json()

        name = str(target.get("name") or "").strip().lower()
        ticker = str(target.get("ticker") or "").strip().lower()
        for item in protocols:
            candidate_name = str(item.get("name") or "").strip().lower()
            candidate_symbol = str(item.get("symbol") or "").strip().lower()
            if candidate_name == name or (ticker and candidate_symbol == ticker):
                slug = str(item.get("slug") or "").strip()
                if slug:
                    return await self._fetch_protocol(slug)
        return None

    async def _resolve_protocol_row(
        self,
        *,
        target_slug: str,
        target_name: str,
        target_ticker: str,
    ) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(f"{self.base_url}/protocols")
                resp.raise_for_status()
                protocols = resp.json()
        except Exception:
            return None

        slug_l = target_slug.strip().lower()
        name_l = target_name.strip().lower()
        ticker_l = target_ticker.strip().lower()

        # 1) Strict match first.
        for row in protocols:
            row_slug = str(row.get("slug") or "").strip().lower()
            row_name = str(row.get("name") or "").strip().lower()
            if row_slug and row_slug == slug_l:
                return row
            if row_name and row_name == name_l:
                return row

        # 2) Fuzzy fallback for aggregate names like "aave" -> "aave-v3" (largest TVL).
        best_row: dict[str, Any] | None = None
        best_score: tuple[int, float] | None = None
        for row in protocols:
            row_slug = str(row.get("slug") or "").strip().lower()
            row_name = str(row.get("name") or "").strip().lower()
            row_symbol = str(row.get("symbol") or "").strip().lower()
            tvl = float(row.get("tvl") or 0.0)

            score = 0
            if slug_l and row_slug:
                if row_slug.startswith(f"{slug_l}-"):
                    score += 4
                elif slug_l in row_slug:
                    score += 2
            if name_l and row_name:
                if row_name.startswith(name_l):
                    score += 4
                elif name_l in row_name:
                    score += 2
            if ticker_l and row_symbol == ticker_l:
                score += 3

            if score <= 0:
                continue
            candidate_score = (score, tvl)
            if best_score is None or candidate_score > best_score:
                best_score = candidate_score
                best_row = row
        if best_row is not None:
            return best_row
        return None

    def _extract_lending_depth(self, payload: dict[str, Any]) -> tuple[float | None, float | None]:
        current = payload.get("currentChainTvls") or {}
        if not isinstance(current, dict):
            return None, None

        borrowed = _safe_float(current.get("borrowed"))
        if borrowed is None:
            borrowed_sum = 0.0
            for key, value in current.items():
                if not isinstance(value, (int, float)):
                    continue
                key_l = str(key).lower()
                if key_l.endswith("-borrowed") or key_l == "borrowed":
                    borrowed_sum += float(value)
            borrowed = borrowed_sum if borrowed_sum > 0 else None

        supplied_sum = 0.0
        for key, value in current.items():
            if not isinstance(value, (int, float)):
                continue
            key_l = str(key).lower()
            if "-" in key_l:
                continue
            if key_l in {"staking", "pool2", "treasury", "borrowed"}:
                continue
            supplied_sum += float(value)
        supplied = supplied_sum if supplied_sum > 0 else None

        if supplied is None and _safe_float(payload.get("tvl")):
            supplied = _safe_float(payload.get("tvl"))
        return borrowed, supplied

    def _resolve_lending_activity_metrics(self, payload: dict[str, Any]) -> dict[str, float | None]:
        borrowed_series = self._extract_borrowed_series(payload)
        current_borrowed = borrowed_series[-1][1] if borrowed_series else None
        borrowed_30d_ago = self._series_value_days_ago(borrowed_series, 30)

        net_borrow_flow_30d: float | None = None
        borrowed_growth_30d: float | None = None
        if current_borrowed is not None and borrowed_30d_ago is not None:
            net_borrow_flow_30d = current_borrowed - borrowed_30d_ago
            if borrowed_30d_ago > 0:
                borrowed_growth_30d = (current_borrowed / borrowed_30d_ago) - 1.0

        return {
            "borrowed_usd_current": current_borrowed,
            "borrowed_usd_30d_ago": borrowed_30d_ago,
            "net_borrow_flow_30d": net_borrow_flow_30d,
            "borrowed_growth_30d": borrowed_growth_30d,
        }

    def _extract_borrowed_series(self, payload: dict[str, Any]) -> list[tuple[int, float]]:
        chain_tvls = payload.get("chainTvls")
        if not isinstance(chain_tvls, dict):
            return []

        by_ts: dict[int, float] = {}
        for key, value in chain_tvls.items():
            key_l = str(key).strip().lower()
            if key_l != "borrowed" and not key_l.endswith("-borrowed"):
                continue
            chain_series = self._extract_tvl_series(value)
            for ts, amount in chain_series:
                by_ts[ts] = by_ts.get(ts, 0.0) + amount

        return sorted(by_ts.items(), key=lambda item: item[0])

    def _extract_tvl_series(self, raw_series: Any) -> list[tuple[int, float]]:
        if not isinstance(raw_series, dict):
            return []
        tvl = raw_series.get("tvl")
        if not isinstance(tvl, list):
            return []
        out: list[tuple[int, float]] = []
        for row in tvl:
            if not isinstance(row, dict):
                continue
            ts = row.get("date")
            amount = _safe_float(row.get("totalLiquidityUSD"))
            if not isinstance(ts, (int, float)) or amount is None:
                continue
            out.append((int(ts), amount))
        out.sort(key=lambda item: item[0])
        return out

    def _series_value_days_ago(self, series: list[tuple[int, float]], days: int) -> float | None:
        if len(series) < 2:
            return None
        target_ts = series[-1][0] - (days * 86400)
        past = [value for ts, value in series if ts <= target_ts]
        if not past:
            return None
        return past[-1]

    async def _resolve_business_metrics(
        self,
        *,
        target_slug: str,
        target_name: str,
        tvl_payload: Any,
        prefer_dex_volume: bool = False,
    ) -> dict[str, Any]:
        fee_summary = await self._fetch_fee_summary(
            target_slug=target_slug,
            target_name=target_name,
            data_type="dailyFees",
        )
        revenue_summary = await self._fetch_fee_summary(
            target_slug=target_slug,
            target_name=target_name,
            data_type="dailyRevenue",
        )
        holder_summary = await self._fetch_fee_summary(
            target_slug=target_slug,
            target_name=target_name,
            data_type="dailyHoldersRevenue",
        )
        volume_summary = await self._fetch_fee_summary(
            target_slug=target_slug,
            target_name=target_name,
            data_type="dailyVolume",
        )
        dex_volume_summary = (
            await self._fetch_dex_summary(target_slug=target_slug, target_name=target_name)
            if prefer_dex_volume
            else None
        )
        preferred_volume_summary = dex_volume_summary or volume_summary

        fees_24h = self._summary_total(fee_summary, 1)
        fees_30d = self._summary_total(fee_summary, 30)
        fees_90d = self._summary_total(fee_summary, 90)
        fees_1y = self._summary_total(fee_summary, 365)

        revenue_24h = self._summary_total(revenue_summary, 1)
        revenue_30d = self._summary_total(revenue_summary, 30)
        revenue_90d = self._summary_total(revenue_summary, 90)
        revenue_1y = self._summary_total(revenue_summary, 365)

        holder_revenue_24h = self._summary_total(holder_summary, 1)
        holder_revenue_30d = self._summary_total(holder_summary, 30)
        holder_revenue_90d = self._summary_total(holder_summary, 90)
        holder_revenue_1y = self._summary_total(holder_summary, 365)
        volume_24h = self._summary_total(preferred_volume_summary, 1)
        volume_30d = self._summary_total(preferred_volume_summary, 30)
        volume_90d = self._summary_total(preferred_volume_summary, 90)
        volume_1y = self._summary_total(preferred_volume_summary, 365)

        revenue_growth_30d = self._summary_growth(revenue_summary, 30)
        revenue_growth_90d = self._summary_growth(revenue_summary, 90)
        revenue_growth_1y = self._summary_growth(revenue_summary, 365)
        fees_growth_30d = self._summary_growth(fee_summary, 30)
        fees_growth_90d = self._summary_growth(fee_summary, 90)
        fees_growth_1y = self._summary_growth(fee_summary, 365)
        volume_growth_30d = self._summary_growth(preferred_volume_summary, 30)
        volume_growth_90d = self._summary_growth(preferred_volume_summary, 90)
        volume_growth_1y = self._summary_growth(preferred_volume_summary, 365)
        tvl_growth_30d = self._tvl_growth(raw_tvl=tvl_payload, days=30)
        tvl_growth_90d = self._tvl_growth(raw_tvl=tvl_payload, days=90)
        tvl_growth_1y = self._tvl_growth(raw_tvl=tvl_payload, days=365)

        growth_30d, growth_30d_basis = self._pick_growth(
            volume_growth=volume_growth_30d,
            revenue_growth=revenue_growth_30d,
            fees_growth=fees_growth_30d,
            tvl_growth=tvl_growth_30d,
        )
        growth_90d, growth_90d_basis = self._pick_growth(
            volume_growth=volume_growth_90d,
            revenue_growth=revenue_growth_90d,
            fees_growth=fees_growth_90d,
            tvl_growth=tvl_growth_90d,
        )
        growth_1y, growth_1y_basis = self._pick_growth(
            volume_growth=volume_growth_1y,
            revenue_growth=revenue_growth_1y,
            fees_growth=fees_growth_1y,
            tvl_growth=tvl_growth_1y,
        )

        growth_basis = None
        for basis in (growth_30d_basis, growth_90d_basis, growth_1y_basis):
            if basis:
                growth_basis = basis
                break

        annualized_fees = (fees_30d * 365.0 / 30.0) if fees_30d is not None else None
        annualized_revenue = (revenue_30d * 365.0 / 30.0) if revenue_30d is not None else None
        annualized_holder_revenue = (
            holder_revenue_30d * 365.0 / 30.0
            if holder_revenue_30d is not None
            else None
        )

        return {
            "fees_24h": fees_24h,
            "fees_30d": fees_30d,
            "fees_90d": fees_90d,
            "fees_1y": fees_1y,
            "revenue_24h": revenue_24h,
            "revenue_30d": revenue_30d,
            "revenue_90d": revenue_90d,
            "revenue_1y": revenue_1y,
            "holder_revenue_24h": holder_revenue_24h,
            "holder_revenue_30d": holder_revenue_30d,
            "holder_revenue_90d": holder_revenue_90d,
            "holder_revenue_1y": holder_revenue_1y,
            "volume_24h": volume_24h,
            "volume_30d": volume_30d,
            "volume_90d": volume_90d,
            "volume_1y": volume_1y,
            "growth_30d": growth_30d,
            "growth_90d": growth_90d,
            "growth_1y": growth_1y,
            "growth_basis": growth_basis,
            "annualized_fees": annualized_fees,
            "annualized_revenue": annualized_revenue,
            "annualized_holder_revenue": annualized_holder_revenue,
        }

    async def _fetch_fee_summary(
        self,
        *,
        target_slug: str,
        target_name: str,
        data_type: str,
    ) -> dict[str, Any] | None:
        candidates: list[str] = []
        slug = target_slug.strip().lower()
        name_slug = target_name.strip().lower().replace(" ", "-")
        if slug:
            candidates.append(slug)
        if name_slug and name_slug not in candidates:
            candidates.append(name_slug)
        for candidate in candidates:
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.get(
                        f"{self.base_url}/summary/fees/{candidate}",
                        params={"dataType": data_type},
                    )
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            try:
                payload = resp.json() or {}
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("totalDataChart"):
                return payload
            if isinstance(payload, dict) and payload.get("total24h") is not None:
                return payload
        return None

    async def _fetch_dex_summary(
        self,
        *,
        target_slug: str,
        target_name: str,
    ) -> dict[str, Any] | None:
        candidates: list[str] = []
        slug = target_slug.strip().lower()
        name_slug = target_name.strip().lower().replace(" ", "-")
        if slug:
            candidates.append(slug)
        if name_slug and name_slug not in candidates:
            candidates.append(name_slug)
        for candidate in candidates:
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.get(f"{self.base_url}/summary/dexs/{candidate}")
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            try:
                payload = resp.json() or {}
            except Exception:
                continue
            if isinstance(payload, dict) and (
                payload.get("totalDataChart") or payload.get("total24h") is not None
            ):
                return payload
        return None

    def _summary_series(self, summary_payload: dict[str, Any] | None) -> list[tuple[int, float]]:
        chart = (summary_payload or {}).get("totalDataChart") or []
        series: list[tuple[int, float]] = []
        for row in chart:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            ts = row[0]
            val = _safe_float(row[1])
            if not isinstance(ts, (int, float)) or val is None:
                continue
            series.append((int(ts), val))
        series.sort(key=lambda item: item[0])
        return series

    def _sum_window_days(
        self,
        *,
        series: list[tuple[int, float]],
        days: int,
        offset_days: int = 0,
    ) -> float | None:
        if not series:
            return None
        last_ts = series[-1][0]
        window_end = last_ts - (offset_days * 86400)
        window_start = window_end - (days * 86400)
        values = [value for ts, value in series if window_start < ts <= window_end]
        if len(values) < max(3, int(days * 0.5)):
            return None
        return float(sum(values))

    def _summary_total(self, summary_payload: dict[str, Any] | None, days: int) -> float | None:
        if not summary_payload:
            return None
        if days == 1:
            direct = _safe_float(summary_payload.get("total24h"))
            if direct is not None:
                return direct
        if days == 30:
            direct = _safe_float(summary_payload.get("total30d"))
            if direct is not None:
                return direct
        if days == 365:
            direct = _safe_float(summary_payload.get("total1y"))
            if direct is not None:
                return direct
        series = self._summary_series(summary_payload)
        return self._sum_window_days(series=series, days=days, offset_days=0)

    def _summary_growth(self, summary_payload: dict[str, Any] | None, days: int) -> float | None:
        if not summary_payload:
            return None
        if days == 30:
            pct = _safe_float(summary_payload.get("change_30dover30d"))
            if pct is not None:
                return pct / 100.0
            current_30d = _safe_float(summary_payload.get("total30d"))
            prev_30d = _safe_float(summary_payload.get("total60dto30d"))
            if current_30d is not None and prev_30d and prev_30d > 0:
                return (current_30d / prev_30d) - 1.0

        series = self._summary_series(summary_payload)
        current = self._sum_window_days(series=series, days=days, offset_days=0)
        previous = self._sum_window_days(series=series, days=days, offset_days=days)
        if current is None or previous is None or previous <= 0:
            return None
        return (current / previous) - 1.0

    def _tvl_growth(self, *, raw_tvl: Any, days: int) -> float | None:
        if not isinstance(raw_tvl, list) or not raw_tvl:
            return None
        series: list[tuple[int, float]] = []
        for row in raw_tvl:
            if not isinstance(row, dict):
                continue
            ts = row.get("date")
            val = _safe_float(row.get("totalLiquidityUSD"))
            if not isinstance(ts, (int, float)) or val is None:
                continue
            series.append((int(ts), val))
        series.sort(key=lambda x: x[0])
        if len(series) < 2:
            return None
        now_ts, now_val = series[-1]
        if now_val <= 0:
            return None
        target_ts = now_ts - (days * 86400)
        past_candidates = [value for ts, value in series if ts <= target_ts]
        if not past_candidates:
            return None
        past_val = past_candidates[-1]
        if past_val <= 0:
            return None
        return (now_val / past_val) - 1.0

    def _pick_growth(
        self,
        *,
        volume_growth: float | None,
        revenue_growth: float | None,
        fees_growth: float | None,
        tvl_growth: float | None,
    ) -> tuple[float | None, str | None]:
        if volume_growth is not None:
            return volume_growth, "volume"
        if revenue_growth is not None:
            return revenue_growth, "revenue"
        if fees_growth is not None:
            return fees_growth, "fees"
        if tvl_growth is not None:
            return tvl_growth, "tvl"
        return None, None

    def _normalize_percent_ratio(self, value: Any) -> float | None:
        numeric = _safe_float(value)
        if numeric is None:
            return None
        if -5.0 <= numeric <= 5.0:
            return numeric
        return numeric / 100.0

    async def _resolve_yields(
        self,
        *,
        target_name: str,
    ) -> tuple[list[dict[str, Any]], float | None, float | None, float | None]:
        normalized_target = target_name.strip().lower()
        if not normalized_target:
            return [], None, None, None

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get("https://yields.llama.fi/pools")
                resp.raise_for_status()
                pools = (resp.json() or {}).get("data") or []
        except Exception:
            return [], None, None, None

        filtered: list[dict[str, Any]] = []
        for pool in pools:
            project = str(pool.get("project") or "").strip().lower()
            if not project:
                continue
            if len(normalized_target) <= 4:
                if project != normalized_target and not project.startswith(f"{normalized_target}-"):
                    continue
            elif normalized_target not in project:
                continue

            tvl = _safe_float(pool.get("tvlUsd"))
            if tvl is None or tvl < 500_000:
                continue
            filtered.append(pool)

        filtered.sort(key=lambda row: float(row.get("tvlUsd") or 0), reverse=True)
        top = filtered[:5]
        if not top:
            return [], None, None, None

        top_yields: list[dict[str, Any]] = []
        apy_values: list[float] = []
        supply_apy_values: list[float] = []
        borrow_apy_values: list[float] = []
        for row in top:
            apy = _safe_float(row.get("apy"))
            if apy is not None:
                apy_values.append(apy)
            apy_supply = _safe_float(row.get("apyBase"))
            if apy_supply is None:
                apy_supply = apy
            if apy_supply is not None:
                supply_apy_values.append(apy_supply)
            apy_borrow = _safe_float(row.get("apyBaseBorrow") or row.get("apyBorrow"))
            if apy_borrow is not None:
                borrow_apy_values.append(apy_borrow)
            top_yields.append(
                {
                    "symbol": row.get("symbol"),
                    "chain": row.get("chain"),
                    "apy": apy,
                    "apy_supply": apy_supply,
                    "apy_borrow": apy_borrow,
                    "tvl_usd": _safe_float(row.get("tvlUsd")),
                    "total_supply_usd": _safe_float(row.get("totalSupplyUsd")),
                    "total_borrow_usd": _safe_float(row.get("totalBorrowUsd")),
                    "stablecoin": bool(row.get("stablecoin")),
                    "project": row.get("project"),
                }
            )

        avg_apy = (sum(apy_values) / len(apy_values)) if apy_values else None
        avg_supply_apy = (sum(supply_apy_values) / len(supply_apy_values)) if supply_apy_values else None
        avg_borrow_apy = (sum(borrow_apy_values) / len(borrow_apy_values)) if borrow_apy_values else None
        return top_yields[:3], avg_apy, avg_supply_apy, avg_borrow_apy

    async def _resolve_competitors(
        self,
        *,
        category: str,
        target_slug: str,
        target_name: str,
    ) -> list[dict[str, Any]]:
        if not category:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(f"{self.base_url}/protocols")
                resp.raise_for_status()
                protocols = resp.json()
        except Exception:
            return []

        category_l = category.strip().lower()
        same_category: list[dict[str, Any]] = []
        for row in protocols:
            cat = str(row.get("category") or "").strip().lower()
            tvl = _safe_float(row.get("tvl"))
            if cat == category_l and tvl is not None and tvl > 10_000:
                same_category.append(row)
        if not same_category:
            return []

        same_category.sort(key=lambda row: float(row.get("tvl") or 0), reverse=True)

        fees_map = await self._fetch_fees_overview_index()
        target_slug_l = target_slug.strip().lower()
        target_name_l = target_name.strip().lower()
        max_universe = 60
        competitors: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        target_present = False

        def _row_key(name: str, slug: str) -> str:
            return slug.strip().lower() or name.strip().lower()

        def _to_competitor(row: dict[str, Any], *, tvl_rank: int) -> dict[str, Any]:
            name = str(row.get("name") or "")
            slug = str(row.get("slug") or "")
            slug_l = slug.strip().lower()
            name_l = name.strip().lower()
            is_target = slug_l == target_slug_l or (name_l and name_l == target_name_l)
            fees_row = fees_map.get(slug_l) or fees_map.get(name_l) or {}
            return {
                "name": name,
                "slug": slug,
                "tvl": _safe_float(row.get("tvl")),
                "tvl_rank": tvl_rank,
                "change_1d": _safe_float(row.get("change_1d")),
                "change_7d": _safe_float(row.get("change_7d")),
                "fees_24h": _safe_float(row.get("total24h") or row.get("fees_24h") or row.get("dailyFees") or fees_row.get("fees_24h")),
                "fees_30d": _safe_float(row.get("total30d") or fees_row.get("fees_30d")),
                "fees_1y": _safe_float(row.get("total1y") or fees_row.get("fees_1y")),
                "revenue_24h": _safe_float(row.get("revenue_24h") or row.get("dailyRevenue") or fees_row.get("revenue_24h")),
                "revenue_30d": _safe_float(row.get("revenue_30d") or fees_row.get("revenue_30d")),
                "revenue_1y": _safe_float(row.get("revenue_1y") or fees_row.get("revenue_1y")),
                "growth_30d": self._normalize_percent_ratio(
                    row.get("change_30dover30d")
                    or fees_row.get("revenue_growth_30d")
                    or fees_row.get("fees_growth_30d")
                ),
                # Not available consistently from current public endpoints.
                "borrowed_usd": None,
                "utilization_rate": None,
                "avg_apy": None,
                "is_target": is_target,
            }

        for idx, row in enumerate(same_category, start=1):
            if idx > max_universe:
                break
            candidate = _to_competitor(row, tvl_rank=idx)
            key = _row_key(candidate["name"], candidate["slug"])
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            if candidate["is_target"]:
                target_present = True
            competitors.append(candidate)

        if not target_present:
            for idx, row in enumerate(same_category[max_universe:], start=max_universe + 1):
                candidate = _to_competitor(row, tvl_rank=idx)
                key = _row_key(candidate["name"], candidate["slug"])
                if not candidate["is_target"] or not key or key in seen_keys:
                    continue
                competitors.append(candidate)
                break

        def _build_rank(metric: str, descending: bool = True) -> dict[str, int]:
            rank_rows = [row for row in competitors if isinstance(row.get(metric), (int, float))]
            rank_rows.sort(key=lambda row: float(row.get(metric) or 0), reverse=descending)
            out: dict[str, int] = {}
            for idx, row in enumerate(rank_rows, start=1):
                out[_row_key(str(row.get("name") or ""), str(row.get("slug") or ""))] = idx
            return out

        fees30_rank = _build_rank("fees_30d", descending=True)
        revenue30_rank = _build_rank("revenue_30d", descending=True)
        growth30_rank = _build_rank("growth_30d", descending=True)
        for row in competitors:
            key = _row_key(str(row.get("name") or ""), str(row.get("slug") or ""))
            row["fees_30d_rank"] = fees30_rank.get(key)
            row["revenue_30d_rank"] = revenue30_rank.get(key)
            row["growth_30d_rank"] = growth30_rank.get(key)

        return competitors

    async def _resolve_dex_competitors(
        self,
        *,
        category: str,
        target_slug: str,
        target_name: str,
    ) -> list[dict[str, Any]]:
        if not category:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(f"{self.base_url}/protocols")
                resp.raise_for_status()
                protocols = resp.json()
        except Exception:
            return []

        category_l = category.strip().lower()
        if "dex" not in category_l and "swap" not in category_l and "amm" not in category_l:
            return []

        dex_rows: list[dict[str, Any]] = []
        for row in protocols:
            cat = str(row.get("category") or "").strip().lower()
            tvl = _safe_float(row.get("tvl"))
            if "dex" in cat and tvl is not None and tvl > 10_000:
                dex_rows.append(row)
        if not dex_rows:
            return []

        dex_rows.sort(key=lambda row: float(row.get("tvl") or 0.0), reverse=True)
        max_universe = 15
        universe_rows = dex_rows[:max_universe]
        fees_map = await self._fetch_fees_overview_index()

        target_slug_l = target_slug.strip().lower()
        target_name_l = target_name.strip().lower()

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            sem = asyncio.Semaphore(8)

            async def _fetch_row_volume(row_slug: str) -> tuple[float | None, float | None, float | None, float | None]:
                if not row_slug:
                    return None, None, None, None
                try:
                    async with sem:
                        resp = await client.get(f"{self.base_url}/summary/dexs/{row_slug}")
                except Exception:
                    return None, None, None, None
                if resp.status_code != 200:
                    return None, None, None, None
                try:
                    summary = resp.json() or {}
                except Exception:
                    return None, None, None, None
                volume_30d = self._summary_total(summary, 30)
                volume_90d = self._summary_total(summary, 90)
                volume_1y = self._summary_total(summary, 365)
                volume_growth_30d = self._summary_growth(summary, 30)
                return volume_30d, volume_90d, volume_1y, volume_growth_30d

            tasks = []
            for row in universe_rows:
                row_slug = str(row.get("slug") or "").strip().lower()
                tasks.append(_fetch_row_volume(row_slug))
            volume_results = await asyncio.gather(*tasks, return_exceptions=True)

        competitors: list[dict[str, Any]] = []
        for idx, row in enumerate(universe_rows, start=1):
            row_slug = str(row.get("slug") or "").strip()
            row_name = str(row.get("name") or "").strip()
            slug_l = row_slug.lower()
            name_l = row_name.lower()
            fees_row = fees_map.get(slug_l) or fees_map.get(name_l) or {}

            volume_30d = None
            volume_90d = None
            volume_1y = None
            volume_growth_30d = None
            loaded = volume_results[idx - 1]
            if isinstance(loaded, tuple) and len(loaded) == 4:
                volume_30d, volume_90d, volume_1y, volume_growth_30d = loaded

            fees_30d = _safe_float(fees_row.get("fees_30d"))
            revenue_30d = _safe_float(fees_row.get("revenue_30d"))
            growth_30d = (
                volume_growth_30d
                if volume_growth_30d is not None
                else self._normalize_percent_ratio(
                    fees_row.get("revenue_growth_30d") or fees_row.get("fees_growth_30d")
                )
            )
            is_target = slug_l == target_slug_l or (name_l and name_l == target_name_l)

            competitors.append(
                {
                    "name": row_name,
                    "slug": row_slug,
                    "is_target": is_target,
                    "tvl": _safe_float(row.get("tvl")),
                    "tvl_rank": idx,
                    "dex_volume_30d": volume_30d,
                    "dex_volume_90d": volume_90d,
                    "dex_volume_1y": volume_1y,
                    "fees_30d": fees_30d,
                    "revenue_30d": revenue_30d,
                    "growth_30d": growth_30d,
                }
            )

        def _row_key(name: str, slug: str) -> str:
            return slug.strip().lower() or name.strip().lower()

        def _build_rank(metric: str, descending: bool = True) -> dict[str, int]:
            rank_rows = [row for row in competitors if isinstance(row.get(metric), (int, float))]
            rank_rows.sort(key=lambda row: float(row.get(metric) or 0.0), reverse=descending)
            out: dict[str, int] = {}
            for idx, row in enumerate(rank_rows, start=1):
                out[_row_key(str(row.get("name") or ""), str(row.get("slug") or ""))] = idx
            return out

        volume30_rank = _build_rank("dex_volume_30d", descending=True)
        fees30_rank = _build_rank("fees_30d", descending=True)
        revenue30_rank = _build_rank("revenue_30d", descending=True)
        growth30_rank = _build_rank("growth_30d", descending=True)
        for row in competitors:
            key = _row_key(str(row.get("name") or ""), str(row.get("slug") or ""))
            row["dex_volume_30d_rank"] = volume30_rank.get(key)
            row["fees_30d_rank"] = fees30_rank.get(key)
            row["revenue_30d_rank"] = revenue30_rank.get(key)
            row["growth_30d_rank"] = growth30_rank.get(key)

        return competitors

    def _is_lending_sector(
        self,
        *,
        category: str | None,
        borrowed_usd_hint: float | None = None,
    ) -> bool:
        if borrowed_usd_hint is not None:
            return True
        category_l = str(category or "").strip().lower()
        return any(word in category_l for word in ("lending", "borrow", "loan", "money market", "cdp"))

    def _is_dex_spot_sector(self, *, category: str | None) -> bool:
        category_l = str(category or "").strip().lower()
        return any(word in category_l for word in ("dex", "swap", "exchange", "amm"))

    def _is_perp_sector(
        self,
        *,
        category: str | None,
        target: dict[str, Any],
        payload: dict[str, Any],
    ) -> bool:
        text = " ".join(
            [
                str(category or ""),
                str(payload.get("category") or ""),
                str(payload.get("name") or ""),
                str(payload.get("slug") or ""),
                str(target.get("category") or ""),
                str((target.get("metadata") or {}).get("sector") or ""),
            ]
        ).lower()
        return any(word in text for word in ("perp", "perpetual", "derivative", "futures"))

    def _is_oracle_sector(
        self,
        *,
        category: str | None,
        target: dict[str, Any],
        payload: dict[str, Any],
        target_slug: str,
    ) -> bool:
        text = " ".join(
            [
                str(category or ""),
                str(payload.get("category") or ""),
                str(payload.get("name") or ""),
                str(payload.get("id") or ""),
                str(target.get("category") or ""),
                str((target.get("metadata") or {}).get("sector") or ""),
                str(target_slug or ""),
            ]
        ).lower()
        keywords = (
            "oracle",
            "price feed",
            "data feed",
            "vrf",
            "entropy",
            "chainlink",
            "pyth",
            "api3",
            "redstone",
            "band",
            "supra",
            "witnet",
            "orcfax",
            "geodnet",
        )
        return any(word in text for word in keywords)

    def _is_l1_l2_sector(
        self,
        *,
        category: str | None,
        target: dict[str, Any],
    ) -> bool:
        text = " ".join(
            [
                str(category or ""),
                str(target.get("category") or ""),
                str((target.get("metadata") or {}).get("sector") or ""),
            ]
        ).lower()
        return any(
            word in text
            for word in ("l1", "l2", "layer 1", "layer 2", "chain", "mainnet", "rollup", "blockchain")
        )

    def _chain_slugify(self, value: str) -> str:
        return value.strip().lower().replace(" ", "-").replace("_", "-")

    def _chain_endpoint_candidates(self, *, chain_name: str, chain_slug: str | None = None) -> list[str]:
        aliases = {
            "binance": ["binance", "bsc", "bnb-chain"],
            "bnb-chain": ["binance", "bsc", "bnb-chain"],
            "bnb": ["binance", "bsc", "bnb-chain"],
            "optimism": ["optimism", "op-mainnet"],
            "xdai": ["xdai", "gnosis"],
            "gnosis": ["gnosis", "xdai"],
        }
        values: list[str] = []
        for item in (chain_slug or "", chain_name, self._chain_slugify(chain_name)):
            item = str(item or "").strip()
            if item and item not in values:
                values.append(item)
        alias_values = aliases.get(self._chain_slugify(chain_name), [])
        for item in alias_values:
            if item and item not in values:
                values.append(item)
        return values

    async def _fetch_chains(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(f"{self.base_url}/chains")
            if resp.status_code != 200:
                return []
            payload = resp.json() or []
            return payload if isinstance(payload, list) else []
        except Exception:
            return []

    async def _resolve_l1_l2_chain_identity(
        self,
        *,
        target: dict[str, Any],
        payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        chains = await self._fetch_chains()
        if not chains:
            return None

        candidates = [
            str((payload or {}).get("name") or "").strip(),
            str((payload or {}).get("slug") or "").strip(),
            str(target.get("name") or "").strip(),
            str(target.get("ticker") or "").strip(),
            str(target.get("category") or "").strip(),
        ]
        norm_candidates = {self._chain_slugify(item) for item in candidates if item}

        def _match(row: dict[str, Any]) -> bool:
            row_name = str(row.get("name") or "").strip()
            row_symbol = str(row.get("tokenSymbol") or "").strip()
            row_norm = self._chain_slugify(row_name)
            if row_norm in norm_candidates:
                return True
            if row_symbol and self._chain_slugify(row_symbol) in norm_candidates:
                return True
            return False

        for row in chains:
            if _match(row):
                return {
                    "name": str(row.get("name") or ""),
                    "slug": self._chain_slugify(str(row.get("name") or "")),
                    "token_symbol": str(row.get("tokenSymbol") or "").strip() or None,
                    "tvl": _safe_float(row.get("tvl")),
                }
        return None

    async def _fetch_chain_summary(
        self,
        *,
        namespace: str,
        chain_name: str,
        chain_slug: str,
    ) -> dict[str, Any] | None:
        candidates = self._chain_endpoint_candidates(chain_name=chain_name, chain_slug=chain_slug)
        for candidate in candidates:
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.get(f"{self.base_url}/summary/{namespace}/{candidate}")
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            try:
                payload = resp.json() or {}
            except Exception:
                continue
            if isinstance(payload, dict) and (payload.get("totalDataChart") or payload.get("total24h") is not None):
                return payload
        return None

    async def _fetch_chain_overview(
        self,
        *,
        namespace: str,
        chain_name: str,
        chain_slug: str,
    ) -> dict[str, Any] | None:
        candidates = self._chain_endpoint_candidates(chain_name=chain_name, chain_slug=chain_slug)
        for candidate in candidates:
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.get(f"{self.base_url}/overview/{namespace}/{candidate}")
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            try:
                payload = resp.json() or {}
            except Exception:
                continue
            if isinstance(payload, dict):
                return payload
        return None

    async def _fetch_chain_tvl_series(
        self,
        *,
        chain_name: str,
        chain_slug: str,
    ) -> list[tuple[int, float]]:
        candidates = [chain_name] + self._chain_endpoint_candidates(chain_name=chain_name, chain_slug=chain_slug)
        for candidate in candidates:
            if not candidate:
                continue
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.get(f"{self.base_url}/v2/historicalChainTvl/{candidate}")
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            try:
                rows = resp.json() or []
            except Exception:
                continue
            series = self._dict_series(
                rows=rows,
                value_keys=("tvl", "totalLiquidityUSD", "totalLiquidity"),
            )
            if series:
                return series
        return []

    async def _fetch_stablecoin_chart(
        self,
        *,
        chain_name: str,
        chain_slug: str,
    ) -> list[tuple[int, float]]:
        candidates = [chain_name] + self._chain_endpoint_candidates(chain_name=chain_name, chain_slug=chain_slug)
        for candidate in candidates:
            if not candidate:
                continue
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.get(f"https://stablecoins.llama.fi/stablecoincharts/{candidate}")
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            try:
                rows = resp.json() or []
            except Exception:
                continue
            series = self._dict_series(
                rows=rows,
                value_keys=("totalCirculatingUSD", "totalCirculating"),
            )
            if series:
                return series
        return []

    async def _fetch_stablecoin_supply_index(self) -> dict[str, float]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get("https://stablecoins.llama.fi/stablecoinchains")
            if resp.status_code != 200:
                return {}
            rows = resp.json() or []
        except Exception:
            return {}
        out: dict[str, float] = {}
        if not isinstance(rows, list):
            return out
        for row in rows:
            name = str((row or {}).get("name") or "").strip().lower()
            value = self._coerce_amount((row or {}).get("totalCirculatingUSD"))
            if name and value is not None:
                out[name] = value
        return out

    def _dict_series(
        self,
        *,
        rows: Any,
        value_keys: tuple[str, ...],
    ) -> list[tuple[int, float]]:
        if not isinstance(rows, list):
            return []
        out: list[tuple[int, float]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = row.get("date")
            if not isinstance(ts, (int, float)):
                continue
            val: float | None = None
            for key in value_keys:
                val = self._coerce_amount(row.get(key))
                if val is not None:
                    break
            if val is None:
                continue
            out.append((int(ts), val))
        out.sort(key=lambda item: item[0])
        return out

    def _coerce_amount(self, value: Any) -> float | None:
        numeric = _safe_float(value)
        if numeric is not None:
            return numeric
        if isinstance(value, dict):
            total = 0.0
            has_numeric = False
            for item in value.values():
                item_numeric = _safe_float(item)
                if item_numeric is None:
                    continue
                has_numeric = True
                total += item_numeric
            if has_numeric:
                return total
        return None

    def _series_growth_ratio(self, *, series: list[tuple[int, float]], days: int) -> float | None:
        if len(series) < 2:
            return None
        current = series[-1][1]
        past = self._series_value_days_ago(series, days)
        if current is None or past is None or past <= 0:
            return None
        return (current / past) - 1.0

    async def _resolve_l1_l2_metrics(
        self,
        *,
        chain_name: str,
        chain_slug: str,
        chain_tvl_hint: float | None,
        fees_30d: float | None,
        fees_90d: float | None,
        fees_1y: float | None,
        revenue_30d: float | None,
        revenue_90d: float | None,
        revenue_1y: float | None,
        growth_30d: float | None,
        growth_90d: float | None,
        growth_1y: float | None,
        annualized_fees: float | None,
        annualized_revenue: float | None,
    ) -> dict[str, Any]:
        active_summary = await self._fetch_chain_summary(
            namespace="active-users",
            chain_name=chain_name,
            chain_slug=chain_slug,
        )
        fees_summary = await self._fetch_fee_summary(
            target_slug=chain_slug,
            target_name=chain_name,
            data_type="dailyFees",
        )
        revenue_summary = await self._fetch_fee_summary(
            target_slug=chain_slug,
            target_name=chain_name,
            data_type="dailyRevenue",
        )
        chain_fees_overview = await self._fetch_chain_overview(
            namespace="fees",
            chain_name=chain_name,
            chain_slug=chain_slug,
        )
        tvl_series = await self._fetch_chain_tvl_series(chain_name=chain_name, chain_slug=chain_slug)
        stable_series = await self._fetch_stablecoin_chart(chain_name=chain_name, chain_slug=chain_slug)

        active_addresses_24h = self._summary_total(active_summary, 1)
        active_addresses_30d = self._summary_total(active_summary, 30)
        active_addresses_90d = self._summary_total(active_summary, 90)
        active_addresses_1y = self._summary_total(active_summary, 365)
        active_growth_30d = self._summary_growth(active_summary, 30)
        active_growth_90d = self._summary_growth(active_summary, 90)
        active_growth_1y = self._summary_growth(active_summary, 365)

        fees_30d_val = fees_30d if fees_30d is not None else self._summary_total(fees_summary, 30)
        fees_90d_val = fees_90d if fees_90d is not None else self._summary_total(fees_summary, 90)
        fees_1y_val = fees_1y if fees_1y is not None else self._summary_total(fees_summary, 365)
        revenue_30d_val = revenue_30d if revenue_30d is not None else self._summary_total(revenue_summary, 30)
        revenue_90d_val = revenue_90d if revenue_90d is not None else self._summary_total(revenue_summary, 90)
        revenue_1y_val = revenue_1y if revenue_1y is not None else self._summary_total(revenue_summary, 365)

        fees_growth_30d = self._summary_growth(fees_summary, 30)
        fees_growth_90d = self._summary_growth(fees_summary, 90)
        fees_growth_1y = self._summary_growth(fees_summary, 365)
        revenue_growth_30d = self._summary_growth(revenue_summary, 30)
        revenue_growth_90d = self._summary_growth(revenue_summary, 90)
        revenue_growth_1y = self._summary_growth(revenue_summary, 365)

        ecosystem_tvl_series = tvl_series[-1][1] if tvl_series else None
        ecosystem_tvl = chain_tvl_hint if chain_tvl_hint is not None else ecosystem_tvl_series
        ecosystem_tvl_growth_30d = self._series_growth_ratio(series=tvl_series, days=30)
        ecosystem_tvl_growth_90d = self._series_growth_ratio(series=tvl_series, days=90)
        ecosystem_tvl_growth_1y = self._series_growth_ratio(series=tvl_series, days=365)

        stablecoin_supply_usd = stable_series[-1][1] if stable_series else None
        if stablecoin_supply_usd is None:
            stable_index = await self._fetch_stablecoin_supply_index()
            stablecoin_supply_usd = _safe_float(
                stable_index.get(chain_name.strip().lower())
                or stable_index.get(chain_slug.strip().lower())
            )
        stablecoin_supply_growth_30d = self._series_growth_ratio(series=stable_series, days=30)

        protocols = (chain_fees_overview or {}).get("protocols") or []
        app_count_30d = 0.0
        for row in protocols:
            if _safe_float((row or {}).get("total30d")):
                app_count_30d += 1.0
        if app_count_30d <= 0:
            app_count_30d = None

        def _pick(primary: float | None, fallback: float | None) -> float | None:
            return primary if primary is not None else fallback

        growth_30d_val = _pick(active_growth_30d, _pick(revenue_growth_30d, _pick(fees_growth_30d, ecosystem_tvl_growth_30d)))
        growth_90d_val = _pick(active_growth_90d, _pick(revenue_growth_90d, _pick(fees_growth_90d, ecosystem_tvl_growth_90d)))
        growth_1y_val = _pick(active_growth_1y, _pick(revenue_growth_1y, _pick(fees_growth_1y, ecosystem_tvl_growth_1y)))

        return {
            "chain_name": chain_name,
            "chain_slug": chain_slug,
            "active_addresses_24h": active_addresses_24h,
            "active_addresses_30d": active_addresses_30d,
            "active_addresses_90d": active_addresses_90d,
            "active_addresses_1y": active_addresses_1y,
            "transactions_24h": None,
            "transactions_30d": None,
            "transactions_90d": None,
            "transactions_1y": None,
            "fees_30d": fees_30d_val,
            "fees_90d": fees_90d_val,
            "fees_1y": fees_1y_val,
            "revenue_30d": revenue_30d_val,
            "revenue_90d": revenue_90d_val,
            "revenue_1y": revenue_1y_val,
            "stablecoin_supply_usd": stablecoin_supply_usd,
            "stablecoin_supply_growth_30d": stablecoin_supply_growth_30d,
            "ecosystem_tvl": ecosystem_tvl,
            "ecosystem_tvl_growth_30d": ecosystem_tvl_growth_30d,
            "ecosystem_tvl_growth_90d": ecosystem_tvl_growth_90d,
            "ecosystem_tvl_growth_1y": ecosystem_tvl_growth_1y,
            "app_count_30d": app_count_30d,
            "growth_30d": growth_30d_val if growth_30d_val is not None else growth_30d,
            "growth_90d": growth_90d_val if growth_90d_val is not None else growth_90d,
            "growth_1y": growth_1y_val if growth_1y_val is not None else growth_1y,
            "annualized_fees": annualized_fees if annualized_fees is not None else (
                (fees_30d_val * 365.0 / 30.0) if fees_30d_val is not None else None
            ),
            "annualized_revenue": annualized_revenue if annualized_revenue is not None else (
                (revenue_30d_val * 365.0 / 30.0) if revenue_30d_val is not None else None
            ),
        }

    async def _resolve_l1_l2_competitors(
        self,
        *,
        target_chain_name: str,
        target_chain_slug: str,
        max_universe: int,
    ) -> list[dict[str, Any]]:
        chains = await self._fetch_chains()
        if not chains:
            return []
        chains = [row for row in chains if _safe_float(row.get("tvl")) and _safe_float(row.get("tvl")) > 50_000_000]
        chains.sort(key=lambda row: float(row.get("tvl") or 0.0), reverse=True)
        universe = chains[:max_universe]

        target_norm_name = self._chain_slugify(target_chain_name)
        target_norm_slug = self._chain_slugify(target_chain_slug)
        has_target = False
        for row in universe:
            name_l = self._chain_slugify(str(row.get("name") or ""))
            if name_l in {target_norm_name, target_norm_slug}:
                has_target = True
                break
        if not has_target:
            for row in chains[max_universe:]:
                name_l = self._chain_slugify(str(row.get("name") or ""))
                if name_l in {target_norm_name, target_norm_slug}:
                    universe.append(row)
                    break

        stable_index = await self._fetch_stablecoin_supply_index()
        sem = asyncio.Semaphore(6)

        async def _load(row: dict[str, Any], tvl_rank: int) -> dict[str, Any]:
            chain_name = str(row.get("name") or "")
            chain_slug = self._chain_slugify(chain_name)
            async with sem:
                active_summary = await self._fetch_chain_summary(
                    namespace="active-users",
                    chain_name=chain_name,
                    chain_slug=chain_slug,
                )
                fees_summary = await self._fetch_fee_summary(
                    target_slug=chain_slug,
                    target_name=chain_name,
                    data_type="dailyFees",
                )
                revenue_summary = await self._fetch_fee_summary(
                    target_slug=chain_slug,
                    target_name=chain_name,
                    data_type="dailyRevenue",
                )
                chain_fees_overview = await self._fetch_chain_overview(
                    namespace="fees",
                    chain_name=chain_name,
                    chain_slug=chain_slug,
                )
            active_30d = self._summary_total(active_summary, 30)
            fees_30d = self._summary_total(fees_summary, 30)
            revenue_30d = self._summary_total(revenue_summary, 30)
            active_growth_30d = self._summary_growth(active_summary, 30)
            revenue_growth_30d = self._summary_growth(revenue_summary, 30)
            fees_growth_30d = self._summary_growth(fees_summary, 30)
            growth_30d = (
                active_growth_30d
                if active_growth_30d is not None
                else (revenue_growth_30d if revenue_growth_30d is not None else fees_growth_30d)
            )
            protocols = (chain_fees_overview or {}).get("protocols") or []
            app_count_30d = 0.0
            for item in protocols:
                if _safe_float((item or {}).get("total30d")):
                    app_count_30d += 1.0
            if app_count_30d <= 0:
                app_count_30d = None
            name_l = chain_name.strip().lower()
            stablecoin_supply_usd = _safe_float(stable_index.get(name_l))
            is_target = self._chain_slugify(chain_name) in {target_norm_name, target_norm_slug}
            return {
                "name": chain_name,
                "slug": chain_slug,
                "is_target": is_target,
                "ecosystem_tvl": _safe_float(row.get("tvl")),
                "ecosystem_tvl_rank": tvl_rank,
                "active_addresses_30d": active_30d,
                "fees_30d": fees_30d,
                "revenue_30d": revenue_30d,
                "stablecoin_supply_usd": stablecoin_supply_usd,
                "growth_30d": growth_30d,
                "app_count_30d": app_count_30d,
                "transactions_30d": None,
            }

        tasks = [_load(row, idx) for idx, row in enumerate(universe, start=1)]
        loaded = await asyncio.gather(*tasks, return_exceptions=True)
        competitors: list[dict[str, Any]] = []
        for item in loaded:
            if isinstance(item, dict):
                competitors.append(item)

        def _row_key(name: str, slug: str) -> str:
            return slug.strip().lower() or name.strip().lower()

        def _build_rank(metric: str, descending: bool = True) -> dict[str, int]:
            rank_rows = [row for row in competitors if isinstance(row.get(metric), (int, float))]
            rank_rows.sort(key=lambda row: float(row.get(metric) or 0.0), reverse=descending)
            out: dict[str, int] = {}
            for idx, row in enumerate(rank_rows, start=1):
                out[_row_key(str(row.get("name") or ""), str(row.get("slug") or ""))] = idx
            return out

        active_rank = _build_rank("active_addresses_30d", descending=True)
        fees_rank = _build_rank("fees_30d", descending=True)
        revenue_rank = _build_rank("revenue_30d", descending=True)
        stable_rank = _build_rank("stablecoin_supply_usd", descending=True)
        growth_rank = _build_rank("growth_30d", descending=True)
        app_rank = _build_rank("app_count_30d", descending=True)
        for row in competitors:
            key = _row_key(str(row.get("name") or ""), str(row.get("slug") or ""))
            row["active_addresses_30d_rank"] = active_rank.get(key)
            row["fees_30d_rank"] = fees_rank.get(key)
            row["revenue_30d_rank"] = revenue_rank.get(key)
            row["stablecoin_supply_rank"] = stable_rank.get(key)
            row["growth_30d_rank"] = growth_rank.get(key)
            row["app_count_30d_rank"] = app_rank.get(key)
            row["transactions_30d_rank"] = None
        return competitors

    async def _fetch_open_interest_overview(self) -> dict[str, Any] | None:
        params = {
            "excludeTotalDataChart": "true",
            "excludeTotalDataChartBreakdown": "true",
        }
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.get(f"{self.base_url}/overview/open-interest", params=params)
            except Exception:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            if resp.status_code != 200:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            try:
                payload = resp.json() or {}
            except Exception:
                return None
            if isinstance(payload, dict):
                return payload
        return None

    def _perp_slugify(self, value: str) -> str:
        return value.strip().lower().replace(" ", "-").replace("_", "-")

    def _perp_summary_slug_candidates(
        self,
        *,
        slug: str | None,
        name: str | None,
        parent_slug: str | None = None,
    ) -> list[str]:
        values: list[str] = []
        for raw in (slug or "", parent_slug or "", name or "", self._perp_slugify(name or "")):
            item = str(raw or "").strip().lower()
            if item and item not in values:
                values.append(item)

        expanded: list[str] = []
        for item in values:
            expanded.append(item)
            for suffix in ("-perps", "-perp", "-v1-perps", "-v2-perps", "-v3-perps", "-v4-perps"):
                if item.endswith(suffix):
                    short = item[: -len(suffix)]
                    if short:
                        expanded.append(short)
        out: list[str] = []
        for item in expanded:
            if item and item not in out:
                out.append(item)
        return out

    async def _fetch_fee_summary_by_candidates(
        self,
        *,
        candidates: list[str],
        data_type: str,
    ) -> dict[str, Any] | None:
        for candidate in candidates:
            if not candidate:
                continue
            summary = await self._fetch_fee_summary(
                target_slug=candidate,
                target_name=candidate,
                data_type=data_type,
            )
            if summary:
                return summary
        return None

    async def _fetch_active_users_summary_by_candidates(
        self,
        *,
        candidates: list[str],
    ) -> dict[str, Any] | None:
        for candidate in candidates:
            if not candidate:
                continue
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.get(f"{self.base_url}/summary/active-users/{candidate}")
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            try:
                payload = resp.json() or {}
            except Exception:
                continue
            if isinstance(payload, dict) and (
                payload.get("totalDataChart") or payload.get("total30d") is not None
            ):
                return payload
        return None

    def _match_perp_oi_row(
        self,
        *,
        rows: list[dict[str, Any]],
        payload: dict[str, Any],
        target: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not rows:
            return None

        target_name = str(target.get("name") or "").strip().lower()
        target_slug = self._perp_slugify(str(payload.get("slug") or target.get("name") or ""))
        target_tokens = [x for x in target_name.replace("-", " ").split() if x]

        candidates = self._perp_summary_slug_candidates(
            slug=str(payload.get("slug") or ""),
            name=str(payload.get("name") or target.get("name") or ""),
            parent_slug=str(payload.get("parentProtocolSlug") or ""),
        )
        candidate_set = set(candidates)

        best_row: dict[str, Any] | None = None
        best_score: tuple[int, float] | None = None
        for row in rows:
            row_slug = self._perp_slugify(str(row.get("slug") or ""))
            row_name = str(row.get("name") or "").strip().lower()
            row_total30d = _safe_float(row.get("total30d")) or 0.0

            score = 0
            if row_slug and row_slug in candidate_set:
                score += 8
            if target_slug and row_slug and target_slug in row_slug:
                score += 3
            if target_name and row_name:
                if row_name == target_name:
                    score += 8
                elif target_name in row_name or row_name in target_name:
                    score += 4
            if target_tokens and row_name:
                overlap = sum(1 for token in target_tokens if token in row_name)
                score += overlap

            if score <= 0:
                continue
            candidate_score = (score, row_total30d)
            if best_score is None or candidate_score > best_score:
                best_score = candidate_score
                best_row = row

        if best_row is not None:
            return best_row

        rows_sorted = sorted(
            rows,
            key=lambda item: float(
                _safe_float(item.get("total30d")) or _safe_float(item.get("total24h")) or 0.0
            ),
            reverse=True,
        )
        return rows_sorted[0] if rows_sorted else None

    async def _resolve_perp_metrics(
        self,
        *,
        target: dict[str, Any],
        payload: dict[str, Any],
        fees_30d: float | None,
        fees_90d: float | None,
        fees_1y: float | None,
        revenue_30d: float | None,
        revenue_90d: float | None,
        revenue_1y: float | None,
        growth_30d: float | None,
        growth_90d: float | None,
        growth_1y: float | None,
        annualized_fees: float | None,
        annualized_revenue: float | None,
    ) -> dict[str, Any]:
        oi_overview = await self._fetch_open_interest_overview()
        oi_rows = list((oi_overview or {}).get("protocols") or [])
        oi_target = self._match_perp_oi_row(rows=oi_rows, payload=payload, target=target) or {}

        perp_slug = str(oi_target.get("slug") or payload.get("slug") or target.get("name") or "")
        perp_name = str(oi_target.get("name") or payload.get("name") or target.get("name") or "")
        parent_slug = str(payload.get("parentProtocolSlug") or "")
        summary_candidates = self._perp_summary_slug_candidates(
            slug=perp_slug,
            name=perp_name,
            parent_slug=parent_slug,
        )

        fees_summary = await self._fetch_fee_summary_by_candidates(
            candidates=summary_candidates,
            data_type="dailyFees",
        )
        revenue_summary = await self._fetch_fee_summary_by_candidates(
            candidates=summary_candidates,
            data_type="dailyRevenue",
        )
        protocol_revenue_summary = await self._fetch_fee_summary_by_candidates(
            candidates=summary_candidates,
            data_type="dailyProtocolRevenue",
        )
        active_users_summary = await self._fetch_active_users_summary_by_candidates(
            candidates=summary_candidates,
        )

        oi_24h = _safe_float(oi_target.get("total24h"))
        oi_30d = _safe_float(oi_target.get("total30d"))
        oi_1y = _safe_float(oi_target.get("total1y"))
        oi_growth_30d = self._normalize_percent_ratio(oi_target.get("change_30dover30d"))
        oi_total_30d = _safe_float((oi_overview or {}).get("total30d"))
        oi_share_30d = (
            (oi_30d / oi_total_30d)
            if oi_30d is not None and oi_total_30d and oi_total_30d > 0
            else None
        )

        fees_30d_val = self._summary_total(fees_summary, 30)
        fees_90d_val = self._summary_total(fees_summary, 90)
        fees_1y_val = self._summary_total(fees_summary, 365)
        revenue_30d_val = self._summary_total(revenue_summary, 30)
        revenue_90d_val = self._summary_total(revenue_summary, 90)
        revenue_1y_val = self._summary_total(revenue_summary, 365)
        protocol_revenue_30d = self._summary_total(protocol_revenue_summary, 30)

        fees_growth_30d = self._summary_growth(fees_summary, 30)
        fees_growth_90d = self._summary_growth(fees_summary, 90)
        fees_growth_1y = self._summary_growth(fees_summary, 365)
        revenue_growth_30d = self._summary_growth(revenue_summary, 30)
        revenue_growth_90d = self._summary_growth(revenue_summary, 90)
        revenue_growth_1y = self._summary_growth(revenue_summary, 365)

        active_users_30d = self._summary_total(active_users_summary, 30)

        def _pick(*values: float | None) -> float | None:
            for value in values:
                if value is not None:
                    return value
            return None

        fees_30d_final = _pick(fees_30d_val, fees_30d)
        fees_90d_final = _pick(fees_90d_val, fees_90d)
        fees_1y_final = _pick(fees_1y_val, fees_1y)
        revenue_30d_final = _pick(revenue_30d_val, revenue_30d)
        revenue_90d_final = _pick(revenue_90d_val, revenue_90d)
        revenue_1y_final = _pick(revenue_1y_val, revenue_1y)
        growth_30d_final = _pick(oi_growth_30d, revenue_growth_30d, fees_growth_30d, growth_30d)
        growth_90d_final = _pick(revenue_growth_90d, fees_growth_90d, growth_90d)
        growth_1y_final = _pick(revenue_growth_1y, fees_growth_1y, growth_1y)

        annualized_fees_final = (
            annualized_fees
            if annualized_fees is not None
            else ((fees_30d_final * 365.0 / 30.0) if fees_30d_final is not None else None)
        )
        annualized_revenue_final = (
            annualized_revenue
            if annualized_revenue is not None
            else ((revenue_30d_final * 365.0 / 30.0) if revenue_30d_final is not None else None)
        )

        # Derivatives volume endpoint is currently paid-gated on public API for this environment.
        perp_volume_30d = None

        return {
            "perp_name": perp_name,
            "perp_slug": perp_slug,
            "open_interest_usd": oi_24h,
            "open_interest_30d": oi_30d,
            "open_interest_1y": oi_1y,
            "open_interest_change_30d": oi_growth_30d,
            "open_interest_share_30d": oi_share_30d,
            "perp_volume_30d": perp_volume_30d,
            "fees_30d": fees_30d_final,
            "fees_90d": fees_90d_final,
            "fees_1y": fees_1y_final,
            "revenue_30d": revenue_30d_final,
            "revenue_90d": revenue_90d_final,
            "revenue_1y": revenue_1y_final,
            "protocol_revenue_30d": protocol_revenue_30d,
            "active_users_30d": active_users_30d,
            "growth_30d": growth_30d_final,
            "growth_90d": growth_90d_final,
            "growth_1y": growth_1y_final,
            "annualized_fees": annualized_fees_final,
            "annualized_revenue": annualized_revenue_final,
            "funding_rate": None,
            "liquidations_30d": None,
            "active_traders_30d": None,
            "market_depth_usd": None,
            "retention_30d": None,
            "insurance_fund_usd": None,
        }

    async def _resolve_perp_competitors(
        self,
        *,
        target_perp_slug: str,
        max_universe: int,
    ) -> list[dict[str, Any]]:
        oi_overview = await self._fetch_open_interest_overview()
        rows = list((oi_overview or {}).get("protocols") or [])
        if not rows:
            return []

        filtered = [
            row
            for row in rows
            if str(row.get("category") or "").strip().lower() == "derivatives"
            and (
                _safe_float(row.get("total24h")) is not None
                or _safe_float(row.get("total30d")) is not None
            )
        ]
        filtered.sort(
            key=lambda row: float(_safe_float(row.get("total24h")) or _safe_float(row.get("total30d")) or 0.0),
            reverse=True,
        )
        universe = filtered[:max_universe]

        target_slug_l = self._perp_slugify(target_perp_slug)
        if target_slug_l:
            has_target = any(self._perp_slugify(str(row.get("slug") or "")) == target_slug_l for row in universe)
            if not has_target:
                for row in filtered[max_universe:]:
                    if self._perp_slugify(str(row.get("slug") or "")) == target_slug_l:
                        universe.append(row)
                        break

        oi_total_30d = _safe_float((oi_overview or {}).get("total30d"))
        sem = asyncio.Semaphore(6)

        async def _load(row: dict[str, Any], oi_rank: int) -> dict[str, Any]:
            perp_name = str(row.get("name") or "")
            perp_slug = str(row.get("slug") or "")
            summary_candidates = self._perp_summary_slug_candidates(
                slug=perp_slug,
                name=perp_name,
                parent_slug="",
            )

            async with sem:
                fees_summary = await self._fetch_fee_summary_by_candidates(
                    candidates=summary_candidates,
                    data_type="dailyFees",
                )
                revenue_summary = await self._fetch_fee_summary_by_candidates(
                    candidates=summary_candidates,
                    data_type="dailyRevenue",
                )
                active_summary = await self._fetch_active_users_summary_by_candidates(
                    candidates=summary_candidates,
                )

            oi_24h = _safe_float(row.get("total24h"))
            oi_30d = _safe_float(row.get("total30d"))
            oi_share_30d = (
                (oi_30d / oi_total_30d)
                if oi_30d is not None and oi_total_30d and oi_total_30d > 0
                else None
            )
            growth_30d = self._normalize_percent_ratio(row.get("change_30dover30d"))

            return {
                "name": perp_name,
                "slug": perp_slug,
                "is_target": self._perp_slugify(perp_slug) == target_slug_l if target_slug_l else False,
                "open_interest_usd": oi_24h,
                "open_interest_30d": oi_30d,
                "open_interest_share_30d": oi_share_30d,
                "open_interest_rank": oi_rank,
                "perp_volume_30d": None,
                "fees_30d": self._summary_total(fees_summary, 30),
                "revenue_30d": self._summary_total(revenue_summary, 30),
                "active_users_30d": self._summary_total(active_summary, 30),
                "growth_30d": growth_30d,
                "funding_rate": None,
                "liquidations_30d": None,
            }

        tasks = [_load(row, idx) for idx, row in enumerate(universe, start=1)]
        loaded = await asyncio.gather(*tasks, return_exceptions=True)
        competitors: list[dict[str, Any]] = []
        for item in loaded:
            if isinstance(item, dict):
                competitors.append(item)

        def _row_key(name: str, slug: str) -> str:
            return slug.strip().lower() or name.strip().lower()

        def _build_rank(metric: str, descending: bool = True) -> dict[str, int]:
            rank_rows = [row for row in competitors if isinstance(row.get(metric), (int, float))]
            rank_rows.sort(key=lambda row: float(row.get(metric) or 0.0), reverse=descending)
            out: dict[str, int] = {}
            for idx, row in enumerate(rank_rows, start=1):
                out[_row_key(str(row.get("name") or ""), str(row.get("slug") or ""))] = idx
            return out

        oi_share_rank = _build_rank("open_interest_share_30d", descending=True)
        fees_rank = _build_rank("fees_30d", descending=True)
        revenue_rank = _build_rank("revenue_30d", descending=True)
        growth_rank = _build_rank("growth_30d", descending=True)
        active_rank = _build_rank("active_users_30d", descending=True)
        volume_rank = _build_rank("perp_volume_30d", descending=True)
        for row in competitors:
            key = _row_key(str(row.get("name") or ""), str(row.get("slug") or ""))
            row["open_interest_share_30d_rank"] = oi_share_rank.get(key)
            row["fees_30d_rank"] = fees_rank.get(key)
            row["revenue_30d_rank"] = revenue_rank.get(key)
            row["growth_30d_rank"] = growth_rank.get(key)
            row["active_users_30d_rank"] = active_rank.get(key)
            row["perp_volume_30d_rank"] = volume_rank.get(key)
        return competitors

    def _oracle_slugify(self, value: str) -> str:
        return value.strip().lower().replace(" ", "-").replace("_", "-")

    def _oracle_summary_slug_candidates(
        self,
        *,
        slug: str | None,
        name: str | None,
        parent_slug: str | None = None,
        protocol_id: str | None = None,
    ) -> list[str]:
        values: list[str] = []
        for raw in (slug or "", parent_slug or "", name or "", self._oracle_slugify(name or "")):
            item = str(raw or "").strip().lower()
            if item and item not in values:
                values.append(item)

        pid = str(protocol_id or "").strip().lower()
        if pid.startswith("parent#"):
            parent_item = pid.split("#", 1)[1].strip()
            if parent_item and parent_item not in values:
                values.append(parent_item)

        out: list[str] = []
        for item in values:
            if item and item not in out:
                out.append(item)
        return out

    def _summary_breakdown_chain_series(
        self,
        *,
        summary_payload: dict[str, Any] | None,
    ) -> list[tuple[int, dict[str, float]]]:
        rows = (summary_payload or {}).get("totalDataChartBreakdown") or []
        if not isinstance(rows, list):
            return []
        out: list[tuple[int, dict[str, float]]] = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            ts = row[0]
            bucket = row[1]
            if not isinstance(ts, (int, float)) or not isinstance(bucket, dict):
                continue

            chain_totals: dict[str, float] = {}
            for chain_name, chain_value in bucket.items():
                chain_key = str(chain_name or "").strip()
                if not chain_key:
                    continue
                total_val = 0.0
                has_val = False
                if isinstance(chain_value, dict):
                    for component_value in chain_value.values():
                        amount = _safe_float(component_value)
                        if amount is None:
                            continue
                        has_val = True
                        total_val += amount
                else:
                    amount = _safe_float(chain_value)
                    if amount is not None:
                        has_val = True
                        total_val += amount
                if has_val and total_val >= 0:
                    chain_totals[chain_key] = total_val

            if chain_totals:
                out.append((int(ts), chain_totals))
        out.sort(key=lambda item: item[0])
        return out

    def _sum_breakdown_window_days(
        self,
        *,
        series: list[tuple[int, dict[str, float]]],
        days: int,
        offset_days: int = 0,
    ) -> dict[str, float] | None:
        if not series:
            return None
        last_ts = series[-1][0]
        window_end = last_ts - (offset_days * 86400)
        window_start = window_end - (days * 86400)
        selected = [item for item in series if window_start < item[0] <= window_end]
        if len(selected) < max(3, int(days * 0.3)):
            return None

        totals: dict[str, float] = {}
        for _, bucket in selected:
            for chain_name, amount in bucket.items():
                if amount <= 0:
                    continue
                totals[chain_name] = totals.get(chain_name, 0.0) + amount
        return totals or None

    def _hhi_score(self, amounts: dict[str, float] | None) -> float | None:
        if not amounts:
            return None
        positive = [value for value in amounts.values() if value > 0]
        if not positive:
            return None
        total = sum(positive)
        if total <= 0:
            return None
        shares = [value / total for value in positive]
        return sum(share * share for share in shares)

    def _summary_request_proxy_total(
        self,
        *,
        summary_payload: dict[str, Any] | None,
        days: int,
    ) -> float | None:
        rows = (summary_payload or {}).get("totalDataChartBreakdown") or []
        if not isinstance(rows, list):
            return None

        keywords = ("request", "vrf", "entropy", "relay", "feed", "proof")
        series: list[tuple[int, float]] = []
        matched_any = False
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            ts = row[0]
            bucket = row[1]
            if not isinstance(ts, (int, float)) or not isinstance(bucket, dict):
                continue

            total_val = 0.0
            matched_here = False
            for chain_value in bucket.values():
                if not isinstance(chain_value, dict):
                    continue
                for label, value in chain_value.items():
                    amount = _safe_float(value)
                    if amount is None:
                        continue
                    label_l = str(label or "").strip().lower()
                    if any(keyword in label_l for keyword in keywords):
                        matched_here = True
                        total_val += amount
            if matched_here:
                matched_any = True
                series.append((int(ts), total_val))

        if not matched_any:
            return None
        return self._sum_window_days(series=series, days=days, offset_days=0)

    def _summary_chain_metrics(
        self,
        *,
        summary_payload: dict[str, Any] | None,
    ) -> tuple[float | None, float | None]:
        breakdown_series = self._summary_breakdown_chain_series(summary_payload=summary_payload)
        chain_totals_30d = self._sum_breakdown_window_days(series=breakdown_series, days=30)
        if chain_totals_30d:
            chain_count = float(sum(1 for value in chain_totals_30d.values() if value > 0))
            hhi = self._hhi_score(chain_totals_30d)
            network_diversification_score = (1.0 - hhi) if hhi is not None else None
            return chain_count if chain_count > 0 else None, network_diversification_score

        chains = (summary_payload or {}).get("chains") or []
        if isinstance(chains, list):
            unique_chains = {str(item or "").strip() for item in chains if str(item or "").strip()}
            chain_count = float(len(unique_chains))
            if chain_count > 1:
                return chain_count, 1.0 - (1.0 / chain_count)
            if chain_count == 1:
                return chain_count, 0.0
        return None, None

    def _summary_client_metrics(
        self,
        *,
        summary_payload: dict[str, Any] | None,
        target_name: str,
    ) -> tuple[float | None, float | None, float | None]:
        target_name_l = str(target_name or "").strip().lower()
        linked = (summary_payload or {}).get("linkedProtocols") or []
        child = (summary_payload or {}).get("childProtocols") or []

        clients: set[str] = set()
        if isinstance(linked, list):
            for item in linked:
                name = str(item or "").strip()
                if not name:
                    continue
                if target_name_l and name.lower() == target_name_l:
                    continue
                clients.add(name.lower())
        if isinstance(child, list):
            for item in child:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("displayName") or "").strip()
                if not name:
                    continue
                if target_name_l and name.lower() == target_name_l:
                    continue
                clients.add(name.lower())

        client_count = float(len(clients)) if clients else None
        if client_count is None:
            return None, None, None

        # If only count data exists, concentration is coarse by definition.
        hhi_proxy = (1.0 / client_count) if client_count > 0 else None
        diversification = (1.0 - hhi_proxy) if hhi_proxy is not None else None
        return client_count, diversification, hhi_proxy

    def _resolve_token_dependency_score(
        self,
        *,
        payload: dict[str, Any],
        revenue_30d: float | None,
        protocol_revenue_30d: float | None,
    ) -> float | None:
        current_chain_tvls = payload.get("currentChainTvls") or {}
        staking_depth = 0.0
        if isinstance(current_chain_tvls, dict):
            for key, value in current_chain_tvls.items():
                key_l = str(key or "").strip().lower()
                if "staking" not in key_l:
                    continue
                amount = _safe_float(value)
                if amount is None or amount <= 0:
                    continue
                staking_depth += amount

        if staking_depth > 0 and (
            (protocol_revenue_30d is not None and protocol_revenue_30d > 0)
            or (revenue_30d is not None and revenue_30d > 0)
        ):
            return 1.0
        if protocol_revenue_30d is not None and protocol_revenue_30d > 0:
            return 0.8
        if revenue_30d is not None and revenue_30d > 0:
            return 0.6
        return None

    async def _fetch_oracle_secured_value_index(self) -> dict[str, dict[str, float | None]]:
        cached = getattr(self, "_oracle_secured_value_index_cache", None)
        if isinstance(cached, dict):
            return cached

        index: dict[str, dict[str, float | None]] = {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(f"{self.base_url}/oracles")
        except Exception:
            setattr(self, "_oracle_secured_value_index_cache", index)
            return index

        if resp.status_code != 200:
            setattr(self, "_oracle_secured_value_index_cache", index)
            return index

        try:
            payload = resp.json() or {}
        except Exception:
            setattr(self, "_oracle_secured_value_index_cache", index)
            return index

        def _key_variants(*items: str) -> set[str]:
            out: set[str] = set()
            for item in items:
                if not item:
                    continue
                raw = str(item).strip().lower()
                if not raw:
                    continue
                out.add(raw)
                out.add(self._oracle_slugify(raw))
            return out

        def _upsert(keys: set[str], values: dict[str, float | None]) -> None:
            for key in keys:
                existing = index.get(key) or {}
                merged = dict(existing)
                for field, field_value in values.items():
                    if field_value is not None:
                        merged[field] = field_value
                index[key] = merged

        protocols = payload.get("protocols") or []
        if isinstance(protocols, list):
            for row in protocols:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or row.get("protocol") or "")
                slug = str(row.get("slug") or row.get("id") or "")
                secured_value_usd = _safe_float(
                    row.get("tvl")
                    or row.get("tvs")
                    or row.get("securedValue")
                    or row.get("total")
                )
                growth_30d = self._normalize_percent_ratio(
                    row.get("change_1m") or row.get("change_30d")
                )
                growth_90d = self._normalize_percent_ratio(
                    row.get("change_3m") or row.get("change_90d")
                )
                growth_1y = self._normalize_percent_ratio(
                    row.get("change_1y") or row.get("change_365d")
                )
                _upsert(
                    _key_variants(name, slug),
                    {
                        "secured_value_usd": secured_value_usd,
                        "secured_value_growth_30d": growth_30d,
                        "secured_value_growth_90d": growth_90d,
                        "secured_value_growth_1y": growth_1y,
                    },
                )

        chart = payload.get("chart") or {}
        if isinstance(chart, dict):
            series_by_protocol: dict[str, list[tuple[int, float]]] = {}
            for ts_raw, bucket in chart.items():
                try:
                    ts = int(ts_raw)
                except Exception:
                    continue
                if not isinstance(bucket, dict):
                    continue
                for proto_name, value in bucket.items():
                    amount = _safe_float(value)
                    if amount is None and isinstance(value, dict):
                        amount = _safe_float(
                            value.get("tvl")
                            or value.get("tvs")
                            or value.get("securedValue")
                            or value.get("value")
                        )
                    if amount is None:
                        continue
                    key = self._oracle_slugify(str(proto_name or ""))
                    if not key:
                        continue
                    series_by_protocol.setdefault(key, []).append((ts, amount))

            for key, series in series_by_protocol.items():
                series.sort(key=lambda item: item[0])
                if not series:
                    continue
                latest = series[-1][1]
                _upsert(
                    {key},
                    {
                        "secured_value_usd": latest,
                        "secured_value_growth_30d": self._series_growth_ratio(series=series, days=30),
                        "secured_value_growth_90d": self._series_growth_ratio(series=series, days=90),
                        "secured_value_growth_1y": self._series_growth_ratio(series=series, days=365),
                    },
                )

        setattr(self, "_oracle_secured_value_index_cache", index)
        return index

    def _lookup_oracle_secured_value(
        self,
        *,
        index: dict[str, dict[str, float | None]],
        candidates: list[str],
    ) -> dict[str, float | None]:
        if not index:
            return {}

        candidate_keys: list[str] = []
        for candidate in candidates:
            raw = str(candidate or "").strip().lower()
            if not raw:
                continue
            normalized = self._oracle_slugify(raw)
            if raw not in candidate_keys:
                candidate_keys.append(raw)
            if normalized and normalized not in candidate_keys:
                candidate_keys.append(normalized)

        for key in candidate_keys:
            row = index.get(key)
            if isinstance(row, dict) and row:
                return row

        for key in candidate_keys:
            for index_key, row in index.items():
                if key and (key in index_key or index_key in key):
                    if isinstance(row, dict) and row:
                        return row
        return {}

    async def _resolve_oracle_metrics(
        self,
        *,
        target: dict[str, Any],
        payload: dict[str, Any],
        target_slug: str,
        target_name: str,
        fees_30d: float | None,
        fees_90d: float | None,
        fees_1y: float | None,
        revenue_30d: float | None,
        revenue_90d: float | None,
        revenue_1y: float | None,
        growth_30d: float | None,
        growth_90d: float | None,
        growth_1y: float | None,
        annualized_fees: float | None,
        annualized_revenue: float | None,
    ) -> dict[str, Any]:
        oracle_name = str(payload.get("name") or target.get("name") or "")
        oracle_slug = str(payload.get("slug") or target_slug or "").strip().lower()
        summary_candidates = self._oracle_summary_slug_candidates(
            slug=oracle_slug,
            name=oracle_name,
            parent_slug=str(payload.get("parentProtocolSlug") or ""),
            protocol_id=str(payload.get("id") or ""),
        )

        fees_summary = await self._fetch_fee_summary_by_candidates(
            candidates=summary_candidates,
            data_type="dailyFees",
        )
        revenue_summary = await self._fetch_fee_summary_by_candidates(
            candidates=summary_candidates,
            data_type="dailyRevenue",
        )
        protocol_revenue_summary = await self._fetch_fee_summary_by_candidates(
            candidates=summary_candidates,
            data_type="dailyProtocolRevenue",
        )

        fees_30d_val = self._summary_total(fees_summary, 30)
        fees_90d_val = self._summary_total(fees_summary, 90)
        fees_1y_val = self._summary_total(fees_summary, 365)
        revenue_30d_val = self._summary_total(revenue_summary, 30)
        revenue_90d_val = self._summary_total(revenue_summary, 90)
        revenue_1y_val = self._summary_total(revenue_summary, 365)
        protocol_revenue_30d = self._summary_total(protocol_revenue_summary, 30)

        usage_30d_proxy = self._summary_request_proxy_total(summary_payload=fees_summary, days=30)
        usage_90d_proxy = self._summary_request_proxy_total(summary_payload=fees_summary, days=90)
        usage_1y_proxy = self._summary_request_proxy_total(summary_payload=fees_summary, days=365)

        fees_30d_final = fees_30d_val if fees_30d_val is not None else fees_30d
        fees_90d_final = fees_90d_val if fees_90d_val is not None else fees_90d
        fees_1y_final = fees_1y_val if fees_1y_val is not None else fees_1y
        revenue_30d_final = revenue_30d_val if revenue_30d_val is not None else revenue_30d
        revenue_90d_final = revenue_90d_val if revenue_90d_val is not None else revenue_90d
        revenue_1y_final = revenue_1y_val if revenue_1y_val is not None else revenue_1y
        usage_30d = usage_30d_proxy if usage_30d_proxy is not None else fees_30d_final
        usage_90d = usage_90d_proxy if usage_90d_proxy is not None else fees_90d_final
        usage_1y = usage_1y_proxy if usage_1y_proxy is not None else fees_1y_final

        chain_count, network_diversification_score = self._summary_chain_metrics(
            summary_payload=fees_summary or revenue_summary
        )
        client_protocols_count, client_diversification_score, client_concentration_hhi = self._summary_client_metrics(
            summary_payload=fees_summary or revenue_summary,
            target_name=oracle_name,
        )
        integrations_count = (
            client_protocols_count
            if client_protocols_count is not None
            else chain_count
        )

        secured_index = await self._fetch_oracle_secured_value_index()
        secured_row = self._lookup_oracle_secured_value(
            index=secured_index,
            candidates=summary_candidates + [oracle_name, str(payload.get("id") or "")],
        )
        secured_value_usd = _safe_float(secured_row.get("secured_value_usd"))
        secured_value_growth_30d = _safe_float(secured_row.get("secured_value_growth_30d"))
        secured_value_growth_90d = _safe_float(secured_row.get("secured_value_growth_90d"))
        secured_value_growth_1y = _safe_float(secured_row.get("secured_value_growth_1y"))

        fees_growth_30d = self._summary_growth(fees_summary, 30)
        fees_growth_90d = self._summary_growth(fees_summary, 90)
        fees_growth_1y = self._summary_growth(fees_summary, 365)
        revenue_growth_30d = self._summary_growth(revenue_summary, 30)
        revenue_growth_90d = self._summary_growth(revenue_summary, 90)
        revenue_growth_1y = self._summary_growth(revenue_summary, 365)
        usage_growth_30d = self._summary_growth(fees_summary, 30)
        usage_growth_90d = self._summary_growth(fees_summary, 90)
        usage_growth_1y = self._summary_growth(fees_summary, 365)

        def _pick(*values: float | None) -> float | None:
            for value in values:
                if value is not None:
                    return value
            return None

        growth_30d_final = _pick(
            usage_growth_30d,
            revenue_growth_30d,
            fees_growth_30d,
            secured_value_growth_30d,
            growth_30d,
        )
        growth_90d_final = _pick(
            usage_growth_90d,
            revenue_growth_90d,
            fees_growth_90d,
            secured_value_growth_90d,
            growth_90d,
        )
        growth_1y_final = _pick(
            usage_growth_1y,
            revenue_growth_1y,
            fees_growth_1y,
            secured_value_growth_1y,
            growth_1y,
        )

        annualized_fees_final = (
            annualized_fees
            if annualized_fees is not None
            else ((fees_30d_final * 365.0 / 30.0) if fees_30d_final is not None else None)
        )
        annualized_revenue_final = (
            annualized_revenue
            if annualized_revenue is not None
            else ((revenue_30d_final * 365.0 / 30.0) if revenue_30d_final is not None else None)
        )

        token_dependency_score = self._resolve_token_dependency_score(
            payload=payload,
            revenue_30d=revenue_30d_final,
            protocol_revenue_30d=protocol_revenue_30d,
        )

        return {
            "oracle_name": oracle_name,
            "oracle_slug": oracle_slug or self._oracle_slugify(oracle_name),
            "integrations_count": integrations_count,
            "secured_value_usd": secured_value_usd,
            "usage_30d": usage_30d,
            "fees_30d": fees_30d_final,
            "revenue_30d": revenue_30d_final,
            "chain_count": chain_count,
            "client_protocols_count": client_protocols_count,
            "growth_30d": growth_30d_final,
            "secured_value_growth_30d": secured_value_growth_30d,
            "secured_value_growth_90d": secured_value_growth_90d,
            "secured_value_growth_1y": secured_value_growth_1y,
            "usage_90d": usage_90d,
            "usage_1y": usage_1y,
            "fees_90d": fees_90d_final,
            "fees_1y": fees_1y_final,
            "revenue_90d": revenue_90d_final,
            "revenue_1y": revenue_1y_final,
            "annualized_fees": annualized_fees_final,
            "annualized_revenue": annualized_revenue_final,
            "network_diversification_score": network_diversification_score,
            "client_diversification_score": client_diversification_score,
            "client_concentration_hhi": client_concentration_hhi,
            "token_dependency_score": token_dependency_score,
            "request_count_30d": None,
            "update_frequency_sec": None,
            "deviation_bps": None,
            "uptime_pct": None,
            "slash_events_30d": None,
            "report_latency_ms": None,
            "retention_30d": None,
        }

    async def _resolve_oracle_competitors(
        self,
        *,
        target_oracle_slug: str,
        target_oracle_name: str,
        max_universe: int,
    ) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(f"{self.base_url}/overview/fees")
            if resp.status_code != 200:
                return []
            overview = resp.json() or {}
        except Exception:
            return []

        rows = list((overview or {}).get("protocols") or [])
        if not rows:
            return []

        oracle_keywords = ("oracle", "chainlink", "pyth", "api3", "redstone", "band", "supra", "witnet", "orcfax")
        filtered: list[dict[str, Any]] = []
        for row in rows:
            name_l = str(row.get("name") or "").strip().lower()
            slug_l = str(row.get("slug") or "").strip().lower()
            category_l = str(row.get("category") or "").strip().lower()
            if not any(keyword in " ".join([name_l, slug_l, category_l]) for keyword in oracle_keywords):
                continue
            total_30d = _safe_float(row.get("total30d"))
            total_24h = _safe_float(row.get("total24h"))
            if total_30d is None and total_24h is None:
                continue
            if (total_30d is not None and total_30d <= 0) and (total_24h is not None and total_24h <= 0):
                continue
            filtered.append(row)

        if not filtered:
            return []

        filtered.sort(
            key=lambda row: float(_safe_float(row.get("total30d")) or _safe_float(row.get("total24h")) or 0.0),
            reverse=True,
        )
        universe = filtered[:max_universe]
        target_slug_l = self._oracle_slugify(target_oracle_slug)
        target_name_l = str(target_oracle_name or "").strip().lower()
        if target_slug_l or target_name_l:
            has_target = False
            for row in universe:
                row_slug_l = self._oracle_slugify(str(row.get("slug") or ""))
                row_name_l = str(row.get("name") or "").strip().lower()
                if row_slug_l == target_slug_l or (target_name_l and row_name_l == target_name_l):
                    has_target = True
                    break
            if not has_target:
                for row in filtered[max_universe:]:
                    row_slug_l = self._oracle_slugify(str(row.get("slug") or ""))
                    row_name_l = str(row.get("name") or "").strip().lower()
                    if row_slug_l == target_slug_l or (target_name_l and row_name_l == target_name_l):
                        universe.append(row)
                        break

        secured_index = await self._fetch_oracle_secured_value_index()
        sem = asyncio.Semaphore(6)

        async def _load(row: dict[str, Any], fees_rank: int) -> dict[str, Any]:
            oracle_name = str(row.get("name") or "")
            oracle_slug = str(row.get("slug") or "")
            summary_candidates = self._oracle_summary_slug_candidates(
                slug=oracle_slug,
                name=oracle_name,
                parent_slug="",
                protocol_id=str(row.get("id") or ""),
            )

            async with sem:
                fees_summary = await self._fetch_fee_summary_by_candidates(
                    candidates=summary_candidates,
                    data_type="dailyFees",
                )
                revenue_summary = await self._fetch_fee_summary_by_candidates(
                    candidates=summary_candidates,
                    data_type="dailyRevenue",
                )

            fees_30d = self._summary_total(fees_summary, 30)
            if fees_30d is None:
                fees_30d = _safe_float(row.get("total30d"))
            revenue_30d = self._summary_total(revenue_summary, 30)
            usage_30d = self._summary_request_proxy_total(summary_payload=fees_summary, days=30)
            if usage_30d is None:
                usage_30d = fees_30d

            chain_count, network_diversification_score = self._summary_chain_metrics(
                summary_payload=fees_summary or revenue_summary
            )
            client_protocols_count, client_diversification_score, _ = self._summary_client_metrics(
                summary_payload=fees_summary or revenue_summary,
                target_name=oracle_name,
            )
            integrations_count = (
                client_protocols_count
                if client_protocols_count is not None
                else chain_count
            )
            growth_30d = self._summary_growth(fees_summary, 30)
            if growth_30d is None:
                growth_30d = self._summary_growth(revenue_summary, 30)
            if growth_30d is None:
                growth_30d = self._normalize_percent_ratio(row.get("change_30dover30d"))

            secured_row = self._lookup_oracle_secured_value(
                index=secured_index,
                candidates=summary_candidates + [oracle_name],
            )
            secured_value_usd = _safe_float(secured_row.get("secured_value_usd"))

            is_target = (
                (target_slug_l and self._oracle_slugify(oracle_slug) == target_slug_l)
                or (target_name_l and oracle_name.strip().lower() == target_name_l)
            )
            return {
                "name": oracle_name,
                "slug": oracle_slug,
                "is_target": is_target,
                "secured_value_usd": secured_value_usd,
                "integrations_count": integrations_count,
                "usage_30d": usage_30d,
                "fees_30d": fees_30d,
                "revenue_30d": revenue_30d,
                "chain_count": chain_count,
                "client_protocols_count": client_protocols_count,
                "growth_30d": growth_30d,
                "network_diversification_score": network_diversification_score,
                "client_diversification_score": client_diversification_score,
                "token_dependency_score": None,
                "fees_30d_rank": fees_rank,
            }

        tasks = [_load(row, idx) for idx, row in enumerate(universe, start=1)]
        loaded = await asyncio.gather(*tasks, return_exceptions=True)
        competitors: list[dict[str, Any]] = []
        for item in loaded:
            if isinstance(item, dict):
                competitors.append(item)

        def _row_key(name: str, slug: str) -> str:
            return slug.strip().lower() or name.strip().lower()

        def _build_rank(metric: str, descending: bool = True) -> dict[str, int]:
            rank_rows = [row for row in competitors if isinstance(row.get(metric), (int, float))]
            rank_rows.sort(key=lambda row: float(row.get(metric) or 0.0), reverse=descending)
            out: dict[str, int] = {}
            for idx, row in enumerate(rank_rows, start=1):
                out[_row_key(str(row.get("name") or ""), str(row.get("slug") or ""))] = idx
            return out

        secured_rank = _build_rank("secured_value_usd", descending=True)
        integrations_rank = _build_rank("integrations_count", descending=True)
        usage_rank = _build_rank("usage_30d", descending=True)
        fees_rank = _build_rank("fees_30d", descending=True)
        revenue_rank = _build_rank("revenue_30d", descending=True)
        chain_rank = _build_rank("chain_count", descending=True)
        client_rank = _build_rank("client_protocols_count", descending=True)
        growth_rank = _build_rank("growth_30d", descending=True)
        client_div_rank = _build_rank("client_diversification_score", descending=True)
        token_dep_rank = _build_rank("token_dependency_score", descending=True)
        for row in competitors:
            key = _row_key(str(row.get("name") or ""), str(row.get("slug") or ""))
            row["secured_value_rank"] = secured_rank.get(key)
            row["integrations_count_rank"] = integrations_rank.get(key)
            row["usage_30d_rank"] = usage_rank.get(key)
            row["fees_30d_rank"] = fees_rank.get(key)
            row["revenue_30d_rank"] = revenue_rank.get(key)
            row["chain_count_rank"] = chain_rank.get(key)
            row["client_protocols_count_rank"] = client_rank.get(key)
            row["growth_30d_rank"] = growth_rank.get(key)
            row["client_diversification_rank"] = client_div_rank.get(key)
            row["token_dependency_rank"] = token_dep_rank.get(key)
        return competitors

    def _build_oracle_sector_metrics(
        self,
        *,
        oracle: dict[str, Any],
    ) -> dict[str, dict[str, float | None]]:
        metric_values: dict[str, float | None] = {
            "integrations_count": _safe_float(oracle.get("integrations_count")),
            "secured_value_usd": _safe_float(oracle.get("secured_value_usd")),
            "usage_30d": _safe_float(oracle.get("usage_30d")),
            "fees_30d": _safe_float(oracle.get("fees_30d")),
            "revenue_30d": _safe_float(oracle.get("revenue_30d")),
            "chain_count": _safe_float(oracle.get("chain_count")),
            "client_protocols_count": _safe_float(oracle.get("client_protocols_count")),
            "growth_30d": _safe_float(oracle.get("growth_30d")),
            "secured_value_growth_30d": _safe_float(oracle.get("secured_value_growth_30d")),
            "secured_value_growth_90d": _safe_float(oracle.get("secured_value_growth_90d")),
            "secured_value_growth_1y": _safe_float(oracle.get("secured_value_growth_1y")),
            "usage_90d": _safe_float(oracle.get("usage_90d")),
            "usage_1y": _safe_float(oracle.get("usage_1y")),
            "fees_90d": _safe_float(oracle.get("fees_90d")),
            "fees_1y": _safe_float(oracle.get("fees_1y")),
            "revenue_90d": _safe_float(oracle.get("revenue_90d")),
            "revenue_1y": _safe_float(oracle.get("revenue_1y")),
            "annualized_fees": _safe_float(oracle.get("annualized_fees")),
            "annualized_revenue": _safe_float(oracle.get("annualized_revenue")),
            "network_diversification_score": _safe_float(oracle.get("network_diversification_score")),
            "client_diversification_score": _safe_float(oracle.get("client_diversification_score")),
            "token_dependency_score": _safe_float(oracle.get("token_dependency_score")),
            "request_count_30d": _safe_float(oracle.get("request_count_30d")),
            "update_frequency_sec": _safe_float(oracle.get("update_frequency_sec")),
            "deviation_bps": _safe_float(oracle.get("deviation_bps")),
            "uptime_pct": _safe_float(oracle.get("uptime_pct")),
            "slash_events_30d": _safe_float(oracle.get("slash_events_30d")),
            "report_latency_ms": _safe_float(oracle.get("report_latency_ms")),
            "retention_30d": _safe_float(oracle.get("retention_30d")),
        }
        return {
            tier: {metric: metric_values.get(metric) for metric in metrics}
            for tier, metrics in ORACLE_SECTOR_METRICS.items()
        }

    def _build_oracle_derived_metrics(
        self,
        *,
        oracle: dict[str, Any],
    ) -> dict[str, dict[str, float | None]]:
        secured_value = _safe_float(oracle.get("secured_value_usd"))
        fees_30d = _safe_float(oracle.get("fees_30d"))
        revenue_30d = _safe_float(oracle.get("revenue_30d"))
        integrations_count = _safe_float(oracle.get("integrations_count"))
        client_count = _safe_float(oracle.get("client_protocols_count"))
        usage_30d = _safe_float(oracle.get("usage_30d"))
        chain_count = _safe_float(oracle.get("chain_count"))
        network_div = _safe_float(oracle.get("network_diversification_score"))
        client_div = _safe_float(oracle.get("client_diversification_score"))

        metric_values: dict[str, float | None] = {
            "secured_value_to_fees_ratio_30d": (
                (secured_value / fees_30d)
                if secured_value is not None and fees_30d and fees_30d > 0
                else None
            ),
            "revenue_to_fees_ratio_30d": (
                (revenue_30d / fees_30d)
                if revenue_30d is not None and fees_30d and fees_30d > 0
                else None
            ),
            "fees_per_integration_30d": (
                (fees_30d / integrations_count)
                if fees_30d is not None and integrations_count and integrations_count > 0
                else None
            ),
            "revenue_per_client_30d": (
                (revenue_30d / client_count)
                if revenue_30d is not None and client_count and client_count > 0
                else None
            ),
            "usage_per_chain_30d": (
                (usage_30d / chain_count)
                if usage_30d is not None and chain_count and chain_count > 0
                else None
            ),
            "chain_client_diversification_ratio": (
                (network_div / client_div)
                if network_div is not None and client_div and client_div > 0
                else None
            ),
            "uptime_adjusted_revenue_score": None,
            "oracle_quality_score": None,
        }
        return {
            tier: {metric: metric_values.get(metric) for metric in metrics}
            for tier, metrics in ORACLE_DERIVED_METRICS.items()
        }

    def _build_oracle_quality_layer(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
    ) -> dict[str, Any]:
        metric_values: dict[str, float | None] = {}
        for grouped in (sector_metrics, derived_metrics):
            for tier_values in grouped.values():
                for key, value in (tier_values or {}).items():
                    if key not in metric_values:
                        metric_values[key] = value

        def _status(score: float) -> str:
            if score >= 0.8:
                return "sufficient"
            if score >= 0.5:
                return "partial"
            return "insufficient"

        def _coverage(required: list[str]) -> dict[str, Any]:
            available = [metric for metric in required if metric_values.get(metric) is not None]
            missing = [metric for metric in required if metric_values.get(metric) is None]
            total = len(required)
            score = (len(available) / total) if total > 0 else 1.0
            return {
                "required": required,
                "available": available,
                "missing": missing,
                "score": round(score, 3),
                "status": _status(score),
            }

        cov_30d = _coverage(
            [
                "integrations_count",
                "secured_value_usd",
                "usage_30d",
                "fees_30d",
                "revenue_30d",
                "growth_30d",
            ]
        )
        cov_90d = _coverage(
            [
                "secured_value_growth_90d",
                "usage_90d",
                "fees_90d",
                "revenue_90d",
            ]
        )
        cov_1y = _coverage(
            [
                "secured_value_growth_1y",
                "usage_1y",
                "fees_1y",
                "revenue_1y",
            ]
        )

        long_horizon_score = round(
            (cov_30d["score"] * 0.5) + (cov_90d["score"] * 0.3) + (cov_1y["score"] * 0.2),
            3,
        )
        if cov_30d["status"] == "sufficient" and long_horizon_score >= 0.7:
            confidence = "sufficient"
        elif cov_30d["status"] != "insufficient" and long_horizon_score >= 0.5:
            confidence = "partial"
        else:
            confidence = "insufficient"

        return {
            "primary_horizon": "30d",
            "horizon_coverage": {
                "30d": cov_30d,
                "90d": cov_90d,
                "1y": cov_1y,
            },
            "long_horizon_score": long_horizon_score,
            "long_horizon_confidence": confidence,
            "enough_for_fundamental_conclusion": confidence == "sufficient",
            "rule": "30d is primary minimum, 90d is important, 1y is long-range when available; 24h is secondary context only.",
        }

    def _build_oracle_flat_metrics(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
        include_non_oracle_defaults: bool,
    ) -> dict[str, float]:
        flat: dict[str, float] = {}
        tiers = ("must", "should") if not include_non_oracle_defaults else ("must",)
        for tier in tiers:
            for key, value in (sector_metrics.get(tier) or {}).items():
                if value is not None:
                    flat[key] = value
            for key, value in (derived_metrics.get(tier) or {}).items():
                if value is not None:
                    flat[key] = value

        revenue_30d = _safe_float(flat.get("revenue_30d"))
        if revenue_30d is not None:
            flat["protocol_income_30d"] = revenue_30d
        return flat

    def _build_oracle_competitor_comparison(
        self,
        *,
        competitors: list[dict[str, Any]],
        target_snapshot: dict[str, Any],
        max_peers: int,
    ) -> dict[str, Any]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        target_row: dict[str, Any] | None = None

        def _key(row: dict[str, Any]) -> str:
            return str(row.get("slug") or "").strip().lower() or str(row.get("name") or "").strip().lower()

        for row in competitors:
            key = _key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            compact = {
                "name": row.get("name"),
                "slug": row.get("slug"),
                "is_target": bool(row.get("is_target")),
                "secured_value_usd": _safe_float(row.get("secured_value_usd")),
                "secured_value_rank": row.get("secured_value_rank"),
                "integrations_count": _safe_float(row.get("integrations_count")),
                "integrations_count_rank": row.get("integrations_count_rank"),
                "usage_30d": _safe_float(row.get("usage_30d")),
                "usage_30d_rank": row.get("usage_30d_rank"),
                "fees_30d": _safe_float(row.get("fees_30d")),
                "fees_30d_rank": row.get("fees_30d_rank"),
                "revenue_30d": _safe_float(row.get("revenue_30d")),
                "revenue_30d_rank": row.get("revenue_30d_rank"),
                "chain_count": _safe_float(row.get("chain_count")),
                "chain_count_rank": row.get("chain_count_rank"),
                "client_protocols_count": _safe_float(row.get("client_protocols_count")),
                "client_protocols_count_rank": row.get("client_protocols_count_rank"),
                "growth_30d": _safe_float(row.get("growth_30d")),
                "growth_30d_rank": row.get("growth_30d_rank"),
                "client_diversification_score": _safe_float(row.get("client_diversification_score")),
                "client_diversification_rank": row.get("client_diversification_rank"),
                "token_dependency_score": _safe_float(row.get("token_dependency_score")),
                "token_dependency_rank": row.get("token_dependency_rank"),
            }
            normalized.append(
                {k: v for k, v in compact.items() if v is not None or k in {"name", "slug", "is_target"}}
            )
            if compact["is_target"]:
                target_row = compact

        if target_row is None:
            target_row = {
                "name": target_snapshot.get("name"),
                "slug": target_snapshot.get("slug"),
                "is_target": True,
                "secured_value_usd": _safe_float(target_snapshot.get("secured_value_usd")),
                "integrations_count": _safe_float(target_snapshot.get("integrations_count")),
                "usage_30d": _safe_float(target_snapshot.get("usage_30d")),
                "fees_30d": _safe_float(target_snapshot.get("fees_30d")),
                "revenue_30d": _safe_float(target_snapshot.get("revenue_30d")),
                "chain_count": _safe_float(target_snapshot.get("chain_count")),
                "client_protocols_count": _safe_float(target_snapshot.get("client_protocols_count")),
                "growth_30d": _safe_float(target_snapshot.get("growth_30d")),
                "client_diversification_score": _safe_float(target_snapshot.get("client_diversification_score")),
                "token_dependency_score": _safe_float(target_snapshot.get("token_dependency_score")),
            }

        def _peer_family(slug: str, name: str) -> str:
            slug_l = slug.strip().lower()
            if slug_l.startswith("chainlink"):
                return "chainlink"
            if slug_l.startswith("pyth"):
                return "pyth"
            for suffix in ("-requests", "-staking", "-entropy", "-express-relay", "-core", "-pro", "-vrf"):
                if slug_l.endswith(suffix):
                    slug_l = slug_l[: -len(suffix)]
                    break
            if "-" in slug_l:
                return slug_l.split("-", 1)[0]
            return slug_l or name.strip().lower()

        peers = [row for row in normalized if not row.get("is_target")]
        target_family = _peer_family(
            str(target_row.get("slug") or ""),
            str(target_row.get("name") or ""),
        )
        if target_family:
            filtered_peers: list[dict[str, Any]] = []
            for row in peers:
                row_family = _peer_family(
                    str(row.get("slug") or ""),
                    str(row.get("name") or ""),
                )
                if row_family and row_family == target_family:
                    continue
                filtered_peers.append(row)
            peers = filtered_peers

        peers.sort(
            key=lambda row: (
                int(row.get("secured_value_rank") or 10_000),
                -(float(row.get("fees_30d") or 0.0)),
            )
        )

        deduped_peers: list[dict[str, Any]] = []
        seen_families: set[str] = set()

        for row in peers:
            family = _peer_family(str(row.get("slug") or ""), str(row.get("name") or ""))
            if family and family in seen_families:
                continue
            if family:
                seen_families.add(family)
            deduped_peers.append(row)
            if len(deduped_peers) >= max_peers:
                break

        selected_projects = [
            {k: v for k, v in target_row.items() if v is not None or k in {"name", "slug", "is_target"}}
        ] + deduped_peers

        def _rank_from_normalized(metric: str, target_metric: float | None) -> int | None:
            if target_metric is None:
                return None
            higher = 0
            for row in normalized:
                if row.get("is_target"):
                    continue
                row_val = _safe_float(row.get(metric))
                if row_val is not None and row_val > target_metric:
                    higher += 1
            return higher + 1

        target_ranks = {
            "secured_value_rank": target_row.get("secured_value_rank")
            or _rank_from_normalized("secured_value_usd", _safe_float(target_row.get("secured_value_usd"))),
            "integrations_count_rank": target_row.get("integrations_count_rank")
            or _rank_from_normalized("integrations_count", _safe_float(target_row.get("integrations_count"))),
            "usage_30d_rank": target_row.get("usage_30d_rank")
            or _rank_from_normalized("usage_30d", _safe_float(target_row.get("usage_30d"))),
            "fees_30d_rank": target_row.get("fees_30d_rank")
            or _rank_from_normalized("fees_30d", _safe_float(target_row.get("fees_30d"))),
            "revenue_30d_rank": target_row.get("revenue_30d_rank")
            or _rank_from_normalized("revenue_30d", _safe_float(target_row.get("revenue_30d"))),
            "chain_count_rank": target_row.get("chain_count_rank")
            or _rank_from_normalized("chain_count", _safe_float(target_row.get("chain_count"))),
            "client_protocols_count_rank": target_row.get("client_protocols_count_rank")
            or _rank_from_normalized(
                "client_protocols_count",
                _safe_float(target_row.get("client_protocols_count")),
            ),
            "growth_30d_rank": target_row.get("growth_30d_rank")
            or _rank_from_normalized("growth_30d", _safe_float(target_row.get("growth_30d"))),
            "client_diversification_rank": target_row.get("client_diversification_rank")
            or _rank_from_normalized(
                "client_diversification_score",
                _safe_float(target_row.get("client_diversification_score")),
            ),
            "token_dependency_rank": target_row.get("token_dependency_rank")
            or _rank_from_normalized(
                "token_dependency_score",
                _safe_float(target_row.get("token_dependency_score")),
            ),
        }
        return {
            "projects": selected_projects[: max_peers + 1],
            "target_ranks": target_ranks,
            "universe_size": len(normalized),
        }

    def _build_oracle_gaps(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
        competitor_comparison: dict[str, Any],
        is_oracle_sector: bool,
    ) -> list[dict[str, str]]:
        if not is_oracle_sector:
            return []

        gaps: list[dict[str, str]] = []

        def _append_metric_gap(group: str, tier: str, metric: str) -> None:
            reason = self._oracle_gap_reason(metric=metric, group=group, tier=tier)
            gaps.append(
                {
                    "group": group,
                    "priority": tier,
                    "metric": metric,
                    "reason": reason,
                }
            )

        for tier, tier_metrics in ORACLE_SECTOR_METRICS.items():
            for metric in tier_metrics:
                if sector_metrics.get(tier, {}).get(metric) is None:
                    _append_metric_gap("sector_metrics", tier, metric)

        for tier, tier_metrics in ORACLE_DERIVED_METRICS.items():
            for metric in tier_metrics:
                if derived_metrics.get(tier, {}).get(metric) is None:
                    _append_metric_gap("derived_metrics", tier, metric)

        target_ranks = competitor_comparison.get("target_ranks") or {}
        for tier, tier_metrics in ORACLE_COMPETITOR_METRICS.items():
            for metric in tier_metrics:
                if target_ranks.get(metric) is None:
                    _append_metric_gap("competitor_comparison", tier, metric)

        if sector_metrics.get("must", {}).get("secured_value_usd") is None:
            _append_metric_gap("gaps", "must", "missing_secured_value_dataset")
        if sector_metrics.get("optional_later", {}).get("request_count_30d") is None:
            _append_metric_gap("gaps", "must", "missing_standardized_request_count")
        if sector_metrics.get("should", {}).get("client_diversification_score") is None:
            _append_metric_gap("gaps", "should", "missing_client_level_usage_breakdown")
        if sector_metrics.get("should", {}).get("token_dependency_score") is None:
            _append_metric_gap("gaps", "should", "missing_token_dependency_methodology")
        if sector_metrics.get("optional_later", {}).get("report_latency_ms") is None:
            _append_metric_gap("gaps", "optional_later", "missing_feed_level_latency")
        if sector_metrics.get("optional_later", {}).get("uptime_pct") is None:
            _append_metric_gap("gaps", "optional_later", "missing_oracle_failure_postmortems")
        return gaps

    def _oracle_gap_reason(self, *, metric: str, group: str, tier: str) -> str:
        if tier == "optional_later":
            return "Deferred by scope (optional_later), not targeted in first oracles implementation."

        reasons = {
            "integrations_count": "No standardized open dataset for true downstream client integrations across oracle networks.",
            "secured_value_usd": "Secured-value endpoint is currently rate-limited/paywalled for public API access in this source stack.",
            "usage_30d": "No standardized public request-count dataset; usage is proxied via request-fee activity where available.",
            "fees_30d": "30d fees are required for long-horizon oracle business throughput baseline.",
            "revenue_30d": "30d protocol revenue is required for long-horizon oracle monetization baseline.",
            "chain_count": "Chain distribution metadata is required for network diversification baseline.",
            "client_protocols_count": "Client protocol count is required for demand concentration baseline.",
            "growth_30d": "Primary growth metric requires at least 30d history (usage/revenue/fees/secured-value basis).",
            "secured_value_growth_30d": "Requires stable 30d secured-value time-series coverage.",
            "secured_value_growth_90d": "Requires stable 90d secured-value time-series coverage.",
            "secured_value_growth_1y": "Requires stable 1y secured-value time-series coverage.",
            "usage_90d": "Requires medium-horizon usage/request dataset beyond 30d proxy.",
            "usage_1y": "Requires long-horizon usage/request dataset beyond 30d proxy.",
            "fees_90d": "Requires 90d fee history for medium-horizon consistency checks.",
            "fees_1y": "Requires 1y fee history for long-cycle consistency checks.",
            "revenue_90d": "Requires 90d revenue history for medium-horizon consistency checks.",
            "revenue_1y": "Requires 1y revenue history for long-cycle consistency checks.",
            "annualized_fees": "Cannot annualize fees reliably without 30d fees baseline.",
            "annualized_revenue": "Cannot annualize revenue reliably without 30d revenue baseline.",
            "network_diversification_score": "Needs stable chain-level usage/fee breakdown to compute diversification quality.",
            "client_diversification_score": "Needs client-level usage split; linked/child metadata is incomplete for broad coverage.",
            "token_dependency_score": "No standardized cross-protocol methodology for token-requiredness in oracle operations.",
            "secured_value_to_fees_ratio_30d": "Cannot compute without secured_value_usd and fees_30d.",
            "revenue_to_fees_ratio_30d": "Cannot compute without revenue_30d and fees_30d.",
            "fees_per_integration_30d": "Cannot compute without integrations_count and fees_30d.",
            "revenue_per_client_30d": "Cannot compute without client_protocols_count and revenue_30d.",
            "usage_per_chain_30d": "Cannot compute without usage_30d and chain_count.",
            "chain_client_diversification_ratio": "Cannot compute without both network and client diversification baselines.",
            "secured_value_rank": "Peer secured-value ranking is unavailable without reliable secured-value dataset.",
            "integrations_count_rank": "Peer integration counts are unavailable without standardized client-integration dataset.",
            "usage_30d_rank": "Peer usage ranking requires standardized request-count data; current values are proxy-based.",
            "fees_30d_rank": "Peer-comparable 30d fees are unavailable for enough oracle competitors.",
            "revenue_30d_rank": "Peer-comparable 30d revenue is unavailable for enough oracle competitors.",
            "chain_count_rank": "Peer chain-coverage ranking is unavailable for enough competitors.",
            "client_protocols_count_rank": "Peer client-protocol counts are unavailable for enough competitors.",
            "growth_30d_rank": "Peer-comparable 30d growth is unavailable for enough competitors.",
            "client_diversification_rank": "Client-level diversification ranking needs client split dataset.",
            "token_dependency_rank": "Token dependency ranking needs standardized cross-protocol methodology.",
            "missing_secured_value_dataset": "Public secured-value endpoint is rate-limited/paywalled in current source stack.",
            "missing_standardized_request_count": "No standardized public request-count dataset across oracle protocols.",
            "missing_client_level_usage_breakdown": "Client-level usage distribution is not exposed consistently in current source stack.",
            "missing_token_dependency_methodology": "Token-requiredness signal is heuristic only; standardized methodology is missing.",
            "missing_feed_level_latency": "Feed-level latency/update datasets are not available in current source stack.",
            "missing_oracle_failure_postmortems": "Structured oracle failure/postmortem dataset is not available in current source stack.",
        }
        reason = reasons.get(metric)
        if reason:
            return reason
        if group == "competitor_comparison":
            return "Peer-comparable data for this ranking metric is not available in current source stack."
        return "Metric is unavailable from current sources for this run."

    def _compute_utilization_rate(
        self,
        *,
        borrowed_usd: float | None,
        supplied_usd: float | None,
        top_yields: list[dict[str, Any]],
    ) -> float | None:
        if borrowed_usd is not None and supplied_usd and supplied_usd > 0:
            return borrowed_usd / supplied_usd

        borrow_sum = 0.0
        supply_sum = 0.0
        for row in top_yields:
            b = _safe_float(row.get("total_borrow_usd"))
            s = _safe_float(row.get("total_supply_usd"))
            if b is not None and b > 0:
                borrow_sum += b
            if s is not None and s > 0:
                supply_sum += s
        if supply_sum > 0 and borrow_sum > 0:
            return borrow_sum / supply_sum
        return None

    def _build_lending_sector_metrics(
        self,
        *,
        tvl: float | None,
        borrowed_usd: float | None,
        supplied_usd: float | None,
        fees_30d: float | None,
        fees_90d: float | None,
        fees_1y: float | None,
        revenue_30d: float | None,
        revenue_90d: float | None,
        revenue_1y: float | None,
        holder_revenue_30d: float | None,
        holder_revenue_90d: float | None,
        holder_revenue_1y: float | None,
        annualized_revenue: float | None,
        annualized_holder_revenue: float | None,
        net_borrow_flow_30d: float | None,
        borrowed_growth_30d: float | None,
        growth_30d: float | None,
        growth_90d: float | None,
        growth_1y: float | None,
        avg_apy: float | None,
        market_cap: float | None,
        volume_30d: float | None,
        utilization_rate: float | None,
        avg_borrow_apy: float | None,
        avg_supply_apy: float | None,
        fees_24h: float | None,
        revenue_24h: float | None,
        holder_revenue_24h: float | None,
        volume_24h: float | None,
        liquidations_24h: float | None,
        bad_debt_usd: float | None,
    ) -> dict[str, dict[str, float | None]]:
        metric_values: dict[str, float | None] = {
            "tvl": tvl,
            "borrowed_usd": borrowed_usd,
            "supplied_usd": supplied_usd,
            "fees_30d": fees_30d,
            "fees_90d": fees_90d,
            "fees_1y": fees_1y,
            "revenue_30d": revenue_30d,
            "revenue_90d": revenue_90d,
            "revenue_1y": revenue_1y,
            "holder_revenue_30d": holder_revenue_30d,
            "holder_revenue_90d": holder_revenue_90d,
            "holder_revenue_1y": holder_revenue_1y,
            "net_borrow_flow_30d": net_borrow_flow_30d,
            "volume_30d": volume_30d,
            "market_cap": market_cap,
            "growth_30d": growth_30d,
            "growth_90d": growth_90d,
            "growth_1y": growth_1y,
            "annualized_revenue": annualized_revenue,
            "annualized_holder_revenue": annualized_holder_revenue,
            "borrowed_growth_30d": borrowed_growth_30d,
            "utilization_rate": utilization_rate,
            "avg_borrow_apy": avg_borrow_apy,
            "avg_supply_apy": avg_supply_apy,
            "avg_apy": avg_apy,
            "liquidations_24h": liquidations_24h,
            "bad_debt_usd": bad_debt_usd,
            "fees_24h": fees_24h,
            "revenue_24h": revenue_24h,
            "holder_revenue_24h": holder_revenue_24h,
            "volume_24h": volume_24h,
            "reserve_factor": None,
            "isolation_mode_share": None,
            "oracle_exposure_share": None,
        }
        return {
            tier: {metric: metric_values.get(metric) for metric in metrics}
            for tier, metrics in LENDING_SECTOR_METRICS.items()
        }

    def _build_lending_derived_metrics(
        self,
        *,
        tvl: float | None,
        market_cap: float | None,
        borrowed_usd: float | None,
        supplied_usd: float | None,
        revenue_30d: float | None,
        avg_borrow_apy: float | None,
        avg_supply_apy: float | None,
        liquidations_24h: float | None,
        bad_debt_usd: float | None,
    ) -> dict[str, dict[str, float | None]]:
        metric_values: dict[str, float | None] = {
            "borrow_to_supply_ratio": (
                (borrowed_usd / supplied_usd)
                if borrowed_usd is not None and supplied_usd and supplied_usd > 0
                else None
            ),
            "mcap_to_tvl_ratio": (
                (market_cap / tvl)
                if market_cap is not None and tvl and tvl > 0
                else None
            ),
            "revenue_to_tvl_ratio_30d": (
                (revenue_30d / tvl)
                if revenue_30d is not None and tvl and tvl > 0
                else None
            ),
            "borrow_supply_spread": (
                avg_borrow_apy - avg_supply_apy
                if avg_borrow_apy is not None and avg_supply_apy is not None
                else None
            ),
            "bad_debt_to_tvl_ratio": (
                (bad_debt_usd / tvl)
                if bad_debt_usd is not None and tvl and tvl > 0
                else None
            ),
            "liquidations_to_borrowed_ratio": (
                (liquidations_24h / borrowed_usd)
                if liquidations_24h is not None and borrowed_usd and borrowed_usd > 0
                else None
            ),
            "risk_adjusted_real_yield": None,
            "capital_efficiency_score": None,
        }
        return {
            tier: {metric: metric_values.get(metric) for metric in metrics}
            for tier, metrics in LENDING_DERIVED_METRICS.items()
        }

    def _build_lending_quality_layer(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
    ) -> dict[str, Any]:
        metric_values: dict[str, float | None] = {}
        for grouped in (sector_metrics, derived_metrics):
            for tier_values in grouped.values():
                for key, value in (tier_values or {}).items():
                    if key not in metric_values:
                        metric_values[key] = value

        def _status(score: float) -> str:
            if score >= 0.8:
                return "sufficient"
            if score >= 0.5:
                return "partial"
            return "insufficient"

        def _coverage(required: list[str]) -> dict[str, Any]:
            available = [metric for metric in required if metric_values.get(metric) is not None]
            missing = [metric for metric in required if metric_values.get(metric) is None]
            total = len(required)
            score = (len(available) / total) if total > 0 else 1.0
            return {
                "required": required,
                "available": available,
                "missing": missing,
                "score": round(score, 3),
                "status": _status(score),
            }

        cov_30d = _coverage(
            [
                "fees_30d",
                "revenue_30d",
                "holder_revenue_30d",
                "growth_30d",
                "net_borrow_flow_30d",
            ]
        )
        cov_90d = _coverage(
            [
                "fees_90d",
                "revenue_90d",
                "holder_revenue_90d",
                "growth_90d",
            ]
        )
        cov_1y = _coverage(
            [
                "fees_1y",
                "revenue_1y",
                "holder_revenue_1y",
                "growth_1y",
            ]
        )

        long_horizon_score = round(
            (cov_30d["score"] * 0.5) + (cov_90d["score"] * 0.3) + (cov_1y["score"] * 0.2),
            3,
        )
        if cov_30d["status"] == "sufficient" and long_horizon_score >= 0.7:
            confidence = "sufficient"
        elif cov_30d["status"] != "insufficient" and long_horizon_score >= 0.5:
            confidence = "partial"
        else:
            confidence = "insufficient"

        return {
            "primary_horizon": "30d",
            "horizon_coverage": {
                "30d": cov_30d,
                "90d": cov_90d,
                "1y": cov_1y,
            },
            "long_horizon_score": long_horizon_score,
            "long_horizon_confidence": confidence,
            "enough_for_fundamental_conclusion": confidence == "sufficient",
            "rule": "30d is primary minimum, 90d is important, 1y is long-range when available; 24h is secondary context only.",
        }

    def _build_lending_flat_metrics(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
        include_non_lending_defaults: bool,
    ) -> dict[str, float]:
        flat: dict[str, float] = {}
        tiers = ("must", "should") if not include_non_lending_defaults else ("must",)
        for tier in tiers:
            for key, value in (sector_metrics.get(tier) or {}).items():
                if value is not None:
                    flat[key] = value
            for key, value in (derived_metrics.get(tier) or {}).items():
                if value is not None:
                    flat[key] = value

        supplied_usd = _safe_float(flat.get("supplied_usd"))
        revenue_30d = _safe_float(flat.get("revenue_30d"))
        if supplied_usd is not None:
            flat["collateral_related_usd"] = supplied_usd
        if revenue_30d is not None:
            flat["protocol_income_30d"] = revenue_30d
        return flat

    def _build_dex_sector_metrics(
        self,
        *,
        tvl: float | None,
        market_cap: float | None,
        dex_volume_24h: float | None,
        dex_volume_30d: float | None,
        dex_volume_90d: float | None,
        dex_volume_1y: float | None,
        fees_24h: float | None,
        fees_30d: float | None,
        fees_90d: float | None,
        fees_1y: float | None,
        revenue_24h: float | None,
        revenue_30d: float | None,
        revenue_90d: float | None,
        revenue_1y: float | None,
        holder_revenue_30d: float | None,
        holder_revenue_90d: float | None,
        holder_revenue_1y: float | None,
        growth_30d: float | None,
        growth_90d: float | None,
        growth_1y: float | None,
        annualized_fees: float | None,
        annualized_revenue: float | None,
    ) -> dict[str, dict[str, float | None]]:
        metric_values: dict[str, float | None] = {
            "dex_volume_30d": dex_volume_30d,
            "tvl": tvl,
            "fees_30d": fees_30d,
            "revenue_30d": revenue_30d,
            "market_cap": market_cap,
            "growth_30d": growth_30d,
            "dex_volume_90d": dex_volume_90d,
            "dex_volume_1y": dex_volume_1y,
            "fees_90d": fees_90d,
            "fees_1y": fees_1y,
            "revenue_90d": revenue_90d,
            "revenue_1y": revenue_1y,
            "holder_revenue_30d": holder_revenue_30d,
            "holder_revenue_90d": holder_revenue_90d,
            "holder_revenue_1y": holder_revenue_1y,
            "growth_90d": growth_90d,
            "growth_1y": growth_1y,
            "annualized_fees": annualized_fees,
            "annualized_revenue": annualized_revenue,
            "fees_24h": fees_24h,
            "revenue_24h": revenue_24h,
            "dex_volume_24h": dex_volume_24h,
            "unique_traders_24h": None,
            "pool_depth_2pct_usd": None,
            "swap_count_24h": None,
            "intent_fill_rate": None,
            "aggregator_volume_share": None,
        }
        return {
            tier: {metric: metric_values.get(metric) for metric in metrics}
            for tier, metrics in DEX_SECTOR_METRICS.items()
        }

    def _build_dex_derived_metrics(
        self,
        *,
        tvl: float | None,
        market_cap: float | None,
        dex_volume_30d: float | None,
        fees_30d: float | None,
        revenue_30d: float | None,
    ) -> dict[str, dict[str, float | None]]:
        metric_values: dict[str, float | None] = {
            "volume_to_tvl_ratio_30d": (
                (dex_volume_30d / tvl)
                if dex_volume_30d is not None and tvl and tvl > 0
                else None
            ),
            "fees_to_volume_ratio_30d": (
                (fees_30d / dex_volume_30d)
                if fees_30d is not None and dex_volume_30d and dex_volume_30d > 0
                else None
            ),
            "revenue_to_volume_ratio_30d": (
                (revenue_30d / dex_volume_30d)
                if revenue_30d is not None and dex_volume_30d and dex_volume_30d > 0
                else None
            ),
            "revenue_to_fees_ratio_30d": (
                (revenue_30d / fees_30d)
                if revenue_30d is not None and fees_30d and fees_30d > 0
                else None
            ),
            "mcap_to_volume_ratio_30d": (
                (market_cap / dex_volume_30d)
                if market_cap is not None and dex_volume_30d and dex_volume_30d > 0
                else None
            ),
            "traders_to_tvl_efficiency": None,
            "organic_volume_ratio": None,
            "wash_trade_risk_score": None,
        }
        return {
            tier: {metric: metric_values.get(metric) for metric in metrics}
            for tier, metrics in DEX_DERIVED_METRICS.items()
        }

    def _build_dex_quality_layer(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
    ) -> dict[str, Any]:
        metric_values: dict[str, float | None] = {}
        for grouped in (sector_metrics, derived_metrics):
            for tier_values in grouped.values():
                for key, value in (tier_values or {}).items():
                    if key not in metric_values:
                        metric_values[key] = value

        def _status(score: float) -> str:
            if score >= 0.8:
                return "sufficient"
            if score >= 0.5:
                return "partial"
            return "insufficient"

        def _coverage(required: list[str]) -> dict[str, Any]:
            available = [metric for metric in required if metric_values.get(metric) is not None]
            missing = [metric for metric in required if metric_values.get(metric) is None]
            total = len(required)
            score = (len(available) / total) if total > 0 else 1.0
            return {
                "required": required,
                "available": available,
                "missing": missing,
                "score": round(score, 3),
                "status": _status(score),
            }

        cov_30d = _coverage(
            [
                "dex_volume_30d",
                "fees_30d",
                "revenue_30d",
                "growth_30d",
            ]
        )
        cov_90d = _coverage(
            [
                "dex_volume_90d",
                "fees_90d",
                "revenue_90d",
                "growth_90d",
            ]
        )
        cov_1y = _coverage(
            [
                "dex_volume_1y",
                "fees_1y",
                "revenue_1y",
                "growth_1y",
            ]
        )

        long_horizon_score = round(
            (cov_30d["score"] * 0.5) + (cov_90d["score"] * 0.3) + (cov_1y["score"] * 0.2),
            3,
        )
        if cov_30d["status"] == "sufficient" and long_horizon_score >= 0.7:
            confidence = "sufficient"
        elif cov_30d["status"] != "insufficient" and long_horizon_score >= 0.5:
            confidence = "partial"
        else:
            confidence = "insufficient"

        return {
            "primary_horizon": "30d",
            "horizon_coverage": {
                "30d": cov_30d,
                "90d": cov_90d,
                "1y": cov_1y,
            },
            "long_horizon_score": long_horizon_score,
            "long_horizon_confidence": confidence,
            "enough_for_fundamental_conclusion": confidence == "sufficient",
            "rule": "30d is primary minimum, 90d is important, 1y is long-range when available; 24h is secondary context only.",
        }

    def _build_dex_flat_metrics(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
        include_non_dex_defaults: bool,
    ) -> dict[str, float]:
        flat: dict[str, float] = {}
        tiers = ("must", "should") if not include_non_dex_defaults else ("must",)
        for tier in tiers:
            for key, value in (sector_metrics.get(tier) or {}).items():
                if value is not None:
                    flat[key] = value
            for key, value in (derived_metrics.get(tier) or {}).items():
                if value is not None:
                    flat[key] = value

        dex_volume_30d = _safe_float(flat.get("dex_volume_30d"))
        revenue_30d = _safe_float(flat.get("revenue_30d"))
        if dex_volume_30d is not None:
            flat["volume_30d"] = dex_volume_30d
        if revenue_30d is not None:
            flat["protocol_income_30d"] = revenue_30d
        return flat

    def _build_dex_competitor_comparison(
        self,
        *,
        competitors: list[dict[str, Any]],
        target_snapshot: dict[str, Any],
        max_peers: int,
    ) -> dict[str, Any]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        target_row: dict[str, Any] | None = None

        def _key(row: dict[str, Any]) -> str:
            return str(row.get("slug") or "").strip().lower() or str(row.get("name") or "").strip().lower()

        for row in competitors:
            key = _key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            compact = {
                "name": row.get("name"),
                "slug": row.get("slug"),
                "is_target": bool(row.get("is_target")),
                "tvl": _safe_float(row.get("tvl")),
                "tvl_rank": row.get("tvl_rank"),
                "dex_volume_30d": _safe_float(row.get("dex_volume_30d")),
                "dex_volume_30d_rank": row.get("dex_volume_30d_rank"),
                "fees_30d": _safe_float(row.get("fees_30d")),
                "fees_30d_rank": row.get("fees_30d_rank"),
                "revenue_30d": _safe_float(row.get("revenue_30d")),
                "revenue_30d_rank": row.get("revenue_30d_rank"),
                "growth_30d": _safe_float(row.get("growth_30d")),
                "growth_30d_rank": row.get("growth_30d_rank"),
            }
            normalized.append({k: v for k, v in compact.items() if v is not None or k in {"name", "slug", "is_target"}})
            if compact["is_target"]:
                target_row = compact

        if target_row is None:
            target_row = {
                "name": target_snapshot.get("name"),
                "slug": target_snapshot.get("slug"),
                "is_target": True,
                "tvl": _safe_float(target_snapshot.get("tvl")),
                "dex_volume_30d": _safe_float(target_snapshot.get("dex_volume_30d")),
                "fees_30d": _safe_float(target_snapshot.get("fees_30d")),
                "revenue_30d": _safe_float(target_snapshot.get("revenue_30d")),
                "growth_30d": _safe_float(target_snapshot.get("growth_30d")),
            }

        peers = [row for row in normalized if not row.get("is_target")]
        target_name_l = str(target_row.get("name") or "").strip().lower()
        target_slug_l = str(target_row.get("slug") or "").strip().lower()
        if target_name_l or target_slug_l:
            filtered_peers: list[dict[str, Any]] = []
            for row in peers:
                peer_name_l = str(row.get("name") or "").strip().lower()
                peer_slug_l = str(row.get("slug") or "").strip().lower()
                same_name_family = bool(target_name_l and peer_name_l and peer_name_l.startswith(target_name_l))
                same_slug_family = bool(target_slug_l and peer_slug_l and peer_slug_l.startswith(target_slug_l))
                if same_name_family or same_slug_family:
                    continue
                filtered_peers.append(row)
            peers = filtered_peers

        peers.sort(
            key=lambda row: (
                int(row.get("tvl_rank") or 10_000),
                -(float(row.get("tvl") or 0.0)),
            )
        )
        deduped_peers: list[dict[str, Any]] = []
        seen_peer_families: set[str] = set()

        def _peer_family(slug: str, name: str) -> str:
            slug_l = slug.strip().lower()
            if "-v" in slug_l:
                prefix, suffix = slug_l.rsplit("-v", 1)
                if suffix and suffix[0].isdigit():
                    return prefix
            return slug_l or name.strip().lower()

        for row in peers:
            family = _peer_family(str(row.get("slug") or ""), str(row.get("name") or ""))
            if family and family in seen_peer_families:
                continue
            if family:
                seen_peer_families.add(family)
            deduped_peers.append(row)
            if len(deduped_peers) >= max_peers:
                break

        selected_projects = [
            {k: v for k, v in target_row.items() if v is not None or k in {"name", "slug", "is_target"}}
        ] + deduped_peers

        def _rank_from_normalized(metric: str, target_metric: float | None) -> int | None:
            if target_metric is None:
                return None
            higher = 0
            for row in normalized:
                if row.get("is_target"):
                    continue
                row_val = _safe_float(row.get(metric))
                if row_val is not None and row_val > target_metric:
                    higher += 1
            return higher + 1

        target_ranks = {
            "tvl_rank": target_row.get("tvl_rank")
            or _rank_from_normalized("tvl", _safe_float(target_row.get("tvl"))),
            "dex_volume_30d_rank": target_row.get("dex_volume_30d_rank")
            or _rank_from_normalized("dex_volume_30d", _safe_float(target_row.get("dex_volume_30d"))),
            "fees_30d_rank": target_row.get("fees_30d_rank")
            or _rank_from_normalized("fees_30d", _safe_float(target_row.get("fees_30d"))),
            "revenue_30d_rank": target_row.get("revenue_30d_rank")
            or _rank_from_normalized("revenue_30d", _safe_float(target_row.get("revenue_30d"))),
            "growth_30d_rank": target_row.get("growth_30d_rank")
            or _rank_from_normalized("growth_30d", _safe_float(target_row.get("growth_30d"))),
            "price_impact_rank": None,
        }
        return {
            "projects": selected_projects[: max_peers + 1],
            "target_ranks": target_ranks,
            "universe_size": len(normalized),
        }

    def _build_perp_sector_metrics(
        self,
        *,
        perp: dict[str, Any],
    ) -> dict[str, dict[str, float | None]]:
        metric_values: dict[str, float | None] = {
            "open_interest_usd": _safe_float(perp.get("open_interest_usd")),
            "fees_30d": _safe_float(perp.get("fees_30d")),
            "revenue_30d": _safe_float(perp.get("revenue_30d")),
            "open_interest_share_30d": _safe_float(perp.get("open_interest_share_30d")),
            "growth_30d": _safe_float(perp.get("growth_30d")),
            "perp_volume_30d": _safe_float(perp.get("perp_volume_30d")),
            "open_interest_30d": _safe_float(perp.get("open_interest_30d")),
            "open_interest_1y": _safe_float(perp.get("open_interest_1y")),
            "fees_90d": _safe_float(perp.get("fees_90d")),
            "fees_1y": _safe_float(perp.get("fees_1y")),
            "revenue_90d": _safe_float(perp.get("revenue_90d")),
            "revenue_1y": _safe_float(perp.get("revenue_1y")),
            "active_users_30d": _safe_float(perp.get("active_users_30d")),
            "growth_90d": _safe_float(perp.get("growth_90d")),
            "growth_1y": _safe_float(perp.get("growth_1y")),
            "annualized_fees": _safe_float(perp.get("annualized_fees")),
            "annualized_revenue": _safe_float(perp.get("annualized_revenue")),
            "funding_rate": _safe_float(perp.get("funding_rate")),
            "liquidations_30d": _safe_float(perp.get("liquidations_30d")),
            "active_traders_30d": _safe_float(perp.get("active_traders_30d")),
            "market_depth_usd": _safe_float(perp.get("market_depth_usd")),
            "retention_30d": _safe_float(perp.get("retention_30d")),
            "insurance_fund_usd": _safe_float(perp.get("insurance_fund_usd")),
        }
        return {
            tier: {metric: metric_values.get(metric) for metric in metrics}
            for tier, metrics in PERP_SECTOR_METRICS.items()
        }

    def _build_perp_derived_metrics(
        self,
        *,
        perp: dict[str, Any],
    ) -> dict[str, dict[str, float | None]]:
        fees_30d = _safe_float(perp.get("fees_30d"))
        revenue_30d = _safe_float(perp.get("revenue_30d"))
        protocol_revenue_30d = _safe_float(perp.get("protocol_revenue_30d"))
        open_interest_usd = _safe_float(perp.get("open_interest_usd"))
        active_users_30d = _safe_float(perp.get("active_users_30d"))
        open_interest_change_30d = _safe_float(perp.get("open_interest_change_30d"))
        liquidations_30d = _safe_float(perp.get("liquidations_30d"))
        funding_rate = _safe_float(perp.get("funding_rate"))
        market_depth_usd = _safe_float(perp.get("market_depth_usd"))

        metric_values: dict[str, float | None] = {
            "revenue_to_fees_ratio_30d": (
                (revenue_30d / fees_30d)
                if revenue_30d is not None and fees_30d and fees_30d > 0
                else None
            ),
            "fees_to_open_interest_ratio_30d": (
                (fees_30d / open_interest_usd)
                if fees_30d is not None and open_interest_usd and open_interest_usd > 0
                else None
            ),
            "revenue_to_open_interest_ratio_30d": (
                (revenue_30d / open_interest_usd)
                if revenue_30d is not None and open_interest_usd and open_interest_usd > 0
                else None
            ),
            "protocol_revenue_margin_30d": (
                (protocol_revenue_30d / revenue_30d)
                if protocol_revenue_30d is not None and revenue_30d and revenue_30d > 0
                else None
            ),
            "fee_per_active_user_30d": (
                (fees_30d / active_users_30d)
                if fees_30d is not None and active_users_30d and active_users_30d > 0
                else None
            ),
            "open_interest_change_30d": open_interest_change_30d,
            "liquidation_to_open_interest_ratio": (
                (liquidations_30d / open_interest_usd)
                if liquidations_30d is not None and open_interest_usd and open_interest_usd > 0
                else None
            ),
            "funding_rate_annualized": (funding_rate * 365.0) if funding_rate is not None else None,
            "depth_to_open_interest_ratio": (
                (market_depth_usd / open_interest_usd)
                if market_depth_usd is not None and open_interest_usd and open_interest_usd > 0
                else None
            ),
        }
        return {
            tier: {metric: metric_values.get(metric) for metric in metrics}
            for tier, metrics in PERP_DERIVED_METRICS.items()
        }

    def _build_perp_quality_layer(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
    ) -> dict[str, Any]:
        metric_values: dict[str, float | None] = {}
        for grouped in (sector_metrics, derived_metrics):
            for tier_values in grouped.values():
                for key, value in (tier_values or {}).items():
                    if key not in metric_values:
                        metric_values[key] = value

        def _status(score: float) -> str:
            if score >= 0.8:
                return "sufficient"
            if score >= 0.5:
                return "partial"
            return "insufficient"

        def _coverage(required: list[str]) -> dict[str, Any]:
            available = [metric for metric in required if metric_values.get(metric) is not None]
            missing = [metric for metric in required if metric_values.get(metric) is None]
            total = len(required)
            score = (len(available) / total) if total > 0 else 1.0
            return {
                "required": required,
                "available": available,
                "missing": missing,
                "score": round(score, 3),
                "status": _status(score),
            }

        cov_30d = _coverage(
            [
                "open_interest_usd",
                "fees_30d",
                "revenue_30d",
                "open_interest_share_30d",
                "growth_30d",
            ]
        )
        cov_90d = _coverage(
            [
                "fees_90d",
                "revenue_90d",
                "growth_90d",
                "open_interest_30d",
            ]
        )
        cov_1y = _coverage(
            [
                "fees_1y",
                "revenue_1y",
                "growth_1y",
                "open_interest_1y",
            ]
        )

        long_horizon_score = round(
            (cov_30d["score"] * 0.5) + (cov_90d["score"] * 0.3) + (cov_1y["score"] * 0.2),
            3,
        )
        if cov_30d["status"] == "sufficient" and long_horizon_score >= 0.7:
            confidence = "sufficient"
        elif cov_30d["status"] != "insufficient" and long_horizon_score >= 0.5:
            confidence = "partial"
        else:
            confidence = "insufficient"

        return {
            "primary_horizon": "30d",
            "horizon_coverage": {
                "30d": cov_30d,
                "90d": cov_90d,
                "1y": cov_1y,
            },
            "long_horizon_score": long_horizon_score,
            "long_horizon_confidence": confidence,
            "enough_for_fundamental_conclusion": confidence == "sufficient",
            "rule": "30d is primary minimum, 90d is important, 1y is long-range when available; 24h is secondary context only.",
        }

    def _build_perp_flat_metrics(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
        include_non_perp_defaults: bool,
    ) -> dict[str, float]:
        flat: dict[str, float] = {}
        tiers = ("must", "should") if not include_non_perp_defaults else ("must",)
        for tier in tiers:
            for key, value in (sector_metrics.get(tier) or {}).items():
                if value is not None:
                    flat[key] = value
            for key, value in (derived_metrics.get(tier) or {}).items():
                if value is not None:
                    flat[key] = value

        if _safe_float(flat.get("revenue_30d")) is not None:
            flat["protocol_income_30d"] = _safe_float(flat.get("revenue_30d"))  # type: ignore[assignment]
        if _safe_float(flat.get("perp_volume_30d")) is not None:
            flat["volume_30d"] = _safe_float(flat.get("perp_volume_30d"))  # type: ignore[assignment]
        return flat

    def _build_perp_competitor_comparison(
        self,
        *,
        competitors: list[dict[str, Any]],
        target_snapshot: dict[str, Any],
        max_peers: int,
    ) -> dict[str, Any]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        target_row: dict[str, Any] | None = None

        def _key(row: dict[str, Any]) -> str:
            return str(row.get("slug") or "").strip().lower() or str(row.get("name") or "").strip().lower()

        for row in competitors:
            key = _key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            compact = {
                "name": row.get("name"),
                "slug": row.get("slug"),
                "is_target": bool(row.get("is_target")),
                "open_interest_usd": _safe_float(row.get("open_interest_usd")),
                "open_interest_rank": row.get("open_interest_rank"),
                "open_interest_share_30d": _safe_float(row.get("open_interest_share_30d")),
                "open_interest_share_30d_rank": row.get("open_interest_share_30d_rank"),
                "perp_volume_30d": _safe_float(row.get("perp_volume_30d")),
                "perp_volume_30d_rank": row.get("perp_volume_30d_rank"),
                "fees_30d": _safe_float(row.get("fees_30d")),
                "fees_30d_rank": row.get("fees_30d_rank"),
                "revenue_30d": _safe_float(row.get("revenue_30d")),
                "revenue_30d_rank": row.get("revenue_30d_rank"),
                "growth_30d": _safe_float(row.get("growth_30d")),
                "growth_30d_rank": row.get("growth_30d_rank"),
                "active_users_30d": _safe_float(row.get("active_users_30d")),
                "active_users_30d_rank": row.get("active_users_30d_rank"),
                "funding_rate": _safe_float(row.get("funding_rate")),
                "liquidations_30d": _safe_float(row.get("liquidations_30d")),
            }
            normalized.append(
                {
                    k: v
                    for k, v in compact.items()
                    if v is not None or k in {"name", "slug", "is_target"}
                }
            )
            if compact["is_target"]:
                target_row = compact

        if target_row is None:
            target_row = {
                "name": target_snapshot.get("name"),
                "slug": target_snapshot.get("slug"),
                "is_target": True,
                "open_interest_usd": _safe_float(target_snapshot.get("open_interest_usd")),
                "open_interest_share_30d": _safe_float(target_snapshot.get("open_interest_share_30d")),
                "perp_volume_30d": _safe_float(target_snapshot.get("perp_volume_30d")),
                "fees_30d": _safe_float(target_snapshot.get("fees_30d")),
                "revenue_30d": _safe_float(target_snapshot.get("revenue_30d")),
                "growth_30d": _safe_float(target_snapshot.get("growth_30d")),
                "active_users_30d": _safe_float(target_snapshot.get("active_users_30d")),
            }

        peers = [row for row in normalized if not row.get("is_target")]
        peers.sort(
            key=lambda row: (
                int(row.get("open_interest_rank") or 10_000),
                -(float(row.get("open_interest_usd") or 0.0)),
            )
        )
        selected_peers = peers[:max_peers]
        selected_projects = [
            {
                k: v
                for k, v in target_row.items()
                if v is not None or k in {"name", "slug", "is_target"}
            }
        ] + selected_peers

        def _rank_from_normalized(metric: str, target_metric: float | None) -> int | None:
            if target_metric is None:
                return None
            higher = 0
            for row in normalized:
                if row.get("is_target"):
                    continue
                row_val = _safe_float(row.get(metric))
                if row_val is not None and row_val > target_metric:
                    higher += 1
            return higher + 1

        target_ranks = {
            "open_interest_rank": target_row.get("open_interest_rank")
            or _rank_from_normalized("open_interest_usd", _safe_float(target_row.get("open_interest_usd"))),
            "fees_30d_rank": target_row.get("fees_30d_rank")
            or _rank_from_normalized("fees_30d", _safe_float(target_row.get("fees_30d"))),
            "revenue_30d_rank": target_row.get("revenue_30d_rank")
            or _rank_from_normalized("revenue_30d", _safe_float(target_row.get("revenue_30d"))),
            "open_interest_share_30d_rank": target_row.get("open_interest_share_30d_rank")
            or _rank_from_normalized(
                "open_interest_share_30d",
                _safe_float(target_row.get("open_interest_share_30d")),
            ),
            "growth_30d_rank": target_row.get("growth_30d_rank")
            or _rank_from_normalized("growth_30d", _safe_float(target_row.get("growth_30d"))),
            "active_users_30d_rank": target_row.get("active_users_30d_rank")
            or _rank_from_normalized("active_users_30d", _safe_float(target_row.get("active_users_30d"))),
            "perp_volume_30d_rank": target_row.get("perp_volume_30d_rank")
            or _rank_from_normalized("perp_volume_30d", _safe_float(target_row.get("perp_volume_30d"))),
            "funding_competitiveness": None,
            "liquidation_intensity_percentile": None,
        }
        return {
            "projects": selected_projects[: max_peers + 1],
            "target_ranks": target_ranks,
            "universe_size": len(normalized),
        }

    def _build_perp_gaps(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
        competitor_comparison: dict[str, Any],
        is_perp_sector: bool,
    ) -> list[dict[str, str]]:
        if not is_perp_sector:
            return []

        gaps: list[dict[str, str]] = []

        def _append_metric_gap(group: str, tier: str, metric: str) -> None:
            reason = self._perp_gap_reason(metric=metric, group=group, tier=tier)
            gaps.append(
                {
                    "group": group,
                    "priority": tier,
                    "metric": metric,
                    "reason": reason,
                }
            )

        for tier, tier_metrics in PERP_SECTOR_METRICS.items():
            for metric in tier_metrics:
                if sector_metrics.get(tier, {}).get(metric) is None:
                    _append_metric_gap("sector_metrics", tier, metric)

        for tier, tier_metrics in PERP_DERIVED_METRICS.items():
            for metric in tier_metrics:
                if derived_metrics.get(tier, {}).get(metric) is None:
                    _append_metric_gap("derived_metrics", tier, metric)

        target_ranks = competitor_comparison.get("target_ranks") or {}
        for tier, tier_metrics in PERP_COMPETITOR_METRICS.items():
            for metric in tier_metrics:
                if target_ranks.get(metric) is None:
                    _append_metric_gap("competitor_comparison", tier, metric)

        if sector_metrics.get("should", {}).get("perp_volume_30d") is None:
            _append_metric_gap("gaps", "must", "missing_perp_volume_dataset")
        if sector_metrics.get("optional_later", {}).get("active_traders_30d") is None:
            _append_metric_gap("gaps", "should", "missing_active_trader_dataset")
        if sector_metrics.get("optional_later", {}).get("liquidations_30d") is None:
            _append_metric_gap("gaps", "should", "missing_liquidation_dataset")
        if sector_metrics.get("optional_later", {}).get("retention_30d") is None:
            _append_metric_gap("gaps", "optional_later", "missing_retention_dataset")
        if sector_metrics.get("optional_later", {}).get("market_depth_usd") is None:
            _append_metric_gap("gaps", "optional_later", "missing_orderbook_depth")
        if sector_metrics.get("optional_later", {}).get("funding_rate") is None:
            _append_metric_gap("gaps", "optional_later", "missing_funding_rate_dataset")
        return gaps

    def _perp_gap_reason(self, *, metric: str, group: str, tier: str) -> str:
        if tier == "optional_later":
            return "Deferred by scope (optional_later), not targeted in first perp_dex implementation."

        reasons = {
            "open_interest_usd": "Open interest baseline is required for perp positioning and leverage footprint.",
            "fees_30d": "30d fees are required for long-horizon perp business throughput.",
            "revenue_30d": "30d protocol revenue is required for long-horizon monetization baseline.",
            "open_interest_share_30d": "30d open-interest share is required for perp market-position context.",
            "growth_30d": "Primary growth metric requires at least 30d history (OI/revenue/fees basis).",
            "perp_volume_30d": "Public DefiLlama derivatives volume endpoint is paid-gated in current source stack.",
            "open_interest_30d": "Requires 30d open-interest aggregate history per protocol.",
            "open_interest_1y": "Requires 1y open-interest aggregate history per protocol.",
            "fees_90d": "Requires 90d fee history for medium-horizon checks.",
            "fees_1y": "Requires 1y fee history for long-cycle checks.",
            "revenue_90d": "Requires 90d revenue history for medium-horizon checks.",
            "revenue_1y": "Requires 1y revenue history for long-cycle checks.",
            "active_users_30d": "Protocol-level active user/trader dataset is inconsistent for perp protocols in current stack.",
            "growth_90d": "Requires 90d historical series with enough coverage.",
            "growth_1y": "Requires 1y historical series with enough coverage.",
            "annualized_fees": "Cannot annualize fees reliably without 30d fees baseline.",
            "annualized_revenue": "Cannot annualize revenue reliably without 30d revenue baseline.",
            "revenue_to_fees_ratio_30d": "Cannot compute without fees_30d and revenue_30d.",
            "fees_to_open_interest_ratio_30d": "Cannot compute without fees_30d and open_interest_usd.",
            "revenue_to_open_interest_ratio_30d": "Cannot compute without revenue_30d and open_interest_usd.",
            "protocol_revenue_margin_30d": "Cannot compute without protocol_revenue_30d and revenue_30d.",
            "fee_per_active_user_30d": "Cannot compute without active_users_30d.",
            "open_interest_change_30d": "Requires 30d open-interest growth series.",
            "open_interest_rank": "Peer open-interest ranking is unavailable from current source stack.",
            "fees_30d_rank": "Peer-comparable 30d fees are unavailable for enough perp competitors.",
            "revenue_30d_rank": "Peer-comparable 30d revenue is unavailable for enough perp competitors.",
            "open_interest_share_30d_rank": "Peer-comparable OI share ranks are unavailable for enough perp competitors.",
            "growth_30d_rank": "Peer-comparable 30d growth is unavailable for enough perp competitors.",
            "active_users_30d_rank": "Peer-comparable active-user metrics are unavailable for enough perp competitors.",
            "perp_volume_30d_rank": "Perp volume ranking requires paid-gated derivatives volume endpoint.",
            "missing_perp_volume_dataset": "Derivatives volume endpoint is paid-gated on public DefiLlama API in current stack.",
            "missing_active_trader_dataset": "Active trader dataset is not consistently available for perp protocols.",
            "missing_liquidation_dataset": "Protocol-level liquidation dataset is not available in current source stack.",
            "missing_orderbook_depth": "Orderbook depth/liquidity quality feeds are not available in current source stack.",
            "missing_retention_dataset": "Retention datasets are not available in the current source stack.",
            "missing_funding_rate_dataset": "Funding rate datasets are not exposed in current source stack for broad perp coverage.",
        }
        reason = reasons.get(metric)
        if reason:
            return reason
        if group == "competitor_comparison":
            return "Peer-comparable data for this ranking metric is not available in current source stack."
        return "Metric is unavailable from current sources for this run."

    def _build_l1_l2_sector_metrics(
        self,
        *,
        l1: dict[str, Any],
    ) -> dict[str, dict[str, float | None]]:
        metric_values: dict[str, float | None] = {
            "active_addresses_30d": _safe_float(l1.get("active_addresses_30d")),
            "fees_30d": _safe_float(l1.get("fees_30d")),
            "revenue_30d": _safe_float(l1.get("revenue_30d")),
            "stablecoin_supply_usd": _safe_float(l1.get("stablecoin_supply_usd")),
            "ecosystem_tvl": _safe_float(l1.get("ecosystem_tvl")),
            "growth_30d": _safe_float(l1.get("growth_30d")),
            "active_addresses_90d": _safe_float(l1.get("active_addresses_90d")),
            "active_addresses_1y": _safe_float(l1.get("active_addresses_1y")),
            "fees_90d": _safe_float(l1.get("fees_90d")),
            "fees_1y": _safe_float(l1.get("fees_1y")),
            "revenue_90d": _safe_float(l1.get("revenue_90d")),
            "revenue_1y": _safe_float(l1.get("revenue_1y")),
            "transactions_30d": _safe_float(l1.get("transactions_30d")),
            "ecosystem_tvl_growth_30d": _safe_float(l1.get("ecosystem_tvl_growth_30d")),
            "ecosystem_tvl_growth_90d": _safe_float(l1.get("ecosystem_tvl_growth_90d")),
            "ecosystem_tvl_growth_1y": _safe_float(l1.get("ecosystem_tvl_growth_1y")),
            "stablecoin_supply_growth_30d": _safe_float(l1.get("stablecoin_supply_growth_30d")),
            "app_count_30d": _safe_float(l1.get("app_count_30d")),
            "annualized_fees": _safe_float(l1.get("annualized_fees")),
            "annualized_revenue": _safe_float(l1.get("annualized_revenue")),
            "transactions_24h": _safe_float(l1.get("transactions_24h")),
            "transactions_90d": _safe_float(l1.get("transactions_90d")),
            "transactions_1y": _safe_float(l1.get("transactions_1y")),
            "active_addresses_24h": _safe_float(l1.get("active_addresses_24h")),
            "developers_30d": _safe_float(l1.get("developers_30d")),
            "retention_30d": _safe_float(l1.get("retention_30d")),
            "sequencer_uptime_pct": _safe_float(l1.get("sequencer_uptime_pct")),
            "blob_cost_usd_24h": _safe_float(l1.get("blob_cost_usd_24h")),
        }
        return {
            tier: {metric: metric_values.get(metric) for metric in metrics}
            for tier, metrics in L1L2_SECTOR_METRICS.items()
        }

    def _build_l1_l2_derived_metrics(
        self,
        *,
        l1: dict[str, Any],
    ) -> dict[str, dict[str, float | None]]:
        fees_30d = _safe_float(l1.get("fees_30d"))
        revenue_30d = _safe_float(l1.get("revenue_30d"))
        active_30d = _safe_float(l1.get("active_addresses_30d"))
        ecosystem_tvl = _safe_float(l1.get("ecosystem_tvl"))
        stable_supply = _safe_float(l1.get("stablecoin_supply_usd"))

        metric_values: dict[str, float | None] = {
            "fees_per_active_address_30d": (
                (fees_30d / active_30d)
                if fees_30d is not None and active_30d and active_30d > 0
                else None
            ),
            "revenue_to_fees_ratio_30d": (
                (revenue_30d / fees_30d)
                if revenue_30d is not None and fees_30d and fees_30d > 0
                else None
            ),
            "stablecoin_penetration_ratio": (
                (stable_supply / ecosystem_tvl)
                if stable_supply is not None and ecosystem_tvl and ecosystem_tvl > 0
                else None
            ),
            "fees_to_tvl_ratio_30d": (
                (fees_30d / ecosystem_tvl)
                if fees_30d is not None and ecosystem_tvl and ecosystem_tvl > 0
                else None
            ),
            "revenue_to_tvl_ratio_30d": (
                (revenue_30d / ecosystem_tvl)
                if revenue_30d is not None and ecosystem_tvl and ecosystem_tvl > 0
                else None
            ),
            "decentralization_score": None,
            "execution_cost_efficiency": None,
            "retention_quality_score": None,
        }
        return {
            tier: {metric: metric_values.get(metric) for metric in metrics}
            for tier, metrics in L1L2_DERIVED_METRICS.items()
        }

    def _build_l1_l2_quality_layer(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
    ) -> dict[str, Any]:
        metric_values: dict[str, float | None] = {}
        for grouped in (sector_metrics, derived_metrics):
            for tier_values in grouped.values():
                for key, value in (tier_values or {}).items():
                    if key not in metric_values:
                        metric_values[key] = value

        def _status(score: float) -> str:
            if score >= 0.8:
                return "sufficient"
            if score >= 0.5:
                return "partial"
            return "insufficient"

        def _coverage(required: list[str]) -> dict[str, Any]:
            available = [metric for metric in required if metric_values.get(metric) is not None]
            missing = [metric for metric in required if metric_values.get(metric) is None]
            total = len(required)
            score = (len(available) / total) if total > 0 else 1.0
            return {
                "required": required,
                "available": available,
                "missing": missing,
                "score": round(score, 3),
                "status": _status(score),
            }

        cov_30d = _coverage(
            [
                "active_addresses_30d",
                "fees_30d",
                "revenue_30d",
                "stablecoin_supply_usd",
                "ecosystem_tvl",
                "growth_30d",
            ]
        )
        cov_90d = _coverage(
            [
                "active_addresses_90d",
                "fees_90d",
                "revenue_90d",
                "growth_90d",
                "ecosystem_tvl_growth_90d",
            ]
        )
        cov_1y = _coverage(
            [
                "active_addresses_1y",
                "fees_1y",
                "revenue_1y",
                "growth_1y",
                "ecosystem_tvl_growth_1y",
            ]
        )

        long_horizon_score = round(
            (cov_30d["score"] * 0.5) + (cov_90d["score"] * 0.3) + (cov_1y["score"] * 0.2),
            3,
        )
        if cov_30d["status"] == "sufficient" and long_horizon_score >= 0.7:
            confidence = "sufficient"
        elif cov_30d["status"] != "insufficient" and long_horizon_score >= 0.5:
            confidence = "partial"
        else:
            confidence = "insufficient"

        return {
            "primary_horizon": "30d",
            "horizon_coverage": {
                "30d": cov_30d,
                "90d": cov_90d,
                "1y": cov_1y,
            },
            "long_horizon_score": long_horizon_score,
            "long_horizon_confidence": confidence,
            "enough_for_fundamental_conclusion": confidence == "sufficient",
            "rule": "30d is primary minimum, 90d is important, 1y is long-range when available; 24h is secondary context only.",
        }

    def _build_l1_l2_flat_metrics(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
        include_non_l1_defaults: bool,
    ) -> dict[str, float]:
        flat: dict[str, float] = {}
        tiers = ("must", "should") if not include_non_l1_defaults else ("must",)
        for tier in tiers:
            for key, value in (sector_metrics.get(tier) or {}).items():
                if value is not None:
                    flat[key] = value
            for key, value in (derived_metrics.get(tier) or {}).items():
                if value is not None:
                    flat[key] = value

        ecosystem_tvl = _safe_float(flat.get("ecosystem_tvl"))
        revenue_30d = _safe_float(flat.get("revenue_30d"))
        if ecosystem_tvl is not None:
            flat["tvl"] = ecosystem_tvl
        if revenue_30d is not None:
            flat["protocol_income_30d"] = revenue_30d
        return flat

    def _build_l1_l2_competitor_comparison(
        self,
        *,
        competitors: list[dict[str, Any]],
        target_snapshot: dict[str, Any],
        max_peers: int,
    ) -> dict[str, Any]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        target_row: dict[str, Any] | None = None

        def _key(row: dict[str, Any]) -> str:
            return str(row.get("slug") or "").strip().lower() or str(row.get("name") or "").strip().lower()

        for row in competitors:
            key = _key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            compact = {
                "name": row.get("name"),
                "slug": row.get("slug"),
                "is_target": bool(row.get("is_target")),
                "ecosystem_tvl": _safe_float(row.get("ecosystem_tvl")),
                "ecosystem_tvl_rank": row.get("ecosystem_tvl_rank"),
                "active_addresses_30d": _safe_float(row.get("active_addresses_30d")),
                "active_addresses_30d_rank": row.get("active_addresses_30d_rank"),
                "fees_30d": _safe_float(row.get("fees_30d")),
                "fees_30d_rank": row.get("fees_30d_rank"),
                "revenue_30d": _safe_float(row.get("revenue_30d")),
                "revenue_30d_rank": row.get("revenue_30d_rank"),
                "stablecoin_supply_usd": _safe_float(row.get("stablecoin_supply_usd")),
                "stablecoin_supply_rank": row.get("stablecoin_supply_rank"),
                "growth_30d": _safe_float(row.get("growth_30d")),
                "growth_30d_rank": row.get("growth_30d_rank"),
                "app_count_30d": _safe_float(row.get("app_count_30d")),
                "app_count_30d_rank": row.get("app_count_30d_rank"),
                "transactions_30d": _safe_float(row.get("transactions_30d")),
                "transactions_30d_rank": row.get("transactions_30d_rank"),
                "retention_rank": row.get("retention_rank"),
            }
            normalized.append(
                {
                    k: v
                    for k, v in compact.items()
                    if v is not None or k in {"name", "slug", "is_target"}
                }
            )
            if compact["is_target"]:
                target_row = compact

        if target_row is None:
            target_row = {
                "name": target_snapshot.get("name"),
                "slug": target_snapshot.get("slug"),
                "is_target": True,
                "ecosystem_tvl": _safe_float(target_snapshot.get("ecosystem_tvl")),
                "active_addresses_30d": _safe_float(target_snapshot.get("active_addresses_30d")),
                "fees_30d": _safe_float(target_snapshot.get("fees_30d")),
                "revenue_30d": _safe_float(target_snapshot.get("revenue_30d")),
                "stablecoin_supply_usd": _safe_float(target_snapshot.get("stablecoin_supply_usd")),
                "growth_30d": _safe_float(target_snapshot.get("growth_30d")),
                "app_count_30d": _safe_float(target_snapshot.get("app_count_30d")),
            }

        peers = [row for row in normalized if not row.get("is_target")]
        peers.sort(
            key=lambda row: (
                int(row.get("ecosystem_tvl_rank") or 10_000),
                -(float(row.get("ecosystem_tvl") or 0.0)),
            )
        )
        selected_peers = peers[:max_peers]
        selected_projects = [
            {
                k: v
                for k, v in target_row.items()
                if v is not None or k in {"name", "slug", "is_target"}
            }
        ] + selected_peers

        def _rank_from_normalized(metric: str, target_metric: float | None) -> int | None:
            if target_metric is None:
                return None
            higher = 0
            for row in normalized:
                if row.get("is_target"):
                    continue
                row_val = _safe_float(row.get(metric))
                if row_val is not None and row_val > target_metric:
                    higher += 1
            return higher + 1

        target_ranks = {
            "ecosystem_tvl_rank": target_row.get("ecosystem_tvl_rank")
            or _rank_from_normalized("ecosystem_tvl", _safe_float(target_row.get("ecosystem_tvl"))),
            "active_addresses_30d_rank": target_row.get("active_addresses_30d_rank")
            or _rank_from_normalized(
                "active_addresses_30d",
                _safe_float(target_row.get("active_addresses_30d")),
            ),
            "fees_30d_rank": target_row.get("fees_30d_rank")
            or _rank_from_normalized("fees_30d", _safe_float(target_row.get("fees_30d"))),
            "stablecoin_supply_rank": target_row.get("stablecoin_supply_rank")
            or _rank_from_normalized(
                "stablecoin_supply_usd",
                _safe_float(target_row.get("stablecoin_supply_usd")),
            ),
            "revenue_30d_rank": target_row.get("revenue_30d_rank")
            or _rank_from_normalized("revenue_30d", _safe_float(target_row.get("revenue_30d"))),
            "growth_30d_rank": target_row.get("growth_30d_rank")
            or _rank_from_normalized("growth_30d", _safe_float(target_row.get("growth_30d"))),
            "app_count_30d_rank": target_row.get("app_count_30d_rank")
            or _rank_from_normalized("app_count_30d", _safe_float(target_row.get("app_count_30d"))),
            "transactions_30d_rank": target_row.get("transactions_30d_rank")
            or _rank_from_normalized(
                "transactions_30d",
                _safe_float(target_row.get("transactions_30d")),
            ),
            "retention_rank": target_row.get("retention_rank"),
        }
        return {
            "projects": selected_projects[: max_peers + 1],
            "target_ranks": target_ranks,
            "universe_size": len(normalized),
        }

    def _build_l1_l2_gaps(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
        competitor_comparison: dict[str, Any],
        is_l1_l2_sector: bool,
    ) -> list[dict[str, str]]:
        if not is_l1_l2_sector:
            return []

        gaps: list[dict[str, str]] = []

        def _append_metric_gap(group: str, tier: str, metric: str) -> None:
            reason = self._l1_l2_gap_reason(metric=metric, group=group, tier=tier)
            gaps.append(
                {
                    "group": group,
                    "priority": tier,
                    "metric": metric,
                    "reason": reason,
                }
            )

        for tier, tier_metrics in L1L2_SECTOR_METRICS.items():
            for metric in tier_metrics:
                if sector_metrics.get(tier, {}).get(metric) is None:
                    _append_metric_gap("sector_metrics", tier, metric)

        for tier, tier_metrics in L1L2_DERIVED_METRICS.items():
            for metric in tier_metrics:
                if derived_metrics.get(tier, {}).get(metric) is None:
                    _append_metric_gap("derived_metrics", tier, metric)

        target_ranks = competitor_comparison.get("target_ranks") or {}
        for tier, tier_metrics in L1L2_COMPETITOR_METRICS.items():
            for metric in tier_metrics:
                if target_ranks.get(metric) is None:
                    _append_metric_gap("competitor_comparison", tier, metric)

        if int(competitor_comparison.get("universe_size") or 0) <= 1:
            _append_metric_gap("gaps", "must", "missing_chain_coverage")
        if sector_metrics.get("should", {}).get("transactions_30d") is None:
            _append_metric_gap("gaps", "must", "missing_transactions_dataset")
        if sector_metrics.get("optional_later", {}).get("developers_30d") is None:
            _append_metric_gap("gaps", "should", "missing_developer_dataset")
        if sector_metrics.get("optional_later", {}).get("retention_30d") is None:
            _append_metric_gap("gaps", "should", "missing_retention_dataset")
        if (
            sector_metrics.get("optional_later", {}).get("sequencer_uptime_pct") is None
            and sector_metrics.get("optional_later", {}).get("blob_cost_usd_24h") is None
        ):
            _append_metric_gap("gaps", "optional_later", "missing_sequencer_censorship_metrics")
        return gaps

    def _l1_l2_gap_reason(self, *, metric: str, group: str, tier: str) -> str:
        if tier == "optional_later":
            return "Deferred by scope (optional_later), not targeted in first l1_l2 implementation."

        reasons = {
            "active_addresses_30d": "30d active addresses are required as the primary long-horizon user baseline for chain demand.",
            "fees_30d": "30d fees are required for long-horizon business throughput and monetization baseline.",
            "revenue_30d": "30d protocol revenue is required for long-horizon monetization baseline.",
            "stablecoin_supply_usd": "Stablecoin supply on-chain is required to assess monetary depth and transactional utility.",
            "ecosystem_tvl": "Ecosystem TVL is required to assess capital depth on the chain.",
            "growth_30d": "Primary growth metric requires at least 30d history (active addresses/revenue/fees/tvl basis).",
            "active_addresses_90d": "Requires 90d active-user history for medium-horizon consistency checks.",
            "active_addresses_1y": "Requires 1y active-user history for long-cycle consistency checks.",
            "fees_90d": "Requires 90d fee history for medium-horizon consistency checks.",
            "fees_1y": "Requires 1y fee history for long-cycle consistency checks.",
            "revenue_90d": "Requires 90d revenue history for medium-horizon consistency checks.",
            "revenue_1y": "Requires 1y revenue history for long-cycle consistency checks.",
            "transactions_30d": "Reliable chain-level transactions dataset is not consistently available from the current source stack.",
            "ecosystem_tvl_growth_30d": "Requires sufficiently dense TVL history to compute 30d chain growth.",
            "ecosystem_tvl_growth_90d": "Requires sufficiently dense TVL history to compute 90d chain growth.",
            "ecosystem_tvl_growth_1y": "Requires sufficiently dense TVL history to compute 1y chain growth.",
            "stablecoin_supply_growth_30d": "Requires stablecoin supply time-series coverage for 30d delta.",
            "app_count_30d": "Requires consistent per-chain app-level activity dataset.",
            "annualized_fees": "Cannot annualize fees reliably without 30d fees baseline.",
            "annualized_revenue": "Cannot annualize revenue reliably without 30d revenue baseline.",
            "fees_per_active_address_30d": "Cannot compute without both fees_30d and active_addresses_30d.",
            "revenue_to_fees_ratio_30d": "Cannot compute without both revenue_30d and fees_30d.",
            "stablecoin_penetration_ratio": "Cannot compute without stablecoin_supply_usd and ecosystem_tvl.",
            "fees_to_tvl_ratio_30d": "Cannot compute without fees_30d and ecosystem_tvl.",
            "revenue_to_tvl_ratio_30d": "Cannot compute without revenue_30d and ecosystem_tvl.",
            "ecosystem_tvl_rank": "Peer chain coverage is insufficient to rank by ecosystem TVL.",
            "active_addresses_30d_rank": "Peer-comparable 30d active addresses are not available for enough chains.",
            "fees_30d_rank": "Peer-comparable 30d fees are not available for enough chains.",
            "stablecoin_supply_rank": "Peer-comparable stablecoin supply is not available for enough chains.",
            "revenue_30d_rank": "Peer-comparable 30d revenue is not available for enough chains.",
            "growth_30d_rank": "Peer-comparable 30d growth is not available for enough chains.",
            "app_count_30d_rank": "Peer-comparable app activity counts are not available for enough chains.",
            "transactions_30d_rank": "Peer-comparable transaction datasets are not consistently available.",
            "retention_rank": "Retention datasets are not available in the current source stack.",
            "missing_chain_coverage": "Competitor universe is too small for robust chain-level ranking.",
            "missing_transactions_dataset": "No stable and consistent public chain-level transactions dataset in current source stack.",
            "missing_developer_dataset": "Developer activity coverage is not available in the current source stack.",
            "missing_retention_dataset": "User retention/returning-user coverage is not available in the current source stack.",
            "missing_sequencer_censorship_metrics": "Sequencer uptime/censorship and blob-cost quality feeds are out of scope for v1 sources.",
        }
        reason = reasons.get(metric)
        if reason:
            return reason
        if group == "competitor_comparison":
            return "Peer-comparable data for this ranking metric is not available in current source stack."
        return "Metric is unavailable from current sources for this run."

    def _build_lending_competitor_comparison(
        self,
        *,
        competitors: list[dict[str, Any]],
        target_snapshot: dict[str, Any],
        max_peers: int,
    ) -> dict[str, Any]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        target_row: dict[str, Any] | None = None

        def _key(row: dict[str, Any]) -> str:
            return str(row.get("slug") or "").strip().lower() or str(row.get("name") or "").strip().lower()

        for row in competitors:
            key = _key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            compact = {
                "name": row.get("name"),
                "slug": row.get("slug"),
                "is_target": bool(row.get("is_target")),
                "tvl": _safe_float(row.get("tvl")),
                "tvl_rank": row.get("tvl_rank"),
                "fees_30d": _safe_float(row.get("fees_30d")),
                "fees_30d_rank": row.get("fees_30d_rank"),
                "revenue_30d": _safe_float(row.get("revenue_30d")),
                "revenue_30d_rank": row.get("revenue_30d_rank"),
                "growth_30d": _safe_float(row.get("growth_30d")),
                "growth_30d_rank": row.get("growth_30d_rank"),
                "fees_24h": _safe_float(row.get("fees_24h")),
                "revenue_24h": _safe_float(row.get("revenue_24h")),
                "change_1d": _safe_float(row.get("change_1d")),
                "change_7d": _safe_float(row.get("change_7d")),
                "borrowed_usd": _safe_float(row.get("borrowed_usd")),
                "utilization_rate": _safe_float(row.get("utilization_rate")),
                "avg_apy": _safe_float(row.get("avg_apy")),
            }
            normalized.append({k: v for k, v in compact.items() if v is not None or k in {"name", "slug", "is_target"}})
            if compact["is_target"]:
                target_row = compact

        if target_row is None:
            target_row = {
                "name": target_snapshot.get("name"),
                "slug": target_snapshot.get("slug"),
                "is_target": True,
                "tvl": _safe_float(target_snapshot.get("tvl")),
                "fees_30d": _safe_float(target_snapshot.get("fees_30d")),
                "revenue_30d": _safe_float(target_snapshot.get("revenue_30d")),
                "growth_30d": _safe_float(target_snapshot.get("growth_30d")),
                "borrowed_usd": _safe_float(target_snapshot.get("borrowed_usd")),
                "utilization_rate": _safe_float(target_snapshot.get("utilization_rate")),
                "avg_apy": _safe_float(target_snapshot.get("avg_apy")),
            }

        peers = [row for row in normalized if not row.get("is_target")]
        target_name_l = str(target_row.get("name") or "").strip().lower()
        target_slug_l = str(target_row.get("slug") or "").strip().lower()
        if target_name_l or target_slug_l:
            filtered_peers: list[dict[str, Any]] = []
            for row in peers:
                peer_name_l = str(row.get("name") or "").strip().lower()
                peer_slug_l = str(row.get("slug") or "").strip().lower()
                same_name_family = bool(target_name_l and peer_name_l and peer_name_l.startswith(target_name_l))
                same_slug_family = bool(target_slug_l and peer_slug_l and peer_slug_l.startswith(target_slug_l))
                if same_name_family or same_slug_family:
                    continue
                filtered_peers.append(row)
            peers = filtered_peers
        peers.sort(
            key=lambda row: (
                int(row.get("tvl_rank") or 10_000),
                -(float(row.get("tvl") or 0.0)),
            )
        )
        selected_peers = peers[:max_peers]
        selected_projects = [
            {k: v for k, v in target_row.items() if v is not None or k in {"name", "slug", "is_target"}}
        ] + selected_peers

        tvl_rank = target_row.get("tvl_rank")
        target_tvl = _safe_float(target_row.get("tvl"))
        if tvl_rank is None and target_tvl is not None:
            higher_tvl = 0
            for row in normalized:
                if row.get("is_target"):
                    continue
                row_tvl = _safe_float(row.get("tvl"))
                if row_tvl is not None and row_tvl > target_tvl:
                    higher_tvl += 1
            tvl_rank = higher_tvl + 1

        fees_30d_rank = target_row.get("fees_30d_rank")
        target_fees_30d = _safe_float(target_row.get("fees_30d"))
        if fees_30d_rank is None and target_fees_30d is not None:
            higher_fees = 0
            for row in normalized:
                if row.get("is_target"):
                    continue
                row_fees_30d = _safe_float(row.get("fees_30d"))
                if row_fees_30d is not None and row_fees_30d > target_fees_30d:
                    higher_fees += 1
            fees_30d_rank = higher_fees + 1

        revenue_30d_rank = target_row.get("revenue_30d_rank")
        target_revenue_30d = _safe_float(target_row.get("revenue_30d"))
        if revenue_30d_rank is None and target_revenue_30d is not None:
            higher_revenue = 0
            for row in normalized:
                if row.get("is_target"):
                    continue
                row_revenue_30d = _safe_float(row.get("revenue_30d"))
                if row_revenue_30d is not None and row_revenue_30d > target_revenue_30d:
                    higher_revenue += 1
            revenue_30d_rank = higher_revenue + 1

        growth_30d_rank = target_row.get("growth_30d_rank")
        target_growth_30d = _safe_float(target_row.get("growth_30d"))
        if growth_30d_rank is None and target_growth_30d is not None:
            higher_growth = 0
            for row in normalized:
                if row.get("is_target"):
                    continue
                row_growth_30d = _safe_float(row.get("growth_30d"))
                if row_growth_30d is not None and row_growth_30d > target_growth_30d:
                    higher_growth += 1
            growth_30d_rank = higher_growth + 1

        target_ranks = {
            "tvl_rank": tvl_rank,
            "fees_30d_rank": fees_30d_rank,
            "revenue_30d_rank": revenue_30d_rank,
            "growth_30d_rank": growth_30d_rank,
            "borrowed_usd_rank": None,
            "utilization_rank": None,
            "avg_apy_rank": None,
            "bad_debt_risk_rank": None,
        }
        return {
            "projects": selected_projects[: max_peers + 1],
            "target_ranks": target_ranks,
            "universe_size": len(normalized),
        }

    def _build_lending_gaps(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
        competitor_comparison: dict[str, Any],
        is_lending_sector: bool,
    ) -> list[dict[str, str]]:
        if not is_lending_sector:
            return []

        gaps: list[dict[str, str]] = []

        def _append_metric_gap(group: str, tier: str, metric: str) -> None:
            reason = self._lending_gap_reason(metric=metric, group=group, tier=tier)
            gaps.append(
                {
                    "group": group,
                    "priority": tier,
                    "metric": metric,
                    "reason": reason,
                }
            )

        for tier, tier_metrics in LENDING_SECTOR_METRICS.items():
            for metric in tier_metrics:
                if sector_metrics.get(tier, {}).get(metric) is None:
                    _append_metric_gap("sector_metrics", tier, metric)

        for tier, tier_metrics in LENDING_DERIVED_METRICS.items():
            for metric in tier_metrics:
                if derived_metrics.get(tier, {}).get(metric) is None:
                    _append_metric_gap("derived_metrics", tier, metric)

        target_ranks = competitor_comparison.get("target_ranks") or {}
        for tier, tier_metrics in LENDING_COMPETITOR_METRICS.items():
            for metric in tier_metrics:
                if target_ranks.get(metric) is None:
                    _append_metric_gap("competitor_comparison", tier, metric)
        return gaps

    def _build_dex_gaps(
        self,
        *,
        sector_metrics: dict[str, dict[str, float | None]],
        derived_metrics: dict[str, dict[str, float | None]],
        competitor_comparison: dict[str, Any],
        is_dex_spot_sector: bool,
    ) -> list[dict[str, str]]:
        if not is_dex_spot_sector:
            return []

        gaps: list[dict[str, str]] = []

        def _append_metric_gap(group: str, tier: str, metric: str) -> None:
            reason = self._dex_gap_reason(metric=metric, group=group, tier=tier)
            gaps.append(
                {
                    "group": group,
                    "priority": tier,
                    "metric": metric,
                    "reason": reason,
                }
            )

        for tier, tier_metrics in DEX_SECTOR_METRICS.items():
            for metric in tier_metrics:
                if sector_metrics.get(tier, {}).get(metric) is None:
                    _append_metric_gap("sector_metrics", tier, metric)

        for tier, tier_metrics in DEX_DERIVED_METRICS.items():
            for metric in tier_metrics:
                if derived_metrics.get(tier, {}).get(metric) is None:
                    _append_metric_gap("derived_metrics", tier, metric)

        target_ranks = competitor_comparison.get("target_ranks") or {}
        for tier, tier_metrics in DEX_COMPETITOR_METRICS.items():
            for metric in tier_metrics:
                if target_ranks.get(metric) is None:
                    _append_metric_gap("competitor_comparison", tier, metric)
        return gaps

    def _lending_gap_reason(self, *, metric: str, group: str, tier: str) -> str:
        if tier == "optional_later":
            return "Deferred by scope (optional_later), not targeted in first lending implementation."

        reasons = {
            "fees_30d": "30d fees are required for fundamental baseline; 24h fees are kept only as short-term context.",
            "fees_90d": "90d fees are required for medium-horizon business consistency checks.",
            "fees_1y": "1y fees are required for long-cycle resilience checks when history is available.",
            "revenue_30d": "30d protocol revenue is required for fundamental baseline; 24h revenue is not a substitute.",
            "revenue_90d": "90d protocol revenue is required for medium-horizon business consistency checks.",
            "revenue_1y": "1y protocol revenue is required for long-cycle resilience checks when history is available.",
            "holder_revenue_30d": "30d holder revenue is required for fundamental baseline; short-term snapshots are insufficient.",
            "holder_revenue_90d": "90d holder revenue is required for medium-horizon consistency checks.",
            "holder_revenue_1y": "1y holder revenue is required for long-cycle consistency checks when history is available.",
            "net_borrow_flow_30d": "Lending activity baseline needs 30d net borrow flow from borrowed time-series; 24h volume is not a replacement.",
            "borrowed_growth_30d": "Needs 30d borrowed balance history to measure lending-demand trend.",
            "volume_30d": "Volume is optional for lending and remains unavailable for many protocols in current source stack.",
            "growth_30d": "Primary growth metric requires at least 30d history (revenue/fees/tvl basis) and is unavailable for this run.",
            "growth_90d": "Requires 90d historical series with enough coverage.",
            "growth_1y": "Requires 1y historical series with enough coverage.",
            "annualized_revenue": "Cannot annualize reliably without 30d revenue baseline.",
            "annualized_holder_revenue": "Cannot annualize reliably without 30d holder revenue baseline.",
            "liquidations_24h": "No reliable protocol-level 24h liquidations feed in current DefiLlama/CoinGecko/Hub stack.",
            "bad_debt_usd": "Bad debt is not exposed consistently in current public endpoints for automated pull.",
            "reserve_factor": "Requires protocol-specific on-chain parameter extraction.",
            "isolation_mode_share": "Requires market-level on-chain risk mode decomposition.",
            "oracle_exposure_share": "Requires collateral-level oracle dependency mapping.",
            "bad_debt_to_tvl_ratio": "Cannot compute without bad_debt_usd.",
            "liquidations_to_borrowed_ratio": "Cannot compute without liquidations_24h.",
            "risk_adjusted_real_yield": "Needs external risk model and funding assumptions.",
            "capital_efficiency_score": "Needs custom scoring model across markets and collateral types.",
            "fees_30d_rank": "Comparable 30d fees are not available for all peers in current source stack.",
            "revenue_30d_rank": "Comparable 30d revenue is not available for all peers in current source stack.",
            "growth_30d_rank": "Comparable 30d growth is not available for all peers in current source stack.",
            "borrowed_usd_rank": "Borrowed USD by protocol is not available consistently for full peer universe.",
            "utilization_rank": "Utilization is not available consistently for peer protocols.",
            "avg_apy_rank": "Comparable APY snapshots across peer protocols are not consistently available.",
            "bad_debt_risk_rank": "Bad debt quality dataset is unavailable in current source stack.",
            "revenue_to_tvl_ratio_30d": "Cannot compute without revenue_30d baseline.",
        }
        reason = reasons.get(metric)
        if reason:
            return reason
        if group == "competitor_comparison":
            return "Peer-comparable data for this ranking metric is not available in current source stack."
        return "Metric is unavailable from current sources for this run."

    def _dex_gap_reason(self, *, metric: str, group: str, tier: str) -> str:
        if tier == "optional_later":
            return "Deferred by scope (optional_later), not targeted in first dex_spot implementation."

        reasons = {
            "dex_volume_30d": "30d DEX volume is required as the primary business throughput baseline.",
            "fees_30d": "30d fees are required for fundamental business quality checks on DEX.",
            "revenue_30d": "30d protocol revenue is required for fundamental business quality checks on DEX.",
            "growth_30d": "Primary growth metric requires at least 30d history (volume/fees/revenue/tvl basis).",
            "dex_volume_90d": "Requires 90d DEX volume history for medium-horizon consistency checks.",
            "dex_volume_1y": "Requires 1y DEX volume history for long-cycle consistency checks.",
            "fees_90d": "Requires 90d fee history for medium-horizon checks.",
            "fees_1y": "Requires 1y fee history for long-cycle checks.",
            "revenue_90d": "Requires 90d revenue history for medium-horizon checks.",
            "revenue_1y": "Requires 1y revenue history for long-cycle checks.",
            "holder_revenue_30d": "Holder revenue is not consistently available for all DEX protocols.",
            "holder_revenue_90d": "Holder revenue 90d is not consistently available for all DEX protocols.",
            "holder_revenue_1y": "Holder revenue 1y is not consistently available for all DEX protocols.",
            "growth_90d": "Requires 90d historical series with enough coverage.",
            "growth_1y": "Requires 1y historical series with enough coverage.",
            "annualized_fees": "Cannot annualize fees reliably without 30d fees baseline.",
            "annualized_revenue": "Cannot annualize revenue reliably without 30d revenue baseline.",
            "volume_to_tvl_ratio_30d": "Cannot compute without dex_volume_30d and tvl.",
            "fees_to_volume_ratio_30d": "Cannot compute without fees_30d and dex_volume_30d.",
            "revenue_to_volume_ratio_30d": "Cannot compute without revenue_30d and dex_volume_30d.",
            "revenue_to_fees_ratio_30d": "Cannot compute without revenue_30d and fees_30d.",
            "mcap_to_volume_ratio_30d": "Cannot compute without market_cap and dex_volume_30d.",
            "dex_volume_30d_rank": "Peer-comparable 30d DEX volume is not available for enough competitors.",
            "fees_30d_rank": "Peer-comparable 30d fees are not available for enough competitors.",
            "revenue_30d_rank": "Peer-comparable 30d revenue is not available for enough competitors.",
            "growth_30d_rank": "Peer-comparable 30d growth is not available for enough competitors.",
            "price_impact_rank": "Pool-level depth and impact datasets are out of scope in v1 source stack.",
        }
        reason = reasons.get(metric)
        if reason:
            return reason
        if group == "competitor_comparison":
            return "Peer-comparable data for this ranking metric is not available in current source stack."
        return "Metric is unavailable from current sources for this run."

    async def _fetch_fees_overview_index(self) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}

        async def _merge_endpoint(endpoint: str) -> None:
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.get(f"{self.base_url}/overview/{endpoint}")
                if resp.status_code != 200:
                    return
                data = resp.json() or {}
            except Exception:
                return

            protocols = data.get("protocols") or []
            for row in protocols:
                name = str(row.get("name") or "").strip().lower()
                slug = str(row.get("slug") or row.get("defillamaId") or "").strip().lower()
                row_payload: dict[str, Any] = {}

                if endpoint == "fees":
                    row_payload = {
                        "fees_24h": _safe_float(row.get("total24h") or row.get("dailyFees") or row.get("fees24h")),
                        "fees_30d": _safe_float(row.get("total30d")),
                        "fees_1y": _safe_float(row.get("total1y")),
                        "fees_growth_30d": self._normalize_percent_ratio(row.get("change_30dover30d")),
                    }
                elif endpoint == "revenue":
                    row_payload = {
                        "revenue_24h": _safe_float(row.get("total24h") or row.get("dailyRevenue") or row.get("revenue24h")),
                        "revenue_30d": _safe_float(row.get("total30d")),
                        "revenue_1y": _safe_float(row.get("total1y")),
                        "revenue_growth_30d": self._normalize_percent_ratio(row.get("change_30dover30d")),
                    }
                elif endpoint == "holders-revenue":
                    row_payload = {
                        "holder_revenue_24h": _safe_float(
                            row.get("total24h")
                            or row.get("holdersRevenue24h")
                            or row.get("holderRevenue24h")
                            or row.get("tokenHolderRevenue24h")
                        ),
                        "holder_revenue_30d": _safe_float(row.get("total30d")),
                        "holder_revenue_1y": _safe_float(row.get("total1y")),
                    }

                if not row_payload:
                    continue
                cleaned = {k: v for k, v in row_payload.items() if v is not None}
                if not cleaned:
                    continue

                if slug:
                    existing = index.get(slug) or {}
                    existing.update(cleaned)
                    index[slug] = existing
                if name:
                    existing = index.get(name) or {}
                    existing.update(cleaned)
                    index[name] = existing

        await _merge_endpoint("fees")
        await _merge_endpoint("revenue")
        await _merge_endpoint("holders-revenue")
        return index

    async def _fetch_fees_overview_row(
        self,
        *,
        target_slug: str,
        target_name: str,
    ) -> dict[str, Any] | None:
        index = await self._fetch_fees_overview_index()
        slug_key = target_slug.strip().lower()
        name_key = target_name.strip().lower()
        return index.get(slug_key) or index.get(name_key)

    def _candidate_slug(self, target: dict[str, Any]) -> str:
        for key in ("defillama_slug",):
            value = str((target.get("metadata") or {}).get(key) or "").strip()
            if value:
                return value.lower()
        name = str(target.get("name") or "").strip().lower()
        return name.replace(" ", "-")
