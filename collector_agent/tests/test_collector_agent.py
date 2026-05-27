from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time

import httpx

from collector_agent.config import Settings
from collector_agent.contracts import CollectorRequest, CollectorResponse, Provenance, Quality, SourceResult, TargetRef
from collector_agent.docs_profile import (
    DocumentationProfileBuilder,
    ProjectProfile,
    ProjectProfileCache,
    _collect_revenue_model_points,
    _collect_governance_points,
    _collect_investor_partner_points,
    _collect_roadmap_points,
    _collect_team_points,
    _collect_token_distribution_points,
    _collect_token_utility_points,
    _collect_tokenomics_points,
    _collect_treasury_points,
    _collect_value_capture_points,
)
from collector_agent.http_app import app
from collector_agent.rules import build_agent_diagnostics, classify_asset
from collector_agent.service import CollectorAgentService
from collector_agent.sources import DefiLlamaSource, build_default_adapters


def _request_payload(**overrides):
    payload = {
        "target": {
            "name": "Bitcoin",
            "ticker": "BTC",
            "coingecko_id": "bitcoin",
        },
        "sources": ["coingecko", "defillama"],
        "criteria": {
            "need_metrics": True,
            "need_protocol": True,
            "need_yields": False,
            "need_competitors": False,
        },
        "strategy": "api_first_browser_second",
        "deadline_sec": 5,
    }
    payload.update(overrides)
    return payload


def _settings(**overrides) -> Settings:
    payload = {
        "service_token": "",
        "http_timeout_seconds": 10,
        "coingecko_base_url": "https://cg.example",
        "defillama_base_url": "https://dl.example",
        "profile_cache_dir": "/tmp/collector-agent-tests",
        "profile_cache_ttl_seconds": 21600,
        "docs_max_pages": 40,
        "docs_max_seed_pages": 12,
        "docs_stage_cap_seconds": 4.0,
    }
    payload.update(overrides)
    return Settings(**payload)


async def _app_post(payload: dict, *, headers: dict[str, str] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.post("/collect", json=payload, headers=headers)


class _FakeService:
    def __init__(self, response: CollectorResponse) -> None:
        self.response = response

    async def collect(self, request: CollectorRequest) -> CollectorResponse:
        assert request.target.name == "Bitcoin"
        return self.response


class _NoopAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _StaticAdapter:
    def __init__(self, result: SourceResult) -> None:
        self.result = result

    async def collect(self, request: CollectorRequest, *, client, deadline_at: float) -> SourceResult:
        del request, client, deadline_at
        return self.result


class _SlowAdapter:
    def __init__(self, source_name: str, delay: float) -> None:
        self.source_name = source_name
        self.delay = delay

    async def collect(self, request: CollectorRequest, *, client, deadline_at: float) -> SourceResult:
        del request, client, deadline_at
        await asyncio.sleep(self.delay)
        return _success_result(self.source_name, metrics={"price_usd": 1.0})


class _ErrorAdapter:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def collect(self, request: CollectorRequest, *, client, deadline_at: float) -> SourceResult:
        del request, client, deadline_at
        raise self.exc


class _StaticProfileBuilder:
    def __init__(self, profile: ProjectProfile | None = None, *, exc: Exception | None = None) -> None:
        self.profile = profile
        self.exc = exc

    async def build(self, request: CollectorRequest, *, client, deadline_at: float, refresh: bool = False):
        del request, client, deadline_at, refresh
        if self.exc is not None:
            raise self.exc
        return self.profile


def _success_result(source: str, *, metrics=None, items=None, metadata=None) -> SourceResult:
    return SourceResult(
        source=source,
        method="api",
        elapsed_ms=0,
        success=True,
        metrics=metrics,
        items=items,
        metadata=metadata,
        provenance=Provenance(method="api", provider=source),
        quality=Quality(status="complete", confidence=0.9, stale=False),
    )


def test_auth_ok(monkeypatch):
    response = CollectorResponse(
        status="ok",
        target=TargetRef(name="Bitcoin", ticker="BTC", coingecko_id="bitcoin"),
        collected_at="2026-03-30T12:00:00Z",
        source_results=[],
    )
    monkeypatch.setattr(
        "collector_agent.http_app.get_settings",
        lambda: _settings(service_token="secret"),
    )
    monkeypatch.setattr("collector_agent.http_app.get_service", lambda: _FakeService(response))

    http_response = asyncio.run(
        _app_post(
            _request_payload(),
            headers={"X-Service-Token": "secret"},
        )
    )

    assert http_response.status_code == 200
    assert http_response.json()["status"] == "ok"


def test_auth_fail(monkeypatch):
    monkeypatch.setattr(
        "collector_agent.http_app.get_settings",
        lambda: _settings(service_token="secret"),
    )
    monkeypatch.setattr("collector_agent.http_app.get_service", lambda: None)

    http_response = asyncio.run(
        _app_post(
            _request_payload(),
            headers={"X-Service-Token": "wrong"},
        )
    )

    body = http_response.json()
    assert http_response.status_code == 401
    assert body["status"] == "error"
    assert body["errors"][0]["code"] == "unauthorized"


def test_invalid_request_returns_structured_error(monkeypatch):
    monkeypatch.setattr(
        "collector_agent.http_app.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr("collector_agent.http_app.get_service", lambda: None)

    http_response = asyncio.run(
        _app_post(
            _request_payload(target={"ticker": "BTC"}),
        )
    )

    body = http_response.json()
    assert http_response.status_code == 400
    assert body["status"] == "error"
    assert body["errors"][0]["code"] == "invalid_request"
    assert body["source_results"] == []


def test_valid_request_ok_with_real_http_mocks():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/coins/bitcoin":
            return httpx.Response(
                200,
                json={
                    "id": "bitcoin",
                    "symbol": "btc",
                    "name": "Bitcoin",
                    "description": {"en": "Digital gold"},
                    "categories": ["Store of Value"],
                    "asset_platform_id": None,
                    "platforms": {},
                    "links": {
                        "homepage": ["https://bitcoin.org"],
                        "twitter_screen_name": "bitcoin",
                        "telegram_channel_identifier": "",
                        "subreddit_url": "https://reddit.com/r/bitcoin",
                        "repos_url": {"github": ["https://github.com/bitcoin/bitcoin"]},
                    },
                    "community_data": {"twitter_followers": 10, "reddit_subscribers": 20},
                    "market_data": {
                        "current_price": {"usd": 100000},
                        "market_cap": {"usd": 2_000_000_000_000},
                        "total_volume": {"usd": 50_000_000_000},
                        "price_change_percentage_24h": 3.2,
                        "price_change_percentage_7d": 7.1,
                        "fully_diluted_valuation": {"usd": 2_100_000_000_000},
                        "circulating_supply": 19_800_000,
                    },
                },
            )
        if request.url.path == "/protocol/bitcoin":
            return httpx.Response(
                200,
                json={
                    "slug": "bitcoin",
                    "name": "Bitcoin",
                    "category": "Chain",
                    "chains": ["Bitcoin"],
                    "url": "https://bitcoin.org",
                    "description": "Bitcoin protocol",
                    "tvl": 123456789,
                    "mcap": 2_000_000_000_000,
                    "fdv": 2_100_000_000_000,
                    "volume24h": 100_000_000,
                },
            )
        if request.url.path.startswith("/summary/"):
            return httpx.Response(404)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = CollectorAgentService(
        settings=_settings(),
        adapters=build_default_adapters(_settings()),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None),
    )

    response = asyncio.run(service.collect(CollectorRequest.model_validate(_request_payload())))

    assert response.status == "ok"
    assert len(response.source_results) == 2
    assert response.source_results[0].metrics["price_usd"] == 100000
    assert response.source_results[1].metrics["tvl"] == 123456789
    assert response.diagnostics["asset_type"] == "blockchain"
    assert "tvl" in response.diagnostics["found_metrics"]
    assert "unavailable_until_dune" not in response.diagnostics
    cg_item = response.source_results[0].items[0]
    dl_item = response.source_results[1].items[0]
    assert cg_item["content_type"] == "metric"
    assert dl_item["content_type"] == "protocol_data"
    assert cg_item["metadata"]["official_links"]["github"] == "https://github.com/bitcoin/bitcoin"
    assert dl_item["metadata"]["website"] == "https://bitcoin.org"


def test_defillama_protocol_resolution_supports_fuzzy_name_matches():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/protocol/sky":
            return httpx.Response(404)
        if request.url.path == "/protocols":
            return httpx.Response(
                200,
                json=[
                    {
                        "slug": "sky-protocol",
                        "name": "Sky Protocol",
                        "symbol": "SKY",
                        "gecko_id": "",
                    }
                ],
            )
        if request.url.path == "/protocol/sky-protocol":
            return httpx.Response(
                200,
                json={
                    "slug": "sky-protocol",
                    "name": "Sky Protocol",
                    "category": "Lending",
                    "chains": ["Ethereum"],
                    "url": "https://sky.money",
                    "tvl": 5_000_000_000,
                },
            )
        if request.url.path.startswith("/summary/"):
            return httpx.Response(404)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = CollectorAgentService(
        settings=_settings(),
        adapters={"defillama": build_default_adapters(_settings())["defillama"]},
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None),
    )
    request = CollectorRequest.model_validate(
        _request_payload(
            target={"name": "Sky", "ticker": "SKY"},
            sources=["defillama"],
        )
    )

    response = asyncio.run(service.collect(request))

    assert response.status == "ok"
    assert response.source_results[0].success is True
    assert response.source_results[0].metadata["resolved_slug"] == "sky-protocol"
    assert response.diagnostics["asset_type"] == "lending"


def test_partial_when_one_source_fails():
    request = CollectorRequest.model_validate(_request_payload())
    service = CollectorAgentService(
        settings=_settings(),
        adapters={
            "coingecko": _StaticAdapter(_success_result("coingecko", metrics={"price_usd": 100000.0})),
            "defillama": _ErrorAdapter(
                httpx.ConnectError("boom", request=httpx.Request("GET", "https://dl.example/protocol/bitcoin"))
            ),
        },
        client_factory=_NoopAsyncClient,
    )

    response = asyncio.run(service.collect(request))

    assert response.status == "partial"
    assert response.source_results[0].success is True
    assert response.source_results[1].success is False
    assert response.source_results[1].error.code == "upstream_transport_error"
    assert response.diagnostics["asset_type"] == "unknown_other"


def test_timeout_deadline_behavior():
    request = CollectorRequest.model_validate(_request_payload(deadline_sec=0.01))
    service = CollectorAgentService(
        settings=_settings(),
        adapters={
            "coingecko": _StaticAdapter(_success_result("coingecko", metrics={"price_usd": 100000.0})),
            "defillama": _SlowAdapter("defillama", delay=0.05),
        },
        client_factory=_NoopAsyncClient,
    )

    response = asyncio.run(service.collect(request))

    assert response.status == "partial"
    timed_out = response.source_results[1]
    assert timed_out.success is False
    assert timed_out.timed_out is True
    assert timed_out.error.code == "timeout"


def test_upstream_api_failure_returns_error_without_crash():
    request = CollectorRequest.model_validate(
        _request_payload(
            sources=["coingecko"],
            criteria={
                "need_metrics": True,
                "need_protocol": True,
                "need_yields": False,
                "need_competitors": False,
            },
        )
    )
    service = CollectorAgentService(
        settings=_settings(),
        adapters={
            "coingecko": _ErrorAdapter(
                httpx.HTTPStatusError(
                    "bad gateway",
                    request=httpx.Request("GET", "https://cg.example/coins/bitcoin"),
                    response=httpx.Response(503),
                )
            )
        },
        client_factory=_NoopAsyncClient,
    )

    response = asyncio.run(service.collect(request))

    assert response.status == "error"
    assert response.errors[0].code == "upstream_http_error"
    assert response.source_results[0].success is False


def test_rule_layer_classifies_lending_and_builds_metric_plan():
    request = CollectorRequest.model_validate(
        _request_payload(
            sources=["defillama"],
            target={"name": "Aave", "ticker": "AAVE", "coingecko_id": "aave"},
        )
    )
    result = _success_result(
        "defillama",
        metrics={"tvl": 1_500_000_000.0},
        metadata={"category": "Lending", "chains": ["Ethereum", "Base"]},
        items=[
            {
                "metadata": {
                    "yield_pool": True,
                }
            },
            {
                "metadata": {
                    "competitors": [
                        {"name": "Compound", "tvl": 800_000_000.0},
                        {"name": "Spark", "tvl": 700_000_000.0},
                    ],
                    "target_snapshot": {"tvl": 1_500_000_000.0},
                }
            },
        ],
    )

    classification = classify_asset(request, [result])
    diagnostics = build_agent_diagnostics(request, [result])

    assert classification.asset_type == "lending"
    assert diagnostics["required_metrics_attempted"] == [
        "tvl",
        "yields",
        "fees",
        "revenue",
        "market_share",
        "competitors",
    ]
    assert "tvl" in diagnostics["found_metrics"]
    assert "yields" in diagnostics["found_metrics"]
    assert "competitors" in diagnostics["found_metrics"]
    assert "market_share" in diagnostics["found_metrics"]
    assert "fees" in diagnostics["not_found_metrics"]


def test_rule_layer_avoids_false_dex_match_from_index_categories():
    request = CollectorRequest.model_validate(
        _request_payload(
            sources=["coingecko", "defillama"],
            target={"name": "Aave", "ticker": "AAVE", "coingecko_id": "aave"},
        )
    )
    coingecko_result = _success_result(
        "coingecko",
        metrics={"market_cap": 1_400_000_000.0},
        metadata={
            "categories": [
                "Index Coop Defi Index",
                "Coinbase 50 Index",
                "Lending/Borrowing Protocols",
            ]
        },
        items=[
            {
                "title": "Aave — CoinGecko",
                "content": "Aave is a decentralized money market protocol where users can lend and borrow assets.",
                "metadata": {
                    "categories": [
                        "Index Coop Defi Index",
                        "Lending/Borrowing Protocols",
                    ]
                },
            }
        ],
    )
    defillama_result = _success_result(
        "defillama",
        metrics={"tvl": 23_000_000_000.0},
        metadata={"category": None},
        items=[{"metadata": {"yield_pool": True}}],
    )

    classification = classify_asset(request, [coingecko_result, defillama_result])

    assert classification.asset_type == "lending"
    assert classification.scores["dex"] < classification.scores["lending"]


def test_rule_layer_unknown_other_on_low_confidence_hints():
    request = CollectorRequest.model_validate(
        _request_payload(
            target={"name": "Mystery Protocol", "ticker": "MYS"},
            sources=["coingecko"],
        )
    )
    result = _success_result(
        "coingecko",
        metrics={"price_usd": 1.0},
        metadata={"categories": ["Experimental"]},
        items=[{"metadata": {"categories": ["Experimental"]}}],
    )

    classification = classify_asset(request, [result])
    diagnostics = build_agent_diagnostics(request, [result])

    assert classification.asset_type == "unknown_other"
    assert diagnostics["asset_type"] == "unknown_other"
    assert diagnostics["found_metrics"] == []


def test_rule_layer_perp_dex_uses_available_defillama_project_metrics():
    request = CollectorRequest.model_validate(
        _request_payload(
            target={"name": "Lighter", "ticker": "LIT", "coingecko_id": "lighter"},
            sources=["defillama"],
        )
    )
    result = _success_result(
        "defillama",
        metrics={
            "volume_24h": 780_000_000.0,
            "open_interest_usd": 320_000_000.0,
            "fees_24h": 350_000.0,
            "protocol_revenue_24h": 110_000.0,
        },
        metadata={"category": "Derivatives"},
        items=[
            {
                "metadata": {
                    "competitors": [
                        {"name": "Hyperliquid", "volume_24h": 1_200_000_000.0},
                        {"name": "dYdX", "volume_24h": 210_000_000.0},
                    ],
                    "target_snapshot": {"volume_24h": 780_000_000.0},
                }
            }
        ],
    )

    diagnostics = build_agent_diagnostics(request, [result])

    assert diagnostics["asset_type"] == "perp_dex"
    assert "trading_volume" in diagnostics["found_metrics"]
    assert "open_interest" in diagnostics["found_metrics"]
    assert "fees" in diagnostics["found_metrics"]
    assert "protocol_revenue" in diagnostics["found_metrics"]
    assert "market_share" in diagnostics["found_metrics"]


def test_rule_layer_lending_marks_fees_revenue_and_chain_distribution_when_available():
    request = CollectorRequest.model_validate(
        _request_payload(
            sources=["defillama"],
            target={"name": "Morpho", "ticker": "MORPHO", "coingecko_id": "morpho"},
        )
    )
    result = _success_result(
        "defillama",
        metrics={
            "tvl": 6_700_000_000.0,
            "fees_24h": 75_000.0,
            "revenue_24h": 24_000.0,
            "chain_distribution": {"Ethereum": 3_640_000_000.0, "Base": 2_178_000_000.0},
        },
        metadata={"category": "Lending", "chains": ["Ethereum", "Base"]},
        items=[
            {"metadata": {"yield_pool": True}},
            {
                "metadata": {
                    "competitors": [{"name": "Aave", "tvl": 25_000_000_000.0}],
                    "target_snapshot": {"tvl": 6_700_000_000.0},
                }
            },
        ],
    )

    diagnostics = build_agent_diagnostics(request, [result])

    assert diagnostics["asset_type"] == "lending"
    assert "fees" in diagnostics["found_metrics"]
    assert "revenue" in diagnostics["found_metrics"]
    assert "chain_distribution" in diagnostics["found_metrics"]


def test_defillama_source_extracts_extended_project_metrics():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/protocol/morpho-v1":
            return httpx.Response(
                200,
                json={
                    "name": "Morpho V1",
                    "slug": "morpho-v1",
                    "category": "Lending",
                    "chains": ["Ethereum", "Base"],
                    "description": "Onchain lending protocol.",
                    "url": "https://morpho.org/",
                    "tvl": [{"totalLiquidityUSD": 6_749_919_543.38}],
                    "mcap": 835_000_000.0,
                    "fdv": 1_200_000_000.0,
                    "volume24h": 120_000_000.0,
                    "fees24h": 80_000.0,
                    "revenue24h": 25_000.0,
                    "openInterest": {"total": 310_000_000.0},
                    "change_1d": -0.6,
                    "change_7d": 1.7,
                    "change_1m": 12.4,
                    "currentChainTvls": {"Ethereum": 3_640_000_000.0, "Base": 2_178_000_000.0},
                    "chainTvls": {"Ethereum": {"tvl": [{"totalLiquidityUSD": 3_640_000_000.0}]}, "Base": {"tvl": [{"totalLiquidityUSD": 2_178_000_000.0}]}},
                },
            )
        if request.url.path == "/summary/fees/morpho-v1":
            data_type = request.url.params.get("dataType")
            if data_type == "dailyFees":
                return httpx.Response(200, json={"total24h": 82_000.0, "total30d": 2_420_000.0})
            if data_type == "dailyRevenue":
                return httpx.Response(200, json={"total24h": 26_000.0, "total30d": 780_000.0})
            if data_type == "dailyHoldersRevenue":
                return httpx.Response(200, json={"total24h": 14_000.0, "total30d": 390_000.0})
            return httpx.Response(404)
        if request.url.path == "/summary/dexs/morpho-v1":
            return httpx.Response(200, json={"total24h": 120_000_000.0, "total30d": 3_200_000_000.0})
        if request.url.path == "/protocols":
            return httpx.Response(
                200,
                json=[
                    {"name": "Aave", "slug": "aave", "category": "Lending", "tvl": 20_000_000_000.0, "mcap": 2_300_000_000.0},
                    {"name": "Compound", "slug": "compound", "category": "Lending", "tvl": 3_000_000_000.0, "mcap": 1_200_000_000.0},
                ],
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    request = CollectorRequest.model_validate(
        _request_payload(
            target={"name": "Morpho", "ticker": "MORPHO", "coingecko_id": "morpho-v1"},
            sources=["defillama"],
            criteria={"need_metrics": True, "need_protocol": True, "need_yields": False, "need_competitors": True},
        )
    )
    source = DefiLlamaSource(_settings(defillama_base_url="https://dl.example"))
    transport = httpx.MockTransport(handler)

    async def run() -> SourceResult:
        async with httpx.AsyncClient(transport=transport) as client:
            return await source.collect(request, client=client, deadline_at=time.monotonic() + 2)

    result = asyncio.run(run())

    assert result.success is True
    assert result.metrics is not None
    assert result.metrics["fees_24h"] == 82_000.0
    assert result.metrics["revenue_24h"] == 26_000.0
    assert result.metrics["open_interest_usd"] == 310_000_000.0
    assert result.metrics["holder_revenue_24h"] == 14_000.0
    assert result.metrics["dex_volume_30d"] == 3_200_000_000.0
    assert isinstance(result.metrics["chain_distribution"], dict)
    assert result.metadata["category"] == "Lending"


def test_defillama_source_summary_metrics_fill_perp_project_gaps_and_handle_402():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/protocol/lighter":
            return httpx.Response(
                200,
                json={
                    "name": "Lighter",
                    "slug": "lighter",
                    "category": "Derivatives",
                    "chains": ["ZkLighter"],
                    "description": "Perp DEX.",
                    "url": "https://lighter.xyz/",
                    "tvl": [{"totalLiquidityUSD": 513_000_000.0}],
                    "mcap": 213_000_000.0,
                    "fdv": 512_000_000.0,
                },
            )
        if request.url.path == "/summary/fees/lighter":
            data_type = request.url.params.get("dataType")
            if data_type == "dailyFees":
                return httpx.Response(200, json={"total24h": 86_000.0, "total30d": 3_700_000.0})
            if data_type == "dailyRevenue":
                return httpx.Response(200, json={"total24h": 82_000.0, "total30d": 3_050_000.0})
            if data_type == "dailyHoldersRevenue":
                return httpx.Response(200, json={"total24h": 75_000.0, "total30d": 3_010_000.0})
            return httpx.Response(404)
        if request.url.path == "/summary/dexs/lighter":
            return httpx.Response(200, json={"total24h": 4_583_404.0, "total30d": 203_345_617.0})
        if request.url.path == "/summary/derivatives/lighter":
            return httpx.Response(402, text="Upgrade to paid plan")
        if request.url.path == "/protocols":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected path: {request.url.path}")

    request = CollectorRequest.model_validate(
        _request_payload(
            target={"name": "Lighter", "ticker": "LIT", "coingecko_id": "lighter"},
            sources=["defillama"],
            criteria={"need_metrics": True, "need_protocol": True, "need_yields": False, "need_competitors": False},
        )
    )
    source = DefiLlamaSource(_settings(defillama_base_url="https://dl.example"))
    transport = httpx.MockTransport(handler)

    async def run() -> SourceResult:
        async with httpx.AsyncClient(transport=transport) as client:
            return await source.collect(request, client=client, deadline_at=time.monotonic() + 2)

    result = asyncio.run(run())

    assert result.success is True
    assert result.metrics is not None
    assert result.metrics["fees_24h"] == 86_000.0
    assert result.metrics["protocol_revenue_24h"] == 82_000.0
    assert result.metrics["holder_revenue_24h"] == 75_000.0
    assert result.metrics["dex_volume_30d"] == 203_345_617.0
    assert result.metrics["trading_volume_24h"] == 4_583_404.0
    assert any("derivatives/openInterest" in warning for warning in (result.quality.warnings or []))


def test_service_keeps_response_shape_and_agent_diagnostics():
    request = CollectorRequest.model_validate(_request_payload())
    service = CollectorAgentService(
        settings=_settings(),
        adapters={
            "coingecko": _StaticAdapter(
                _success_result(
                    "coingecko",
                    metrics={"price_usd": 100000.0, "market_cap": 2_000_000_000_000.0},
                    metadata={"categories": ["Layer 1", "Store of Value"]},
                    items=[{"metadata": {"categories": ["Layer 1", "Store of Value"]}}],
                )
            ),
            "defillama": _StaticAdapter(
                _success_result(
                    "defillama",
                    metrics={"tvl": 123456789.0},
                    metadata={"category": "Chain", "chains": ["Bitcoin"]},
                    items=[{"metadata": {"chains": ["Bitcoin"]}}],
                )
            ),
        },
        client_factory=_NoopAsyncClient,
    )

    response = asyncio.run(service.collect(request))
    payload = response.model_dump(mode="json")

    assert payload["status"] == "ok"
    assert "source_results" in payload
    assert "diagnostics" in payload
    assert payload["diagnostics"]["asset_type"] == "blockchain"
    assert payload["diagnostics"]["by_metric"]["tvl"]["status"] == "found"


def test_service_diagnostics_survive_partial_missing_data():
    request = CollectorRequest.model_validate(_request_payload())
    service = CollectorAgentService(
        settings=_settings(),
        adapters={
            "coingecko": _StaticAdapter(
                _success_result(
                    "coingecko",
                    metrics={"price_usd": 2.0},
                    metadata={"categories": ["Oracle"]},
                    items=[{"metadata": {"categories": ["Oracle"]}}],
                )
            ),
            "defillama": _StaticAdapter(
                SourceResult(
                    source="defillama",
                    method="api",
                    elapsed_ms=0,
                    success=False,
                    error={"code": "target_not_found", "message": "missing", "retryable": False},
                    metadata={"category": None},
                    provenance=Provenance(method="api", provider="defillama"),
                    quality=Quality(status="warnings", confidence=0.3, stale=False),
                )
            ),
        },
        client_factory=_NoopAsyncClient,
    )

    response = asyncio.run(service.collect(request))

    assert response.status == "partial"
    assert response.diagnostics["asset_type"] == "infrastructure_or_oracle_or_data"
    assert "competitors" in response.diagnostics["not_found_metrics"]


def test_docs_profile_discovers_and_reads_full_official_docs_contour(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/lighter"):
            return httpx.Response(
                200,
                json={
                    "links": {
                        "homepage": ["https://lighter.xyz"],
                        "repos_url": {"github": ["https://github.com/lighter-xyz/core"]},
                    }
                },
            )
        if url == "https://dl.example/protocol/lighter":
            return httpx.Response(
                200,
                json={"slug": "lighter", "name": "Lighter", "url": "https://lighter.xyz", "category": "Dexes"},
            )
        if url == "https://lighter.xyz/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://docs.lighter.xyz/overview">Docs</a>
                  <a href="https://docs.lighter.xyz/tokenomics">Tokenomics</a>
                  <a href="https://docs.lighter.xyz/security">Security</a>
                  <a href="https://lighter.xyz/audits">Audits</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.lighter.xyz/overview":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Lighter Overview</h1>
                  <p>Lighter is a non-custodial perpetual exchange with an order book based market structure.</p>
                  <nav>
                    <a href="https://docs.lighter.xyz/overview">Overview</a>
                    <a href="https://docs.lighter.xyz/perpetuals">Perpetuals</a>
                    <a href="https://docs.lighter.xyz/governance">Governance</a>
                    <a href="https://docs.lighter.xyz/tokenomics">Tokenomics</a>
                    <a href="https://docs.lighter.xyz/security">Security</a>
                    <a href="https://docs.lighter.xyz/blog/launch">Blog</a>
                  </nav>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.lighter.xyz/perpetuals":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Perpetual Markets</h1>
                  <p>Users trade perpetual futures with leverage, funding rates, and open interest.</p>
                  <p>The central limit order book matches perpetual positions without custody of user assets.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.lighter.xyz/governance":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Governance</h1>
                  <p>The LIGHT token is used for governance voting and fee rebates.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.lighter.xyz/tokenomics":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Tokenomics</h1>
                  <p>Token emissions align traders, stakers, and market makers.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.lighter.xyz/security":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Security</h1>
                  <p>Smart contract risk, liquidation risk, and oracle risk are documented here.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://lighter.xyz/audits":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Audits</h1>
                  <p>External security audits were completed before mainnet launch.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Lighter", "ticker": "LIGHT", "coingecko_id": "lighter"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "perp_dex"
    assert profile.project_subtype == "orderbook_perp_dex"
    assert profile.security_section_present is True
    assert profile.audits_present is True
    assert profile.tokenomics_present is True
    assert profile.governance_present is True
    assert "https://docs.lighter.xyz/overview" in profile.official_urls["docs"]
    assert "https://docs.lighter.xyz/perpetuals" in profile.docs_urls_read
    assert "https://lighter.xyz/audits" in profile.docs_urls_read
    assert all("blog" not in url for url in profile.docs_urls_read)
    assert profile.classification_flags["perp_dex"] is True
    assert profile.classification_flags["lending"] is False
    assert profile.classification_flags["orderbook_visible"] is True
    assert profile.classification_flags["non_custodial_visible"] is True


def test_docs_profile_cache_reuses_snapshot(tmp_path: Path):
    call_count = {"total": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["total"] += 1
        url = str(request.url)
        if url.startswith("https://cg.example/coins/aster"):
            return httpx.Response(200, json={"links": {"homepage": ["https://aster.finance"]}})
        if url == "https://dl.example/protocol/aster":
            return httpx.Response(200, json={"slug": "aster", "name": "Aster", "url": "https://aster.finance"})
        if url == "https://aster.finance/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://docs.aster.finance/overview">Docs</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.aster.finance/overview":
            return httpx.Response(
                200,
                text="<html><body><h1>Aster</h1><p>Aster is a perpetuals protocol with leverage.</p></body></html>",
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Aster", "ticker": "AST", "coingecko_id": "aster"})
    )
    settings = _settings(profile_cache_dir=str(tmp_path), profile_cache_ttl_seconds=3600)
    builder = DocumentationProfileBuilder(settings, cache=ProjectProfileCache(cache_dir=str(tmp_path), ttl_seconds=3600))

    async def run() -> tuple[ProjectProfile, ProjectProfile]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            first = await builder.build(request, client=client, deadline_at=time.monotonic() + 5)
            before = call_count["total"]
            second = await builder.build(request, client=client, deadline_at=time.monotonic() + 5)
            after = call_count["total"]
            assert before == after
            return first, second

    first, second = asyncio.run(run())

    assert first.read_stats["cache_hit"] is False
    assert second.read_stats["cache_hit"] is True
    assert second.read_stats["extraction_version"]
    assert second.project_type == "perp_dex"


def test_service_prefers_docs_profile_over_aggregator_noise_for_perp_dex():
    profile = ProjectProfile(
        project_name="Lighter",
        official_urls={"website": ["https://lighter.xyz"], "docs": ["https://docs.lighter.xyz/overview"]},
        docs_urls_read=["https://docs.lighter.xyz/overview", "https://docs.lighter.xyz/perpetuals"],
        project_type="perp_dex",
        project_subtype="orderbook_perp_dex",
        confidence=0.93,
        what_the_project_does="Lighter is a perpetual exchange with order book markets.",
        business_model="Facilitates perpetual trading markets and monetizes trading activity.",
        revenue_model="Primary revenue likely comes from trading fees and liquidation activity.",
        key_product_entities=["markets", "positions"],
        supported_chains=["Ethereum"],
        token_exists=True,
        token_role="The LIGHT token is used for governance voting and fee rebates.",
        governance_present=True,
        security_section_present=True,
        audits_present=True,
        tokenomics_present=True,
        risk_factors=["Smart contract risk is documented."],
        keywords=["perpetual", "order book", "funding rate"],
        evidence_snippets=[{"url": "https://docs.lighter.xyz/perpetuals", "signal": "perpetual", "snippet": "Users trade perpetual futures with leverage."}],
        classification_flags={"perp_dex": True, "orderbook_visible": True},
        read_stats={"cache_hit": False},
    )
    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Lighter", "ticker": "LIGHT", "coingecko_id": "lighter"})
    )
    service = CollectorAgentService(
        settings=_settings(),
        adapters={
            "coingecko": _StaticAdapter(
                _success_result(
                    "coingecko",
                    metrics={"market_cap": 100_000_000.0},
                    metadata={"categories": ["Bridge", "Lending Protocol"]},
                    items=[{"content": "Lighter is listed across broad aggregator categories."}],
                )
            ),
            "defillama": _StaticAdapter(
                _success_result(
                    "defillama",
                    metrics={"volume_24h": 80_000_000.0},
                    metadata={"category": "Dexes"},
                    items=[],
                )
            ),
        },
        profile_builder=_StaticProfileBuilder(profile),
        client_factory=_NoopAsyncClient,
    )

    response = asyncio.run(service.collect(request))

    assert response.diagnostics["classification_basis"] == "official_docs"
    assert response.diagnostics["asset_type"] == "perp_dex"
    assert response.diagnostics["project_type"] == "perp_dex"
    assert response.diagnostics["project_subtype"] == "orderbook_perp_dex"
    assert response.diagnostics["project_profile"]["official_urls"]["docs"] == ["https://docs.lighter.xyz/overview"]
    assert "open_interest" in response.diagnostics["not_found_metrics"]


def test_docs_profile_marks_browser_fallback_placeholder_for_js_only_docs(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/sky"):
            return httpx.Response(200, json={"links": {"homepage": ["https://sky.money"]}})
        if url == "https://dl.example/protocol/sky":
            return httpx.Response(200, json={"slug": "sky", "name": "Sky", "url": "https://sky.money"})
        if url == "https://sky.money/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://docs.sky.money/overview">Docs</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.sky.money/overview":
            return httpx.Response(
                200,
                text="""
                <html><head>
                    <script src="/app.js"></script>
                    <script src="/vendor.js"></script>
                    <script src="/runtime.js"></script>
                </head><body><div id="app"></div></body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Sky", "ticker": "SKY", "coingecko_id": "sky"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.read_stats["browser_fallback_needed"] is True
    assert profile.read_stats["browser_fallback_supported"] is False
    assert "https://docs.sky.money/overview" in profile.read_stats["browser_fallback_reasons"]


def test_docs_profile_uses_meta_description_for_js_heavy_official_pages(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/aave"):
            return httpx.Response(200, json={"links": {"homepage": ["https://aave.com"]}})
        if url == "https://dl.example/protocol/aave":
            return httpx.Response(200, json={"slug": "aave", "name": "Aave", "url": "https://aave.com"})
        if url == "https://developers.aave.com/":
            return httpx.Response(404, text="not found")
        if url == "https://developer.aave.com/":
            return httpx.Response(404, text="not found")
        if url == "https://learn.aave.com/":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/docs":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/developers":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/developer":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/learn":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://docs.aave.com">Docs</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.aave.com/":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>Aave Docs</title>
                    <meta name="description" content="Aave is an open source liquidity protocol where users supply assets to earn yield and borrow against collateral.">
                    <script src="/app.js"></script>
                    <script src="/vendor.js"></script>
                    <script src="/runtime.js"></script>
                  </head>
                  <body><div id="app"></div></body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Aave", "ticker": "AAVE", "coingecko_id": "aave"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.what_the_project_does is not None
    assert "liquidity protocol" in profile.what_the_project_does.lower()
    assert "supply assets" in profile.what_the_project_does.lower()
    assert profile.docs_urls_read == ["https://aave.com/", "https://docs.aave.com/"]
    assert profile.read_stats["browser_fallback_needed"] is True


def test_docs_profile_follows_promising_internal_site_pages_without_explicit_docs_link(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/aerodrome"):
            return httpx.Response(200, json={"links": {"homepage": ["https://aerodrome.finance"]}})
        if url == "https://dl.example/protocol/aerodrome":
            return httpx.Response(200, json={"slug": "aerodrome", "name": "Aerodrome", "url": "https://aerodrome.finance"})
        if url == "https://docs.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://developers.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://developer.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://learn.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/docs":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/developers":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/developer":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/learn":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://aerodrome.finance/about">About</a>
                  <a href="https://aerodrome.finance/liquidity">Liquidity</a>
                  <a href="https://aerodrome.finance/governance">Governance</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://aerodrome.finance/about":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Aerodrome</h1>
                  <p>Aerodrome is a central liquidity hub on Base and a decentralized exchange designed to route trading activity efficiently.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://aerodrome.finance/liquidity":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Liquidity providers deposit assets into pools and earn trading fees and incentive emissions.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://aerodrome.finance/governance":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>The AERO token is used for governance and ecosystem incentives.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Aerodrome", "ticker": "AERO", "coingecko_id": "aerodrome"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert "https://aerodrome.finance/about" in profile.docs_urls_read
    assert profile.what_the_project_does is not None
    assert "central liquidity hub" in profile.what_the_project_does.lower()
    assert profile.token_role is not None
    assert "governance" in profile.token_role.lower()


def test_docs_profile_filters_external_reference_and_asset_noise_from_official_urls(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/pendle"):
            return httpx.Response(200, json={"links": {"homepage": ["https://pendle.finance"]}})
        if url == "https://dl.example/protocol/pendle":
            return httpx.Response(
                200,
                json={
                    "slug": "pendle",
                    "name": "Pendle",
                    "url": "https://pendle.finance",
                    "audit_links": ["https://github.com/pendle-finance/pendle-core-v2-public/tree/main/audits"],
                },
            )
        if url == "https://pendle.finance/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://docs.pendle.finance/pendle-v2/introduction">Docs</a>
                  <a href="https://pendle.finance/brand-guide">Brand</a>
                  <a href="https://docs.pendle.finance/pendle-v2/TermsOfUse">Terms</a>
                  <a href="https://docs.pendle.finance/pendle-v2/PrivacyPolicy">Privacy</a>
                  <a href="https://www.pendle.finance/images/logos/no-glow.svg">Logo</a>
                  <a href="https://tokenterminal.com/explorer/projects/pendle">Token Terminal</a>
                  <a href="https://defillama.com/protocol/pendle">DefiLlama</a>
                  <a href="https://cointelegraph.com/news/example">Cointelegraph</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.pendle.finance/pendle-v2/introduction":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Pendle</h1>
                  <a href="https://docs.pendle.finance/boros-docs/Introduction">Boros</a>
                  <a href="https://docs.pendle.finance/pendle-v2/ProtocolMechanics/YieldTokenization">Yield Tokenization</a>
                  <p>Pendle lets users trade and hedge yield from DeFi assets.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.pendle.finance/boros-docs/Introduction":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Boros</h1>
                  <p>Boros is a Pendle product for interest rate trading using funding rates, margin, positions, and liquidations.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.pendle.finance/pendle-v2/ProtocolMechanics/YieldTokenization":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Yield Tokenization</h1>
                  <p>Pendle splits yield-bearing assets into Principal Tokens and Yield Tokens so users can trade future yield or lock in fixed yield.</p>
                  <p>PENDLE can be staked as sPENDLE to receive a share of protocol revenue.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Pendle", "ticker": "PENDLE", "coingecko_id": "pendle"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())
    serialized_urls = json.dumps(profile.official_urls)

    assert "https://docs.pendle.finance/pendle-v2/introduction" in profile.official_urls["docs"]
    assert "https://github.com/pendle-finance/pendle-core-v2-public/tree/main/audits" in profile.official_urls["audits"]
    assert all("brand-guide" not in url for url in profile.docs_urls_read)
    assert all("TermsOfUse" not in url for url in profile.docs_urls_read)
    assert all("PrivacyPolicy" not in url for url in profile.docs_urls_read)
    assert all("images/logos" not in url for url in profile.docs_urls_read)
    assert "tokenterminal.com" not in serialized_urls
    assert "defillama.com" not in serialized_urls
    assert "cointelegraph.com" not in serialized_urls
    assert profile.project_type == "yield_trading"
    assert profile.business_model == "Enables users to tokenize, trade, and hedge future yield from DeFi assets."
    assert any("share of protocol revenue" in item.lower() for item in profile.revenue_model_points)


def test_docs_profile_classifies_agent_tokenization_platform_without_false_dex_or_chains(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/virtual-protocol"):
            return httpx.Response(200, json={"links": {"homepage": ["https://www.virtuals.io/"]}})
        if url == "https://dl.example/protocol/virtual-protocol":
            return httpx.Response(200, json={"slug": "virtual-protocol", "name": "Virtuals Protocol", "url": "https://www.virtuals.io/"})
        if url == "https://www.virtuals.io/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Virtuals Protocol</h1>
                  <a href="https://whitepaper.virtuals.io/">Whitepaper</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://whitepaper.virtuals.io/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Virtuals Protocol Whitepaper</h1>
                  <a href="/about-virtuals/tokenization/agent-tokenization-platform">Agent Tokenization Platform</a>
                  <a href="/about-virtuals/agent-commerce-protocol-acp">Agent Commerce Protocol</a>
                  <a href="/info-hub/usdvirtual">$VIRTUAL</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://whitepaper.virtuals.io/about-virtuals/tokenization/agent-tokenization-platform":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Agent Tokenization Platform</h1>
                  <p>The Virtuals Launchpad enables founders to tokenize AI agents and AI-native businesses directly onchain by pairing their agents with $VIRTUAL liquidity.</p>
                  <p>Each launch has a one-time creation fee of 1,000 $VIRTUAL and uses bonding curves before a liquidity pool can be established for the agent token.</p>
                  <p>The guide compares Ethereum, Arbitrum, Base, Polygon, Linea, and Mode wallets only as examples of ecosystem context.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://whitepaper.virtuals.io/about-virtuals/agent-commerce-protocol-acp":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Agent Commerce Protocol</h1>
                  <p>Agent Commerce Protocol lets autonomous agents request services, pay for tasks, and coordinate commerce onchain.</p>
                  <p>A 1% trading tax applies to agent-token activity; fees are allocated to the protocol treasury, agent creators, and ACP incentives.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://whitepaper.virtuals.io/info-hub/usdvirtual":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>$VIRTUAL</h1>
                  <p>$VIRTUAL is the base asset for agent tokens and a routing currency for agent-token purchases.</p>
                  <p>Creating a new agent requires $VIRTUAL for its liquidity pairing, creating demand and deflationary pressure through locked liquidity.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        return httpx.Response(404, text="not found")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Virtual", "ticker": "VIRTUAL", "coingecko_id": "virtual-protocol"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "agent_platform"
    assert profile.business_model == "Provides an AI-agent tokenization and commerce platform where autonomous agents can be launched, owned, and transact onchain."
    assert profile.supported_chains == []
    assert any("creation fee" in item.lower() for item in profile.revenue_model_points)
    assert any("trading tax" in item.lower() for item in profile.revenue_model_points)
    assert any("base asset" in item.lower() or "routing currency" in item.lower() for item in profile.product_token_link_points)


def test_docs_profile_classifies_alerts_sector_taxonomy_without_asset_specific_overrides(tmp_path: Path):
    pages = {
        "https://paraswap.example/": """
            <html><body>
              <h1>ParaSwap</h1>
              <a href="https://paraswap.example/docs">Docs</a>
            </body></html>
        """,
        "https://paraswap.example/docs": """
            <html><body>
              <h1>DEX Aggregator</h1>
              <p>ParaSwap is a DEX aggregator and swap aggregator that routes swaps across many liquidity sources.</p>
              <p>Smart order routing and best execution split quotes across DEXs, solvers, and liquidity sources.</p>
              <p>Protocol revenue comes from routing fees, aggregation fees, and partner fees on executed swaps.</p>
            </body></html>
        """,
        "https://lido.example/": """
            <html><body>
              <h1>Lido</h1>
              <a href="https://lido.example/docs">Docs</a>
            </body></html>
        """,
        "https://lido.example/docs": """
            <html><body>
              <h1>Liquid Staking</h1>
              <p>Lido is a liquid staking protocol that lets users stake ETH and receive stETH, a staked token.</p>
              <p>The protocol distributes staking rewards from validators while charging staking fees and validator commissions.</p>
            </body></html>
        """,
        "https://blur.example/": """
            <html><body>
              <h1>Blur</h1>
              <a href="https://blur.example/docs">Docs</a>
            </body></html>
        """,
        "https://blur.example/docs": """
            <html><body>
              <h1>NFT Marketplace</h1>
              <p>Blur is an NFT marketplace for NFT trading, listings, bids, and secondary sales.</p>
              <p>Marketplace fees and creator royalties can apply to trades between collectors and creators.</p>
            </body></html>
        """,
    }

    async def build(name: str, ticker: str, homepage: str) -> ProjectProfile:
        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.startswith("https://cg.example/coins/"):
                return httpx.Response(200, json={"links": {"homepage": [homepage]}})
            if url.startswith("https://dl.example/protocol/"):
                return httpx.Response(404, text="not found")
            html = pages.get(url)
            if html is not None:
                return httpx.Response(200, text=html, headers={"content-type": "text/html"})
            return httpx.Response(404, text="not found")

        request = CollectorRequest.model_validate(_request_payload(target={"name": name, "ticker": ticker, "coingecko_id": name.lower()}))
        builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path / name.lower())))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    paraswap = asyncio.run(build("ParaSwap", "PSP", "https://paraswap.example/"))
    lido = asyncio.run(build("Lido", "LDO", "https://lido.example/"))
    blur = asyncio.run(build("Blur", "BLUR", "https://blur.example/"))

    assert paraswap.project_type == "dex_aggregator"
    assert paraswap.business_model == "Aggregates swap liquidity and routes orders across DEXs or liquidity sources for better execution."
    assert any("routing fees" in item.lower() or "aggregation fees" in item.lower() for item in paraswap.revenue_model_points)

    assert lido.project_type == "liquid_staking"
    assert lido.business_model == "Tokenizes staked or restaked assets so users can keep liquidity while earning staking or restaking rewards."
    assert any("staking fees" in item.lower() or "validator commissions" in item.lower() for item in lido.revenue_model_points)

    assert blur.project_type == "nft_marketplace"
    assert blur.business_model == "Provides marketplace infrastructure for NFT minting, listings, bids, and secondary trading."
    assert any("marketplace fees" in item.lower() or "creator royalties" in item.lower() for item in blur.revenue_model_points)


def test_docs_profile_keeps_lido_like_noisy_docs_as_liquid_staking_not_payment_chain(tmp_path: Path):
    pages = {
        "https://lido.example/": """
            <html><body>
              <h1>Lido</h1>
              <a href="https://lido.example/docs">Docs</a>
              <a href="https://lido.example/deployed-contracts">Deployed contracts</a>
              <a href="https://lido.example/guides/integration">Integration guide</a>
            </body></html>
        """,
        "https://lido.example/docs": """
            <html><body>
              <h1>Liquid Staking</h1>
              <p>Lido is a liquid staking protocol that lets users stake ETH and receive stETH, a staked token.</p>
              <p>The protocol distributes staking rewards from validators while charging staking fees and validator commissions.</p>
              <p>LDO holders govern protocol parameters through the Lido DAO.</p>
            </body></html>
        """,
        "https://lido.example/deployed-contracts": """
            <html><body>
              <h1>Deployed contracts</h1>
              <p>Deployed on Ethereum, Arbitrum, Base, BNB Chain, Polygon, ZkSync, Linea, and Mode.</p>
              <p>Accounts, transactions, ledger integrations, validators, assets, and payments.</p>
            </body></html>
        """,
        "https://lido.example/guides/integration": """
            <html><body>
              <h1>Integration guide</h1>
              <p>Integrators can support stETH across Ethereum, Arbitrum, Base, Polygon, and other chains.</p>
              <p>Use these APIs and token guides when integrating wrapped staking tokens.</p>
            </body></html>
        """,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/lido"):
            return httpx.Response(200, json={"links": {"homepage": ["https://lido.example/"]}})
        if url.startswith("https://dl.example/protocol/"):
            return httpx.Response(404, text="not found")
        html = pages.get(url)
        if html is not None:
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    request = CollectorRequest.model_validate(_request_payload(target={"name": "Lido", "ticker": "LDO", "coingecko_id": "lido"}))
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "liquid_staking"
    assert profile.project_subtype is None
    assert "accounts" not in profile.key_product_entities
    assert "transactions" not in profile.key_product_entities
    assert profile.supported_chains == []
    assert any("govern" in item.lower() or "ldo" in item.lower() for item in profile.governance_points)


def test_docs_profile_ignores_liquid_staking_extension_chain_surfaces(tmp_path: Path):
    pages = {
        "https://lido.example/": """
            <html><body>
              <h1>Lido</h1>
              <a href="https://lido.example/docs">Docs</a>
              <a href="https://lido.example/stvaults">stVaults</a>
            </body></html>
        """,
        "https://lido.example/docs": """
            <html><body>
              <h1>Liquid Staking</h1>
              <p>Lido is a liquid staking protocol that lets users stake ETH and receive stETH, a staked token.</p>
              <p>The protocol distributes staking rewards from validators while charging staking fees and validator commissions.</p>
            </body></html>
        """,
        "https://lido.example/stvaults": """
            <html><body>
              <h1>stVaults</h1>
              <p>stVaults are available across Arbitrum, Base, BNB Chain, Polygon, ZkSync, Linea, and Mode.</p>
              <p>These vaults wrap staking positions for extended earning strategies across supported ecosystems.</p>
            </body></html>
        """,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/lido"):
            return httpx.Response(200, json={"links": {"homepage": ["https://lido.example/"]}})
        if url.startswith("https://dl.example/protocol/"):
            return httpx.Response(404, text="not found")
        html = pages.get(url)
        if html is not None:
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    request = CollectorRequest.model_validate(_request_payload(target={"name": "Lido", "ticker": "LDO", "coingecko_id": "lido"}))
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "liquid_staking"
    assert profile.supported_chains == []


def test_docs_profile_ignores_bug_bounty_and_dev_integrations_for_marinade_like_docs(tmp_path: Path):
    pages = {
        "https://marinade.example/": """
            <html><body>
              <h1>Marinade</h1>
              <a href="https://docs.marinade.example/">Docs</a>
              <a href="https://docs.marinade.example/developers/bug-bounty">Bug bounty</a>
              <a href="https://docs.marinade.example/developers/stake-to-marinade-via-fireblocks">Fireblocks</a>
              <a href="https://marinade.example/usdc-vault">USDC Vault</a>
              <a href="https://marinade.example/liquid-staking">Liquid Staking</a>
            </body></html>
        """,
        "https://docs.marinade.example/": """
            <html><body>
              <h1>Marinade Protocol Overview</h1>
              <p>Marinade is a liquid staking protocol on Solana that lets users stake SOL and receive liquid staking tokens while validators earn rewards.</p>
              <p>The protocol automates validator delegation and distributes staking rewards minus protocol fees.</p>
            </body></html>
        """,
        "https://marinade.example/liquid-staking": """
            <html><body>
              <h1>Liquid Staking</h1>
              <p>Liquid staking on Solana keeps SOL liquid while delegating stake across validators.</p>
            </body></html>
        """,
        "https://docs.marinade.example/developers/bug-bounty": """
            <html><body>
              <h1>Bug bounty</h1>
              <p>Oracle failure or manipulation, pricing oracles, governance attacks, and flash loan attacks are in scope.</p>
            </body></html>
        """,
        "https://docs.marinade.example/developers/stake-to-marinade-via-fireblocks": """
            <html><body>
              <h1>Stake to Marinade via Fireblocks</h1>
              <p>Institutional integrations can route stablecoin vault flows from Base while using Fireblocks operational tooling.</p>
            </body></html>
        """,
        "https://marinade.example/usdc-vault": """
            <html><body>
              <h1>USDC Vault</h1>
              <p>Users can earn yield on USDC through a separate vault product.</p>
            </body></html>
        """,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/marinade"):
            return httpx.Response(200, json={"links": {"homepage": ["https://marinade.example/"]}})
        if url.startswith("https://dl.example/protocol/"):
            return httpx.Response(404, text="not found")
        html = pages.get(url)
        if html is not None:
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    request = CollectorRequest.model_validate(_request_payload(target={"name": "Marinade", "ticker": "MNDE", "coingecko_id": "marinade"}))
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "liquid_staking"
    assert profile.business_model == "Tokenizes staked or restaked assets so users can keep liquidity while earning staking or restaking rewards."
    assert profile.supported_chains == []
    assert "oracles" not in profile.key_product_entities
    secondary_types = [item["type"] for item in profile.product_lines if item.get("role") == "secondary"]
    assert "vault_yield" not in secondary_types
    assert "oracle" not in secondary_types


def test_docs_profile_uses_bittensor_core_docs_not_vtao_liquidity_tutorials(tmp_path: Path):
    pages = {
        "https://bittensor.example/": """
            <html><body>
              <h1>Bittensor</h1>
              <a href="https://docs.learnbittensor.example/">Docs</a>
              <a href="https://bittensor.example/whitepaper">Whitepaper</a>
            </body></html>
        """,
        "https://bittensor.example/whitepaper": """
            <html><body>
              <p>Bittensor is a decentralized machine learning network where miners produce intelligence and validators evaluate model outputs.</p>
            </body></html>
        """,
        "https://docs.learnbittensor.example/": """
            <html><body>
              <h1>Bittensor Documentation</h1>
              <a href="https://docs.learnbittensor.example/learn/introduction">Introduction</a>
              <a href="https://docs.learnbittensor.example/evm-tutorials/bridge-vtao">Bridge vTAO</a>
              <a href="https://docs.learnbittensor.example/liquidity-positions">Liquidity positions</a>
              <a href="https://docs.learnbittensor.example/governance">Governance</a>
              <a href="https://docs.learnbittensor.example/staking-and-delegation/delegation">Delegation</a>
              <a href="https://docs.learnbittensor.example/learn/emissions">Emissions</a>
              <p>Bittensor is an AI network for machine learning, inference, miners, validators, and subnets.</p>
            </body></html>
        """,
        "https://docs.learnbittensor.example/learn/introduction": """
            <html><body>
              <p>The network coordinates subnets where miners serve AI models and validators score useful inference outputs.</p>
            </body></html>
        """,
        "https://docs.learnbittensor.example/evm-tutorials/bridge-vtao": """
            <html><body>
              <h1>Bridge vTAO</h1>
              <p>This tutorial explains wrapped staked tokens, bridge liquidity, liquid staking positions, and staking rewards for vTAO on EVM.</p>
            </body></html>
        """,
        "https://docs.learnbittensor.example/liquidity-positions": """
            <html><body>
              <h1>Liquidity positions</h1>
              <p>Liquidity providers can manage NFT positions in pools for game-like campaigns and marketplace integrations.</p>
            </body></html>
        """,
        "https://docs.learnbittensor.example/staking-and-delegation/delegation": """
            <html><body>
              <h1>Delegation</h1>
              <p>When users stake TAO, validators receive stake and rewards are emitted through subnet AMM pools.</p>
              <p>Staked tokens and staking rewards are part of native network delegation rather than a liquid staking product.</p>
            </body></html>
        """,
        "https://docs.learnbittensor.example/learn/emissions": """
            <html><body>
              <h1>Emissions</h1>
              <p>Emissions allocate rewards to miners and validators across subnets for useful machine learning work.</p>
            </body></html>
        """,
        "https://docs.learnbittensor.example/governance": """
            <html><body>
              <p>Governance participants vote on proposals and senate decisions.</p>
            </body></html>
        """,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/bittensor"):
            return httpx.Response(200, json={"links": {"homepage": ["https://bittensor.example/"]}})
        if url.startswith("https://dl.example/protocol/"):
            return httpx.Response(404, text="not found")
        html = pages.get(url)
        if html is not None:
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    request = CollectorRequest.model_validate(_request_payload(target={"name": "Tao", "ticker": "TAO", "coingecko_id": "bittensor"}))
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "ai_network"
    assert profile.business_model == "Provides AI infrastructure such as inference, compute, model, agent, or subnet marketplaces."
    assert "inference" in profile.key_product_entities
    secondary_types = [item["type"] for item in profile.product_lines if item.get("role") == "secondary"]
    assert "liquid_staking" not in secondary_types
    assert "gaming" not in secondary_types
    assert "nft_marketplace" not in secondary_types


def test_docs_profile_filters_ascii_art_and_classifies_agent_network(tmp_path: Path):
    pages = {
        "https://griffain.example/": """
            <html><body>
              <h1>Griffain</h1>
              <a href="https://griffain.example/developers">Developers</a>
            </body></html>
        """,
        "https://griffain.example/developers": """
            <html><body>
              <pre>
              ╔══════════════════════════════╗
              ║ 🤖 AGENT NETWORK 🤖          ║
              ║ ● ● ● ●                      ║
              ║ \\ | / \\ |                    ║
              ╚══════════════════════════════╝
              </pre>
              <p>Griffain is an agent network and agent engine for launching autonomous agents and services.</p>
              <p>Developers use Griffain to build AI agents that can transact and coordinate onchain services.</p>
            </body></html>
        """,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/griffain"):
            return httpx.Response(200, json={"links": {"homepage": ["https://griffain.example/"]}})
        if url.startswith("https://dl.example/protocol/"):
            return httpx.Response(404, text="not found")
        html = pages.get(url)
        if html is not None:
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    request = CollectorRequest.model_validate(_request_payload(target={"name": "Griffain", "ticker": "GRIFFAIN", "coingecko_id": "griffain"}))
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "agent_platform"
    assert "agent network" in (profile.what_the_project_does or "").lower()
    assert "╔" not in (profile.what_the_project_does or "")
    assert "AGENT NETWORK" not in (profile.what_the_project_does or "")
    assert profile.business_model == "Provides an AI-agent tokenization and commerce platform where autonomous agents can be launched, owned, and transact onchain."


def test_docs_profile_classifies_giza_agents_without_lending_or_quickstart_chains(tmp_path: Path):
    pages = {
        "https://giza.example/": """
            <html><body>
              <h1>Giza</h1>
              <a href="https://docs.giza.example/introduction">Docs</a>
              <a href="https://docs.giza.example/developers/quickstart">Quickstart</a>
            </body></html>
        """,
        "https://docs.giza.example/introduction": """
            <html><body>
              <h1>Giza Documentation</h1>
              <p>Giza builds autonomous AI agents that manage DeFi positions on behalf of users.</p>
              <p>Giza Agents use an optimizer to allocate capital across onchain markets according to user risk preferences.</p>
              <p>The Giza Agent is an autonomous agent product for DeFi automation, execution, and standardized APR discovery.</p>
            </body></html>
        """,
        "https://docs.giza.example/developers/quickstart": """
            <html><body>
              <h1>Developer Quickstart</h1>
              <p>The SDK examples support Ethereum, Arbitrum, Base, Polygon, and Mode wallets for local integration testing.</p>
              <p>The Giza Optimizer asks how capital should be distributed across lending markets to maximize yield for a user's risk preferences.</p>
              <p>Giza agents actively test protocols to extract real APR performance and create standardized APR through direct interaction.</p>
            </body></html>
        """,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/giza"):
            return httpx.Response(200, json={"links": {"homepage": ["https://giza.example/"]}})
        if url.startswith("https://dl.example/protocol/"):
            return httpx.Response(404, text="not found")
        html = pages.get(url)
        if html is not None:
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    request = CollectorRequest.model_validate(_request_payload(target={"name": "Giza", "ticker": "GIZA", "coingecko_id": "giza"}))
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type in {"agent_platform", "ai_network"}
    assert profile.project_type != "lending"
    assert "AI-agent" in (profile.business_model or "") or "AI infrastructure" in (profile.business_model or "")
    assert profile.supported_chains == []


def test_docs_profile_does_not_classify_from_security_docs_when_core_product_evidence_is_absent(tmp_path: Path):
    pages = {
        "https://example-protocol.test/": """
            <html><body>
              <h1>Example Protocol</h1>
              <a href="https://docs.example-protocol.test/developers/bug-bounty">Bug bounty</a>
            </body></html>
        """,
        "https://docs.example-protocol.test/developers/bug-bounty": """
            <html><body>
              <h1>Bug bounty</h1>
              <p>Oracle manipulation, stablecoin peg failures, bridge attacks, and liquidity pool exploits are in scope.</p>
              <p>Testing against pricing oracles or mainnet deployments is prohibited.</p>
            </body></html>
        """,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/example-protocol"):
            return httpx.Response(200, json={"links": {"homepage": ["https://example-protocol.test/"]}})
        if url.startswith("https://dl.example/protocol/"):
            return httpx.Response(404, text="not found")
        html = pages.get(url)
        if html is not None:
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Example Protocol", "ticker": "EX", "coingecko_id": "example-protocol"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "unknown_other"
    assert profile.product_lines == []
    assert profile.supported_chains == []


def test_docs_profile_keeps_jupiter_like_swap_aggregator_as_core_surface(tmp_path: Path):
    pages = {
        "https://jup.example/": """
            <html><body>
              <h1>Jupiter</h1>
              <a href="https://docs.jup.example/">Docs</a>
            </body></html>
        """,
        "https://docs.jup.example/": """
            <html><body>
              <h1>Jupiter Docs</h1>
              <a href="https://docs.jup.example/user-docs/trade/swap">Swap</a>
              <a href="https://docs.jup.example/user-docs/trade/swap/fees">Fees</a>
              <a href="https://docs.jup.example/user-docs/trade/swap/ultra-mode">Ultra Mode</a>
              <a href="https://docs.jup.example/user-docs/trade/perps-and-jlp">Perps</a>
              <a href="https://docs.jup.example/user-docs/trade/predict">Predict</a>
              <a href="https://docs.jup.example/user-docs/earn/offerbook">Earn</a>
              <a href="https://docs.jup.example/user-docs/trade/terminal">Terminal</a>
              <a href="https://docs.jup.example/user-docs/launch/studio">Launch</a>
            </body></html>
        """,
        "https://docs.jup.example/user-docs/trade/swap": """
            <html><body>
              <h1>Swap</h1>
              <p>Jupiter is a swap aggregator and DEX aggregator on Solana focused on best execution across liquidity sources.</p>
              <p>Smart order routing routes swaps across liquidity sources and returns quotes for token swaps.</p>
              <p>Jupiter swap is available on Solana.</p>
            </body></html>
        """,
        "https://docs.jup.example/user-docs/trade/swap/fees": """
            <html><body>
              <h1>Fees</h1>
              <p>Swap fees, slippage, and price impact depend on route quality and liquidity sources.</p>
            </body></html>
        """,
        "https://docs.jup.example/user-docs/trade/swap/ultra-mode": """
            <html><body>
              <h1>Ultra Mode</h1>
              <p>Ultra Mode improves token swaps through better routing and execution.</p>
              <p>Manual Mode and limit orders are available for swap traders.</p>
            </body></html>
        """,
        "https://docs.jup.example/user-docs/trade/perps-and-jlp": """
            <html><body>
              <h1>Perps and JLP</h1>
              <p>Perps are available on Solana, Base, Linea, and Mode.</p>
              <p>Open interest and perp positions are part of this separate product surface.</p>
            </body></html>
        """,
        "https://docs.jup.example/user-docs/trade/predict": """
            <html><body>
              <h1>Predict</h1>
              <p>Prediction markets are available on Base and Solana.</p>
            </body></html>
        """,
        "https://docs.jup.example/user-docs/earn/offerbook": """
            <html><body>
              <h1>Offerbook</h1>
              <p>Users can earn yield from separate earn products.</p>
            </body></html>
        """,
        "https://docs.jup.example/user-docs/trade/terminal": """
            <html><body>
              <h1>Terminal</h1>
              <p>Terminal widgets can be embedded on Base, Linea, Mode, and Solana.</p>
            </body></html>
        """,
        "https://docs.jup.example/user-docs/launch/studio": """
            <html><body>
              <h1>Launch Studio</h1>
              <p>Launch products help new tokens go live.</p>
            </body></html>
        """,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/jupiter"):
            return httpx.Response(200, json={"links": {"homepage": ["https://jup.example/"]}})
        if url.startswith("https://dl.example/protocol/"):
            return httpx.Response(404, text="not found")
        html = pages.get(url)
        if html is not None:
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    request = CollectorRequest.model_validate(_request_payload(target={"name": "Jupiter", "ticker": "JUP", "coingecko_id": "jupiter"}))
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "dex_aggregator"
    assert profile.project_subtype is None
    assert profile.business_model == "Aggregates swap liquidity and routes orders across DEXs or liquidity sources for better execution."
    assert profile.supported_chains == ["Solana"]
    assert profile.product_lines[0]["type"] == "dex_aggregator"
    assert any(item["type"] == "perp_dex" for item in profile.product_lines if item["role"] == "secondary")
    assert any(item["type"] == "prediction_market" for item in profile.product_lines if item["role"] == "secondary")
    assert "routes" in profile.key_product_entities or "liquidity sources" in profile.key_product_entities


def test_docs_profile_token_utility_points_ignore_generic_supply_mechanics(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/aave"):
            return httpx.Response(200, json={"links": {"homepage": ["https://aave.com"]}})
        if url == "https://dl.example/protocol/aave":
            return httpx.Response(200, json={"slug": "aave", "name": "Aave", "url": "https://aave.com"})
        if url == "https://docs.aave.com/":
            return httpx.Response(404, text="not found")
        if url == "https://developers.aave.com/":
            return httpx.Response(404, text="not found")
        if url == "https://developer.aave.com/":
            return httpx.Response(404, text="not found")
        if url == "https://learn.aave.com/":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/docs":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/developers":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/developer":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/learn":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://aave.com/help/governance">Governance</a><a href="https://aave.com/help/supplying">Supplying</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://aave.com/help/governance":
            return httpx.Response(
                200,
                text='<html><body><p>AAVE token holders participate in governance voting and can stake in the Safety Module.</p></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://aave.com/help/supplying":
            return httpx.Response(
                200,
                text='<html><body><p>Supplied tokens are stored in publicly accessible smart contracts that enable overcollateralised borrowing according to governance-approved parameters.</p></body></html>',
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Aave", "ticker": "AAVE", "coingecko_id": "aave"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert any("safety module" in item.lower() for item in profile.token_utility_points)
    assert all("supplied tokens are stored" not in item.lower() for item in profile.token_utility_points)


def test_docs_profile_token_utility_points_ignore_third_party_audit_docs_for_semantics(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/uniswap"):
            return httpx.Response(200, json={"links": {"homepage": ["https://uniswap.org"]}})
        if url == "https://dl.example/protocol/uniswap":
            return httpx.Response(200, json={"slug": "uniswap", "name": "Uniswap", "url": "https://uniswap.org"})
        if url == "https://docs.uniswap.org/":
            return httpx.Response(404, text="not found")
        if url == "https://docs.uniswap.org/docs":
            return httpx.Response(404, text="not found")
        if url == "https://developers.uniswap.org/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://developers.uniswap.org/docs">Docs</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://developers.uniswap.org/docs":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Uniswap pools route liquidity across supported markets.</p>
                  <p>UNI token holders govern protocol upgrades and treasury decisions.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://developer.uniswap.org/":
            return httpx.Response(404, text="not found")
        if url == "https://learn.uniswap.org/":
            return httpx.Response(404, text="not found")
        if url == "https://uniswap.org/docs":
            return httpx.Response(404, text="not found")
        if url == "https://uniswap.org/developers":
            return httpx.Response(404, text="not found")
        if url == "https://uniswap.org/developer":
            return httpx.Response(404, text="not found")
        if url == "https://uniswap.org/learn":
            return httpx.Response(404, text="not found")
        if url == "https://uniswap.org/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://uniswap.org/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://developers.uniswap.org/docs">Developers Docs</a><a href="https://cantina.xyz/bounties/uni">Bug bounty</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://cantina.xyz/bounties/uni":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Security Researchers Opportunities to offer and conduct efficient, well-matched security audits.</p>
                  <p>Curated Opportunities. Collaborative Environment. Cantina Tools Communication Features.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Uni", "ticker": "UNI", "coingecko_id": "uniswap"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert any("govern" in item.lower() for item in profile.token_utility_points)
    assert all("cantina" not in item.lower() for item in profile.token_utility_points)
    assert all("curated opportunities" not in item.lower() for item in profile.token_utility_points)


def test_docs_profile_extracts_governance_treasury_tokenomics_and_revenue_points(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/aerodrome"):
            return httpx.Response(200, json={"links": {"homepage": ["https://aerodrome.finance"]}})
        if url == "https://dl.example/protocol/aerodrome":
            return httpx.Response(200, json={"slug": "aerodrome", "name": "Aerodrome", "url": "https://aerodrome.finance"})
        if url == "https://docs.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://developers.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://developer.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://learn.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/docs":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/developers":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/developer":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/learn":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://aerodrome.finance/tokenomics">Tokenomics</a>
                  <a href="https://aerodrome.finance/governance">Governance</a>
                  <a href="https://aerodrome.finance/treasury">Treasury</a>
                  <a href="https://aerodrome.finance/fees">Fees</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://aerodrome.finance/tokenomics":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Tokenomics</h1>
                  <p>The max supply of AERO is fixed at 500 million tokens and weekly emissions decay over time.</p>
                  <p>AERO distribution allocates 40% to community incentives, 25% to the team, 25% to investors, and 10% to the treasury.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://aerodrome.finance/governance":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Governance</h1>
                  <p>AERO can be locked as veAERO for governance voting on emissions and protocol fee distribution.</p>
                  <p>Token holders may submit proposals and delegates can participate in DAO voting.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://aerodrome.finance/treasury":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Treasury</h1>
                  <p>The protocol treasury receives a share of fees and governance can direct treasury reserves to ecosystem grants.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://aerodrome.finance/fees":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Fees</h1>
                  <p>Protocol revenue comes from trading fees, and veAERO voters direct emissions toward pools generating the most productive liquidity.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Aerodrome", "ticker": "AERO", "coingecko_id": "aerodrome"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert "https://aerodrome.finance/governance" in profile.official_urls["governance"]
    assert "https://aerodrome.finance/treasury" in profile.official_urls["treasury"]
    assert any("locked as veaero" in item.lower() for item in profile.governance_points)
    assert any("fee distribution" in item.lower() for item in profile.value_capture_points)
    assert any("max supply" in item.lower() for item in profile.tokenomics_points)
    assert any("40% to community incentives" in item.lower() for item in profile.token_distribution_points)
    assert any("protocol revenue comes from trading fees" in item.lower() for item in profile.revenue_model_points)
    assert any("treasury receives a share of fees" in item.lower() for item in profile.treasury_points)


def test_docs_profile_extracts_team_partners_and_roadmap_points(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/example-protocol"):
            return httpx.Response(200, json={"links": {"homepage": ["https://example.org"]}})
        if url == "https://dl.example/protocol/example-protocol":
            return httpx.Response(200, json={"slug": "example-protocol", "name": "Example Protocol", "url": "https://example.org"})
        if url == "https://docs.example.org/":
            return httpx.Response(404, text="not found")
        if url == "https://developers.example.org/":
            return httpx.Response(404, text="not found")
        if url == "https://developer.example.org/":
            return httpx.Response(404, text="not found")
        if url == "https://learn.example.org/":
            return httpx.Response(404, text="not found")
        if url == "https://example.org/docs":
            return httpx.Response(404, text="not found")
        if url == "https://example.org/developers":
            return httpx.Response(404, text="not found")
        if url == "https://example.org/developer":
            return httpx.Response(404, text="not found")
        if url == "https://example.org/learn":
            return httpx.Response(404, text="not found")
        if url == "https://example.org/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://example.org/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://example.org/team">Team</a>
                  <a href="https://example.org/partners">Partners</a>
                  <a href="https://example.org/roadmap">Roadmap</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://example.org/team":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Team</h1>
                  <p>Example Protocol was founded by Alice Doe and Bob Roe, who previously built market infrastructure at major DeFi teams.</p>
                  <p>The core team also includes Carol Smith as lead researcher and David Lee as protocol advisor.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://example.org/partners":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Partners</h1>
                  <p>Example Protocol is backed by North Island Ventures and Placeholder, and is integrated with Chainlink for oracle services.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://example.org/roadmap":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Roadmap</h1>
                  <p>The next phase will launch isolated markets, cross-chain collateral support, and a public governance portal.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Example", "ticker": "EXM", "coingecko_id": "example-protocol"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert "https://example.org/team" in profile.official_urls["team"]
    assert "https://example.org/partners" in profile.official_urls["partners"]
    assert "https://example.org/roadmap" in profile.official_urls["roadmap"]
    assert any("founded by alice doe and bob roe" in item.lower() for item in profile.team_points)
    assert any("backed by north island ventures" in item.lower() for item in profile.investor_partner_points)
    assert any("integrated with chainlink" in item.lower() for item in profile.investor_partner_points)
    assert any("next phase will launch isolated markets" in item.lower() for item in profile.roadmap_points)


def test_docs_profile_prioritizes_distribution_percentages_and_fee_flow_points(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/structured-protocol"):
            return httpx.Response(200, json={"links": {"homepage": ["https://structured.org"]}})
        if url == "https://dl.example/protocol/structured-protocol":
            return httpx.Response(200, json={"slug": "structured-protocol", "name": "Structured Protocol", "url": "https://structured.org"})
        if url == "https://docs.structured.org/":
            return httpx.Response(404, text="not found")
        if url == "https://developers.structured.org/":
            return httpx.Response(404, text="not found")
        if url == "https://developer.structured.org/":
            return httpx.Response(404, text="not found")
        if url == "https://learn.structured.org/":
            return httpx.Response(404, text="not found")
        if url == "https://structured.org/docs":
            return httpx.Response(404, text="not found")
        if url == "https://structured.org/developers":
            return httpx.Response(404, text="not found")
        if url == "https://structured.org/developer":
            return httpx.Response(404, text="not found")
        if url == "https://structured.org/learn":
            return httpx.Response(404, text="not found")
        if url == "https://structured.org/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://structured.org/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://structured.org/tokenomics">Tokenomics</a>
                  <a href="https://structured.org/treasury">Treasury</a>
                  <a href="https://structured.org/fees">Fees</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://structured.org/tokenomics":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Tokenomics</h1>
                  <p>SPT has utility across governance and staking.</p>
                  <p>The token distribution allocates 35% to community incentives, 20% to the treasury, 20% to investors, 15% to the core team, and 10% to the foundation.</p>
                  <p>Total supply is capped at 1 billion SPT and investor vesting unlocks linearly over 24 months.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://structured.org/treasury":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Treasury</h1>
                  <p>The treasury receives 20% of protocol fees, and governance can redirect treasury reserves toward grants and liquidity support.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://structured.org/fees":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Fees</h1>
                  <p>Protocol revenue comes from swap fees and liquidation fees.</p>
                  <p>A portion of fees is used to buy back SPT and distribute value to locked token holders.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Structured", "ticker": "SPT", "coingecko_id": "structured-protocol"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.token_distribution_points
    assert "35% to community incentives" in profile.token_distribution_points[0]
    assert any("total supply is capped" in item.lower() for item in profile.tokenomics_points)
    assert profile.treasury_points
    assert "treasury receives 20% of protocol fees" in profile.treasury_points[0].lower()
    assert profile.revenue_model_points
    assert "protocol revenue comes from swap fees" in profile.revenue_model_points[0].lower()
    assert any("buy back spt" in item.lower() for item in profile.value_capture_points)


def test_docs_profile_prioritizes_dex_fee_and_burn_pages_over_welcome_links(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/pancakeswap-token"):
            return httpx.Response(200, json={"links": {"homepage": ["https://pancakeswap.finance"]}})
        if url == "https://dl.example/protocol/pancakeswap-token":
            return httpx.Response(200, json={"slug": "pancakeswap-token", "name": "PancakeSwap", "url": "https://pancakeswap.finance"})
        if url in {
            "https://developers.pancakeswap.finance/",
            "https://developer.pancakeswap.finance/",
            "https://learn.pancakeswap.finance/",
            "https://pancakeswap.finance/docs",
            "https://pancakeswap.finance/developers",
            "https://pancakeswap.finance/developer",
            "https://pancakeswap.finance/learn",
            "https://pancakeswap.finance/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://pancakeswap.finance/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://docs.pancakeswap.finance/">Docs</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.pancakeswap.finance/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://docs.pancakeswap.finance/welcome-to-pancakeswap/how-to-guides">How-to Guides</a>
                  <a href="https://docs.pancakeswap.finance/welcome-to-pancakeswap/roadmap">Roadmap</a>
                  <a href="https://docs.pancakeswap.finance/welcome-to-pancakeswap/info">Info</a>
                  <a href="https://docs.pancakeswap.finance/welcome-to-pancakeswap/about-us">About Us</a>
                  <a href="https://docs.pancakeswap.finance/trade/pancakeswap-exchange/trade">Token Swaps</a>
                  <a href="https://docs.pancakeswap.finance/earn/pancakeswap-pools">Liquidity Pools</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url.startswith("https://docs.pancakeswap.finance/welcome-to-pancakeswap/"):
            return httpx.Response(
                200,
                text="<html><body><p>PancakeSwap community information and user guides.</p></body></html>",
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.pancakeswap.finance/trade/pancakeswap-exchange/trade":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Token Swaps</h1>
                  <p>Token swaps on PancakeSwap are a simple way to trade one token for another via automated liquidity pools.</p>
                  <p>For Exchange V2 liquidity pools, a fixed 0.25% trading fee is applied: 0.17% is returned to Liquidity Pools, 0.0225% is sent to the PancakeSwap Treasury, and 0.0575% is sent towards CAKE buyback and burn.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.pancakeswap.finance/earn/pancakeswap-pools":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Liquidity Pools</h1>
                  <p>Trading fees for Exchange V3 are distributed to Liquidity Providers, CAKE Burn, and Treasury according to each fee tier.</p>
                  <p>CAKE Burn receives a share of total swap fees, permanently removing CAKE to reduce supply.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Cake", "ticker": "CAKE", "coingecko_id": "pancakeswap-token"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path), docs_max_pages=6))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "dex_spot"
    assert any("0.25% trading fee" in item.lower() for item in profile.revenue_model_points)
    assert any("cake buyback and burn" in item.lower() or "cake burn" in item.lower() for item in profile.value_capture_points)
    assert any("pancakeswap treasury" in item.lower() for item in profile.fee_recipient_points)


def test_docs_profile_extracts_vesting_treasury_control_fee_recipients_and_product_token_link(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/link-protocol"):
            return httpx.Response(200, json={"links": {"homepage": ["https://linkproto.org"]}})
        if url == "https://dl.example/protocol/link-protocol":
            return httpx.Response(200, json={"slug": "link-protocol", "name": "Link Protocol", "url": "https://linkproto.org"})
        if url == "https://docs.linkproto.org/":
            return httpx.Response(404, text="not found")
        if url == "https://developers.linkproto.org/":
            return httpx.Response(404, text="not found")
        if url == "https://developer.linkproto.org/":
            return httpx.Response(404, text="not found")
        if url == "https://learn.linkproto.org/":
            return httpx.Response(404, text="not found")
        if url == "https://linkproto.org/docs":
            return httpx.Response(404, text="not found")
        if url == "https://linkproto.org/developers":
            return httpx.Response(404, text="not found")
        if url == "https://linkproto.org/developer":
            return httpx.Response(404, text="not found")
        if url == "https://linkproto.org/learn":
            return httpx.Response(404, text="not found")
        if url == "https://linkproto.org/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://linkproto.org/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://linkproto.org/tokenomics">Tokenomics</a>
                  <a href="https://linkproto.org/governance">Governance</a>
                  <a href="https://linkproto.org/treasury">Treasury</a>
                  <a href="https://linkproto.org/fees">Fees</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://linkproto.org/tokenomics":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Tokenomics</h1>
                  <p>The total supply is fixed at 100 million LINKP.</p>
                  <p>Investor tokens vest with a 12 month cliff and unlock linearly over 24 months.</p>
                  <p>LINKP can be locked to direct emissions toward liquidity pools that route the most trading activity.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://linkproto.org/governance":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Governance</h1>
                  <p>LINKP holders vote on emissions, protocol fee distribution, and treasury allocations.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://linkproto.org/treasury":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Treasury</h1>
                  <p>The DAO can direct treasury reserves toward ecosystem grants and liquidity support programs.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://linkproto.org/fees":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Fees</h1>
                  <p>Protocol revenue comes from swap fees and routing fees.</p>
                  <p>Thirty percent of fees accrues to the treasury while the remainder is distributed to locked LINKP holders.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "LinkProto", "ticker": "LINKP", "coingecko_id": "link-protocol"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert any("12 month cliff" in item.lower() for item in profile.vesting_points)
    assert any("dao can direct treasury reserves" in item.lower() for item in profile.treasury_control_points)
    assert any("distributed to locked linkp holders" in item.lower() for item in profile.fee_recipient_points)
    assert any("locked to direct emissions toward liquidity pools" in item.lower() for item in profile.product_token_link_points)


def test_docs_profile_enriches_topic_urls_from_crawled_docs_pages(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/uni-like"):
            return httpx.Response(200, json={"links": {"homepage": ["https://unilike.org"]}})
        if url == "https://dl.example/protocol/uni-like":
            return httpx.Response(200, json={"slug": "uni-like", "name": "UniLike", "url": "https://unilike.org"})
        if url in {
            "https://docs.unilike.org/",
            "https://developers.unilike.org/",
            "https://developer.unilike.org/",
            "https://learn.unilike.org/",
            "https://unilike.org/developers",
            "https://unilike.org/developer",
            "https://unilike.org/learn",
            "https://unilike.org/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://unilike.org/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://unilike.org/docs">Docs</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://unilike.org/docs":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>UniLike Docs</h1>
                  <p>UniLike provides decentralized trading infrastructure and liquidity routing.</p>
                  <a href="https://unilike.org/docs/governance">Governance</a>
                  <a href="https://unilike.org/docs/tokenomics">Tokenomics</a>
                  <a href="https://unilike.org/docs/treasury">Treasury</a>
                  <a href="https://unilike.org/docs/fees">Fees</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://unilike.org/docs/governance":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Governance</h1>
                  <p>UNIX holders vote on proposals and protocol fee distribution.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://unilike.org/docs/tokenomics":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Tokenomics</h1>
                  <p>Total supply is fixed at 1 billion UNIX.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://unilike.org/docs/treasury":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Treasury</h1>
                  <p>The DAO can direct treasury reserves toward ecosystem grants.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://unilike.org/docs/fees":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Fees</h1>
                  <p>Protocol revenue comes from swap fees and a share accrues to the treasury.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "UniLike", "ticker": "UNIX", "coingecko_id": "uni-like"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert "https://unilike.org/docs/governance" in (profile.official_urls.get("governance") or [])
    assert "https://unilike.org/docs/tokenomics" in (profile.official_urls.get("tokenomics") or [])
    assert "https://unilike.org/docs/treasury" in (profile.official_urls.get("treasury") or [])
    assert any("protocol revenue comes from swap fees" in item.lower() for item in profile.revenue_model_points)
    assert any("dao can direct treasury reserves" in item.lower() for item in profile.treasury_control_points)


def test_docs_profile_extracts_text_from_next_data_json_for_spa_site(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/aerodrome"):
            return httpx.Response(200, json={"links": {"homepage": ["https://aerodrome.finance"]}})
        if url == "https://dl.example/protocol/aerodrome":
            return httpx.Response(200, json={"slug": "aerodrome", "name": "Aerodrome", "url": "https://aerodrome.finance"})
        if url == "https://docs.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://developers.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://developer.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://learn.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/docs":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/developers":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/developer":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/learn":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <script id="__NEXT_DATA__" type="application/json">
                      {
                        "props": {
                          "pageProps": {
                            "hero": {
                              "title": "Aerodrome is the central liquidity hub on Base",
                              "description": "Aerodrome is a decentralized exchange designed to route trading activity and incentives efficiently."
                            },
                            "token": {
                              "utility": "AERO can be locked for governance and emissions voting."
                            }
                          }
                        }
                      }
                    </script>
                  </head>
                  <body><div id="__next"></div></body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Aerodrome", "ticker": "AERO", "coingecko_id": "aerodrome"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.what_the_project_does is not None
    assert (
        "central liquidity hub on base" in profile.what_the_project_does.lower()
        or "decentralized exchange designed to route trading activity" in profile.what_the_project_does.lower()
    )
    assert profile.token_utility_points
    assert any("governance" in item.lower() for item in profile.token_utility_points)


def test_docs_profile_extracts_overview_from_spa_meta_descriptions(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/aerodrome"):
            return httpx.Response(200, json={"links": {"homepage": ["https://aerodrome.finance"]}})
        if url == "https://dl.example/protocol/aerodrome":
            return httpx.Response(200, json={"slug": "aerodrome", "name": "Aerodrome", "url": "https://aerodrome.finance"})
        if url == "https://docs.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://developers.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://developer.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://learn.aerodrome.finance/":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/docs":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/developers":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/developer":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/learn":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/":
            return httpx.Response(
                200,
                text="""
                <!doctype html>
                <html>
                  <head>
                    <title>Aerodrome Finance</title>
                    <meta name="description" content="Aerodrome Finance: The central liquidity hub on Base network." />
                    <meta property="og:description" content="Aerodrome Finance is a next-generation AMM that combines the best of Curve, Convex and Uniswap. Aerodrome NFTs vote on token emissions and receive incentives and fees generated by the protocol." />
                    <script type="module" src="/assets/index.js"></script>
                  </head>
                  <body><div id="root"></div></body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Aerodrome", "ticker": "AERO", "coingecko_id": "aerodrome"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.what_the_project_does is not None
    assert "next-generation amm" in profile.what_the_project_does.lower() or "central liquidity hub" in profile.what_the_project_does.lower()
    assert any("token emissions" in item.lower() or "governance" in item.lower() for item in profile.token_utility_points)


def test_docs_profile_prefers_summary_json_over_navigation_noise_in_developer_docs_shell(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/uniswap"):
            return httpx.Response(200, json={"links": {"homepage": ["https://uniswap.org"]}})
        if url == "https://dl.example/protocol/uniswap":
            return httpx.Response(200, json={"slug": "uniswap", "name": "Uniswap", "url": "https://uniswap.org"})
        if url in {
            "https://docs.uniswap.org/",
            "https://docs.uniswap.org/docs",
            "https://developers.uniswap.org/",
            "https://developer.uniswap.org/",
            "https://developer.uniswap.org/docs",
            "https://learn.uniswap.org/",
            "https://learn.uniswap.org/docs",
            "https://uniswap.org/developers",
            "https://uniswap.org/developer",
            "https://uniswap.org/learn",
            "https://uniswap.org/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://developers.uniswap.org/docs":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <meta property="og:title" content="Uniswap Developers" />
                    <script id="__NEXT_DATA__" type="application/json">
                      {
                        "props": {
                          "pageProps": {
                            "navigation": {
                              "sidebar": [
                                "Developers Docs Quickstart SDK API Reference Concepts Guides Hooks Widgets Routing"
                              ]
                            },
                            "hero": {
                              "title": "Uniswap Developers",
                              "description": "Uniswap provides decentralized trading infrastructure and liquidity routing across supported networks."
                            },
                            "governance": {
                              "summary": "UNI holders can vote on protocol proposals and upgrades."
                            }
                          }
                        }
                      }
                    </script>
                  </head>
                  <body><div id="__next"></div></body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://uniswap.org/":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head><title>Uniswap</title></head>
                  <body><div id="root"></div></body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://uniswap.org/docs":
            return httpx.Response(404, text="not found")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Uni", "ticker": "UNI", "coingecko_id": "uniswap"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.what_the_project_does is not None
    assert "decentralized trading infrastructure" in profile.what_the_project_does.lower()
    assert "quickstart sdk api reference" not in profile.what_the_project_does.lower()
    assert any("uni holders can vote" in item.lower() for item in profile.governance_points)


def test_docs_profile_survives_dns_failure_on_guessed_docs_candidates(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/aerodrome"):
            return httpx.Response(200, json={"links": {"homepage": ["https://aerodrome.finance"]}})
        if url == "https://dl.example/protocol/aerodrome":
            return httpx.Response(200, json={"slug": "aerodrome", "name": "Aerodrome", "url": "https://aerodrome.finance"})
        if url == "https://docs.aerodrome.finance/":
            raise httpx.ConnectError("[Errno -5] No address associated with hostname")
        if url == "https://docs.aerodrome.finance/docs":
            raise httpx.ConnectError("[Errno -5] No address associated with hostname")
        if url == "https://developers.aerodrome.finance/":
            raise httpx.ConnectError("[Errno -5] No address associated with hostname")
        if url == "https://developers.aerodrome.finance/docs":
            raise httpx.ConnectError("[Errno -5] No address associated with hostname")
        if url == "https://developer.aerodrome.finance/":
            raise httpx.ConnectError("[Errno -5] No address associated with hostname")
        if url == "https://developer.aerodrome.finance/docs":
            raise httpx.ConnectError("[Errno -5] No address associated with hostname")
        if url == "https://learn.aerodrome.finance/":
            raise httpx.ConnectError("[Errno -5] No address associated with hostname")
        if url == "https://learn.aerodrome.finance/docs":
            raise httpx.ConnectError("[Errno -5] No address associated with hostname")
        if url == "https://aerodrome.finance/docs":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/developers":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/developer":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/learn":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://aerodrome.finance/":
            return httpx.Response(
                200,
                text="""
                <!doctype html>
                <html>
                  <head>
                    <title>Aerodrome Finance</title>
                    <meta name="description" content="Aerodrome Finance: The central liquidity hub on Base network." />
                    <meta property="og:description" content="Aerodrome Finance is a next-generation AMM that combines the best of Curve, Convex and Uniswap. Aerodrome NFTs vote on token emissions and receive incentives and fees generated by the protocol." />
                  </head>
                  <body><div id="root"></div></body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Aerodrome", "ticker": "AERO", "coingecko_id": "aerodrome"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.what_the_project_does is not None
    assert (
        "central liquidity hub" in profile.what_the_project_does.lower()
        or "next-generation amm" in profile.what_the_project_does.lower()
    )


def test_docs_profile_avoids_false_perp_classification_for_stablecoin_docs_and_filters_non_native_token_utility(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/ethena"):
            return httpx.Response(200, json={"links": {"homepage": ["https://ethena.fi"]}})
        if url == "https://dl.example/protocol/ethena":
            return httpx.Response(200, json={"slug": "ethena", "name": "Ethena", "url": "https://ethena.fi"})
        if url == "https://docs.ethena.fi/":
            return httpx.Response(404, text="not found")
        if url == "https://developers.ethena.fi/":
            return httpx.Response(404, text="not found")
        if url == "https://developer.ethena.fi/":
            return httpx.Response(404, text="not found")
        if url == "https://learn.ethena.fi/":
            return httpx.Response(404, text="not found")
        if url == "https://ethena.fi/docs":
            return httpx.Response(404, text="not found")
        if url == "https://ethena.fi/developers":
            return httpx.Response(404, text="not found")
        if url == "https://ethena.fi/developer":
            return httpx.Response(404, text="not found")
        if url == "https://ethena.fi/learn":
            return httpx.Response(404, text="not found")
        if url == "https://ethena.fi/documentation":
            return httpx.Response(404, text="not found")
        if url == "https://ethena.fi/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://docs.ethena.fi/how-usde-works">How USDe Works</a>
                  <a href="https://docs.ethena.fi/ena">ENA</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.ethena.fi/how-usde-works":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>How USDe Works</h1>
                  <p>A crypto-native synthetic dollar utilizing spot assets as backing, onchain custody, and centralized liquidity venues.</p>
                  <p>Ethena's synthetic dollar, USDe, provides the crypto-native, scalable solution for money achieved by delta-hedging Bitcoin, Ethereum and other governance-approved spot assets using perpetual and deliverable futures contracts, as well as holding liquid stables.</p>
                  <p>The protocol opens a corresponding short perpetual position for the approximate same notional dollar value on a derivatives exchange.</p>
                  <p>Assets backing USDe remain in off-exchange custody and are used for delta-neutral hedging.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.ethena.fi/ena":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>ENA</h1>
                  <p>In this framework, $ENA governance tokenholders are able to delegate everyday decision-making with respect to key aspects of the ecosystem to sophisticated, expert-level stakeholders while retaining transparency during the process.</p>
                  <p>Staked ENA can be obtained by staking ENA.</p>
                  <p>sUSDe is the reward-accruing version of USDe.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Ethena", "ticker": "ENA", "coingecko_id": "ethena"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert all("app.ethena.fi" not in url for url in profile.official_urls.get("website", []))
    assert profile.project_type == "synthetic_dollar"
    assert any("staking ena" in item.lower() or "staked ena" in item.lower() for item in profile.token_utility_points)
    assert all("susde" not in item.lower() for item in profile.token_utility_points)
    assert all("usde" not in item.lower() for item in profile.token_utility_points)


def test_docs_profile_prefers_sky_usds_protocol_over_vault_yield_marketing(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/sky"):
            return httpx.Response(200, json={"links": {"homepage": ["https://sky.money"]}})
        if url == "https://dl.example/protocol/sky":
            return httpx.Response(200, json={"slug": "sky", "name": "Sky", "url": "https://sky.money"})
        if url == "https://sky.money/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://sky.money/docs">Docs</a>
                  <a href="https://sky.money/vaults">Vaults</a>
                  <a href="https://sky.money/sky-ecosystem-rewards">Rewards</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://sky.money/docs":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Sky Protocol</h1>
                  <p>Sky Protocol includes USDS, the decentralized stablecoin upgraded from Dai, and the SKY governance token.</p>
                  <p>Users can generate USDS against collateral, redeem USDS through protocol modules, and participate in Sky governance with SKY.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://sky.money/vaults":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Sky Vaults</h1>
                  <p>Vaults let users deposit collateral and generate USDS positions.</p>
                  <p>Sky Protocol enables market-leading stablecoin yield through savings and reward modules.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://sky.money/sky-ecosystem-rewards":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Sky Ecosystem Rewards</h1>
                  <p>Deposit USDS to earn governance tokens through ecosystem rewards campaigns.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Sky", "ticker": "SKY", "coingecko_id": "sky"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "synthetic_dollar"
    assert profile.business_model == "Issues a crypto-native synthetic dollar backed by collateral, custody, and hedging infrastructure."
    assert all("market-leading stablecoin yield" not in item.lower() for item in profile.token_utility_points)
    assert all("deposit usds to earn governance tokens" not in item.lower() for item in profile.token_utility_points)


def test_docs_profile_extracts_sky_revenue_from_stability_fees_and_surplus(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/sky"):
            return httpx.Response(200, json={"links": {"homepage": ["https://sky.money"]}})
        if url == "https://dl.example/protocol/sky":
            return httpx.Response(200, json={"slug": "sky", "name": "Sky", "url": "https://sky.money"})
        if url == "https://sky.money/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://developers.skyeco.com/">Docs</a>
                  <a href="https://developers.skyeco.com/rates/stability-fees">Stability Fees</a>
                  <a href="https://developers.skyeco.com/modules/surplus-buffer">Surplus Buffer</a>
                  <a href="https://developers.skyeco.com/guides/psm/litepsm">LitePSM</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://developers.skyeco.com/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Sky Protocol</h1>
                  <p>Sky Protocol includes USDS, the decentralized stablecoin upgraded from Dai, and the SKY governance token.</p>
                  <p>Users can generate USDS against collateral and participate in Sky governance with SKY.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://developers.skyeco.com/rates/stability-fees":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Stability Fees</h1>
                  <p>Vault owners pay a stability fee on generated USDS debt, and those fees accrue to the protocol surplus buffer.</p>
                  <p>The Sky Savings Rate is paid from protocol surplus and is adjusted by governance.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://developers.skyeco.com/modules/surplus-buffer":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Surplus Buffer</h1>
                  <p>Protocol surplus collects stability fees, liquidation penalties, and PSM fees before governance allocates surplus through protocol mechanisms.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://developers.skyeco.com/guides/psm/litepsm":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>LitePSM</h1>
                  <p>LitePSM charges fees on swaps between USDS and supported stablecoins, creating spread income for the protocol.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Sky", "ticker": "SKY", "coingecko_id": "sky"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "synthetic_dollar"
    assert any("stability fee" in item.lower() for item in profile.revenue_model_points)
    assert any("surplus" in item.lower() for item in profile.revenue_model_points)
    assert any("psm fees" in item.lower() or "spread income" in item.lower() for item in profile.revenue_model_points)
    assert any("surplus buffer" in item.lower() for item in profile.fee_recipient_points)


def test_docs_profile_filters_sky_upgrade_and_marketing_noise_from_topic_points():
    snippets = [
        {"url": "https://sky.money/", "text": "Stake SKY tokens to earn 13% APY, borrow USDS, and participate in governance."},
        {"url": "https://sky.money/", "text": "A non-custodial DeFi application providing access to Sky Protocol's suite of stablecoin yield products: sUSDS, Sky Vaults, stUSDS, Sky Ecosystem Rewards, and SKY Staking."},
        {"url": "https://sky.money/", "text": "Earn Sky Savings Rate (SSR) via sUSDS Deploy stablecoins into curated Sky Vaults Earn premium yield via stUSDS risk capital Accumulate ecosystem tokens via Sky Ecosystem Rewards Stake SKY tokens for governance and yield Borrow USDS against staked SKY 1:1 USDC"},
        {"url": "https://developers.skyeco.com/guides/sky/token-governance-upgrade/key-info", "text": "All conversions in the upgrade process are executed unidirectionally via the mkrToSky function, with fees applied according to the Delayed Upgrade Penalty schedule post-upgrade."},
        {"url": "https://developers.skyeco.com/guides/upgrades/migrate-old-mkr-to-mkr", "text": "Collect Your Position Data” Check the following before starting the migration: What to Check Why It Matters During Shutdown USDS debt (drawn balance) Must be zero before you can unlock collateral in V1."},
        {"url": "https://developers.skyeco.com/guides/sky/token-governance-upgrade/key-info", "text": "Phase 4 — Communications Done 2025-05-13 A community-wide marketing campaign for the Sky Ecosystem will be launched."},
        {"url": "https://sky.money/", "text": "Your stablecoins don’t have to sit still Protocol updates, upcoming launches and everything you need to stay on top of putting your stablecoins to work."},
        {"url": "https://developers.skyeco.com/protocol/core/vat", "text": "Vault owners pay a stability fee on generated USDS debt, and those fees accrue to the protocol surplus buffer."},
        {"url": "https://developers.skyeco.com/protocol/liquidity/litepsm", "text": "LitePSM charges fees on swaps between USDS and supported stablecoins, creating spread income for the protocol."},
        {"url": "https://sky.money/sky-ecosystem-rewards", "text": "Up to 3.75% APY Ecosystem Rewards Ecosystem Rewards are issued and distributed by Sky Ecosystem partners and Sky Agents."},
        {"url": "https://sky.money/sky-ecosystem-rewards", "text": "Sky.money does not control their issuance, rate, or value; all rewards are variable and subject to market conditions."},
        {"url": "https://sky.money/vaults", "text": "Governed by Sky Ecosystem to deliver the best risk-adjusted yield, sUSDS allows you to grow your holdings with instant liquidity and zero fees."},
        {"url": "https://developers.skyeco.com/guides/sky/token-governance-upgrade/key-info", "text": "Fee Collection Mechanism Fee Collection Mechanism Section titled “Fee Collection Mechanism” Fees collected during conversions accumulate within the Converter contract and are tracked by the internal take variable."},
        {"url": "https://developers.skyeco.com/guides/sky/token-governance-upgrade/integrators", "text": "You can contact the Integrations team at email protected to discuss your specific situation and develop a custom action plan."},
        {"url": "https://developers.skyeco.com/guides/sky/token-governance-upgrade/protocol-participants", "text": "Steps for Governance Delegates Steps for Governance Delegates Section titled “Steps for Governance Delegates” Deploy a V3 Delegate: Call create() on Vote Delegate Factory V3."},
        {"url": "https://vote.sky.money/", "text": "Sky Governance - Governance Portal Sky Governance Sky Governance Voting Portal Voting Portal Vote with or delegate your SKY tokens to help protect the integrity of the Sky protocol How to vote Latest Executive Latest Executive View more Launch Avalanche SkyLink."},
        {"url": "https://vote.sky.money/", "text": "High Impact Risk Parameter Weekly Atlas Edit System Surplus Technical Misc Governance Endgame Multi-Chain Bridge View Details Plurality poll Show me more polls related to High Impact Risk Parameter Technical Weekly Atlas Edit."},
        {"url": "https://sky.money/", "text": "Through Sky.money, you can access SKY, stake it to earn rewards for governance participation, and borrow USDS against your staked SKY for more liquidity."},
        {"url": "https://sky.money/", "text": "10.81% APY SKY Market Cap $1.81B SKY Price $0.0787 Sky Price $0.0787 Sky Market Cap $1.81B SKY Stake Rate SKY is a decentralized governance token of Sky Protocol."},
        {"url": "https://sky.money/", "text": "Sky.money is a non-custodial interface operated by Skybase, an independent Sky Agent with no control over Sky Protocol smart contracts or ecosystem governance."},
        {"url": "https://developers.skyeco.com/protocol/liquidity/litepsm", "text": "Fees are represented as fixed decimal-point numbers with 18 decimals."},
        {"url": "https://developers.skyeco.com/guides/sky/token-governance-upgrade/key-info", "text": "Governance can call the collect function to transfer the accumulated SKY fees from the Converter V2 contract to a designated address."},
        {"url": "https://developers.skyeco.com/guides/sky/token-governance-upgrade/key-info", "text": "Fees cannot be enabled on this route in the future."},
        {"url": "https://developers.skyeco.com/protocol/governance/chief", "text": "Thus, ds-chief can work well as a method for selecting code for execution just as well as it can for realizing political processes."},
        {"url": "https://developers.skyeco.com/protocol/core/vow", "text": "the fixed surplus quantity to be sold by any one surplus auction hump : surplus buffer, must be exceeded before surplus auctions are possible."},
        {"url": "https://sky.money/", "text": "Skybase does not participate in, and has no ability to control or guarantee outcomes of, decentralized governance processes."},
        {"url": "https://sky.money/vaults", "text": "When you deposit USDS into the stUSDS module, your capital funds loans for SKY stakers."},
        {"url": "https://sky.money/vaults", "text": "Sky Vault returns are not governance-set and not guaranteed."},
        {"url": "https://sky.money/sky-ecosystem-rewards", "text": "Deposit USDS to earn Sky Agent governance tokens (e.g., Spark)."},
        {"url": "https://developers.skyeco.com/protocol/rewards/staking-engine", "text": "The LockStake Engine deposits the LSSKY token balance held by the user's vault into their selected staking rewards contracts."},
        {"url": "https://developers.skyeco.com/guides/upgrades/migrate-old-mkr-to-mkr", "text": "Every 3 months after, the penalty will increase by an additional 1%."},
        {"url": "https://developers.skyeco.com/protocol/core/vat", "text": "Rate Updates via fold(bytes32 ilk, address u, int rate) An ilk's rate is the conversion factor between any normalized debt drawn against it and the present value of that debt with accrued fees."},
        {"url": "https://developers.skyeco.com/guides/sky/token-governance-upgrade/overview", "text": "The Sky Ecosystem Governance community has voted to make SKY the sole governance token of the Sky Protocol."},
    ]

    token_utility = _collect_token_utility_points(snippets, target_name="Sky", ticker="SKY")
    value_capture = _collect_value_capture_points(snippets, target_name="Sky", ticker="SKY")
    tokenomics = _collect_tokenomics_points(snippets)
    distribution = _collect_token_distribution_points(snippets)
    revenue = _collect_revenue_model_points(snippets)
    team = _collect_team_points(snippets)
    partners = _collect_investor_partner_points(snippets)
    governance = _collect_governance_points(snippets, target_name="Sky", ticker="SKY")
    treasury = _collect_treasury_points(snippets)
    roadmap = _collect_roadmap_points(snippets)
    combined_noise_sections = token_utility + value_capture + tokenomics + distribution + team + partners + governance + roadmap

    assert token_utility == []
    assert combined_noise_sections == []
    assert any("surplus buffer" in item.lower() for item in treasury)
    assert all("delayed upgrade penalty" not in item.lower() for item in revenue)
    assert all("fee collection mechanism" not in item.lower() for item in revenue)
    assert any("stability fee" in item.lower() for item in revenue)
    assert any("spread income" in item.lower() for item in revenue)


def test_docs_profile_discovers_whitepaper_subdomain_when_homepage_is_js_shell(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/virtual-protocol"):
            return httpx.Response(200, json={"links": {"homepage": ["https://www.virtuals.io"]}})
        if url == "https://dl.example/protocol/virtual-protocol":
            return httpx.Response(200, json={"slug": "virtual-protocol", "name": "Virtuals Protocol", "url": "https://www.virtuals.io"})
        if url in {
            "https://docs.virtuals.io/",
            "https://docs.virtuals.io/docs",
            "https://developers.virtuals.io/",
            "https://developers.virtuals.io/docs",
            "https://developer.virtuals.io/",
            "https://developer.virtuals.io/docs",
            "https://learn.virtuals.io/",
            "https://learn.virtuals.io/docs",
            "https://www.virtuals.io/docs",
            "https://www.virtuals.io/developers",
            "https://www.virtuals.io/developer",
            "https://www.virtuals.io/learn",
            "https://www.virtuals.io/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://whitepaper.virtuals.io/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>About Virtuals Protocol</h1>
                  <p>Virtuals Protocol is a society of AI agents: a coordinated, onchain ecosystem where autonomous agents generate services or products and engage in commerce with humans and other agents.</p>
                  <p>The VIRTUAL token functions as the base liquidity pair and transactional currency across agent interactions.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://www.virtuals.io/":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>Virtuals Protocol</title>
                    <script type="module" src="/assets/app.js"></script>
                    <script type="module" src="/assets/runtime.js"></script>
                    <script type="module" src="/assets/vendor.js"></script>
                  </head>
                  <body><div id="root"></div></body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Virtual", "ticker": "VIRTUAL", "coingecko_id": "virtual-protocol"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert any("whitepaper.virtuals.io" in url for url in profile.docs_urls_read)
    assert profile.what_the_project_does is not None
    assert "society of ai agents" in profile.what_the_project_does.lower()


def test_docs_profile_discovers_developer_subdomain_docs_path_when_homepage_has_no_docs_link(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/uniswap"):
            return httpx.Response(200, json={"links": {"homepage": ["https://uniswap.org"]}})
        if url == "https://dl.example/protocol/uniswap":
            return httpx.Response(200, json={"slug": "uniswap", "name": "Uniswap", "url": "https://uniswap.org"})
        if url in {
            "https://docs.uniswap.org/",
            "https://docs.uniswap.org/docs",
            "https://developers.uniswap.org/",
            "https://developer.uniswap.org/",
            "https://developer.uniswap.org/docs",
            "https://learn.uniswap.org/",
            "https://learn.uniswap.org/docs",
            "https://uniswap.org/docs",
            "https://uniswap.org/developers",
            "https://uniswap.org/developer",
            "https://uniswap.org/learn",
            "https://uniswap.org/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://developers.uniswap.org/docs":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Uniswap Developers Docs</h1>
                  <p>Uniswap provides decentralized trading infrastructure.</p>
                  <p>Liquidity pools enable token swaps and liquidity provisioning across supported networks.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://uniswap.org/":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head><title>Uniswap</title></head>
                  <body><div id="root"></div></body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Uni", "ticker": "UNI", "coingecko_id": "uniswap"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert any("developers.uniswap.org/docs" in url for url in profile.docs_urls_read)
    assert any("developers.uniswap.org/docs" in url for url in (profile.official_urls.get("docs") or []))


def test_docs_profile_discovers_developer_subdomain_nested_intro_path_when_shallow_paths_fail(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/uniswap"):
            return httpx.Response(200, json={"links": {"homepage": ["https://uniswap.org"]}})
        if url == "https://dl.example/protocol/uniswap":
            return httpx.Response(200, json={"slug": "uniswap", "name": "Uniswap", "url": "https://uniswap.org"})
        if url in {
            "https://docs.uniswap.org/",
            "https://docs.uniswap.org/docs",
            "https://docs.uniswap.org/overview",
            "https://docs.uniswap.org/introduction",
            "https://docs.uniswap.org/docs/overview",
            "https://docs.uniswap.org/docs/introduction",
            "https://developers.uniswap.org/",
            "https://developers.uniswap.org/docs",
            "https://developers.uniswap.org/overview",
            "https://developers.uniswap.org/introduction",
            "https://developers.uniswap.org/docs/overview",
            "https://developer.uniswap.org/",
            "https://developer.uniswap.org/docs",
            "https://developer.uniswap.org/overview",
            "https://developer.uniswap.org/introduction",
            "https://developer.uniswap.org/docs/overview",
            "https://developer.uniswap.org/docs/introduction",
            "https://learn.uniswap.org/",
            "https://learn.uniswap.org/docs",
            "https://learn.uniswap.org/overview",
            "https://learn.uniswap.org/introduction",
            "https://learn.uniswap.org/docs/overview",
            "https://learn.uniswap.org/docs/introduction",
            "https://uniswap.org/docs",
            "https://uniswap.org/developers",
            "https://uniswap.org/developer",
            "https://uniswap.org/learn",
            "https://uniswap.org/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://developers.uniswap.org/docs/introduction":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Introduction</h1>
                  <p>Uniswap provides decentralized trading infrastructure and liquidity pools for token swaps.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://uniswap.org/":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head><title>Uniswap</title></head>
                  <body><div id="root"></div></body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Uni", "ticker": "UNI", "coingecko_id": "uniswap"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert any("developers.uniswap.org/docs/introduction" in url for url in profile.docs_urls_read)
    assert any("developers.uniswap.org/docs/introduction" in url for url in (profile.official_urls.get("docs") or []))
    assert profile.what_the_project_does is not None
    assert "decentralized trading infrastructure" in profile.what_the_project_does.lower()


def test_docs_profile_prefers_oracle_over_bridge_for_chainlink_like_docs(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/chainlink"):
            return httpx.Response(200, json={"links": {"homepage": ["https://chain.link"]}})
        if url == "https://dl.example/protocol/chainlink":
            return httpx.Response(200, json={"slug": "chainlink", "name": "Chainlink", "url": "https://chain.link"})
        if url == "https://chain.link/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://docs.chain.link/docs">Docs</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.chain.link/docs":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Chainlink</h1>
                  <p>Chainlink connects blockchains to real-world data, other blockchains, and enterprise systems.</p>
                  <p>Developers use Chainlink Data Feeds and oracle services to build secure applications.</p>
                  <p>Cross-chain messaging is also available through official infrastructure.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Link", "ticker": "LINK", "coingecko_id": "chainlink"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "oracle"


def test_docs_profile_keeps_chainlink_like_docs_as_oracle_with_bridge_secondary_only(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/chainlink"):
            return httpx.Response(200, json={"links": {"homepage": ["https://chain.link"]}})
        if url == "https://dl.example/protocol/chainlink":
            return httpx.Response(200, json={"slug": "chainlink", "name": "Chainlink", "url": "https://chain.link"})
        if url == "https://chain.link/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://docs.chain.link/docs">Docs</a>
                  <a href="https://chain.link/cross-chain">Cross-chain</a>
                  <a href="https://chain.link/economics/staking">Staking</a>
                  <a href="https://chain.link/use-cases/exchanges-trading-venues">Use cases</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.chain.link/docs":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Chainlink</h1>
                  <p>Chainlink connects blockchains to real-world data, other blockchains, and enterprise systems.</p>
                  <p>Developers use Chainlink Data Feeds and oracle services to build secure applications.</p>
                  <p>Chainlink CCIP provides cross-chain messaging and interoperability infrastructure.</p>
                  <a href="https://docs.chain.link/data-feeds">Data Feeds</a>
                  <a href="https://docs.chain.link/ccip">CCIP</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.chain.link/data-feeds":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Data Feeds</h1>
                  <p>Chainlink Data Feeds provide reliable market data and external data for smart contracts.</p>
                  <p>Oracle networks deliver price feeds and reference data onchain.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.chain.link/ccip":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>CCIP</h1>
                  <p>CCIP is Chainlink's cross-chain messaging standard for token transfers and arbitrary messaging across chains.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url in {
            "https://chain.link/cross-chain",
            "https://chain.link/economics/staking",
            "https://chain.link/use-cases/exchanges-trading-venues",
        }:
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Marketing page with broad examples across staking, tokenized assets, exchanges, and cross-chain applications.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Link", "ticker": "LINK", "coingecko_id": "chainlink"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "oracle"
    assert profile.business_model == "Supplies external data and pricing infrastructure to onchain applications."
    assert profile.product_lines[0]["type"] == "oracle"
    secondary_types = [item["type"] for item in profile.product_lines if item.get("role") == "secondary"]
    assert "bridge" in secondary_types
    assert "depin_wireless" not in secondary_types
    assert "liquid_staking" not in secondary_types
    assert "synthetic_dollar" not in secondary_types


def test_docs_profile_ignores_chainlink_marketing_surfaces_for_primary_classification(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/chainlink"):
            return httpx.Response(200, json={"links": {"homepage": ["https://chain.link"]}})
        if url == "https://dl.example/protocol/chainlink":
            return httpx.Response(200, json={"slug": "chainlink", "name": "chainlink", "url": "https://chain.link"})
        if url == "https://chain.link/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://docs.chain.link/docs">Docs</a>
                  <a href="https://dev.chain.link/resources">Dev Resources</a>
                  <a href="https://chain.link/everything">Everything</a>
                  <a href="https://chain.link/build-program">Build</a>
                  <a href="https://chain.link/economics/staking">Staking</a>
                  <a href="https://chain.link/use-cases/exchanges-trading-venues">Exchanges</a>
                  <a href="https://chain.link/cross-chain">Cross-chain</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url in {
            "https://docs.chain.link/docs",
            "https://docs.chain.link",
            "https://docs.chain.link/",
        }:
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Chainlink docs</h1>
                  <p>Chainlink connects blockchains to real-world data, other blockchains, and external systems.</p>
                  <p>Developers use Chainlink Data Feeds and oracle services to build secure applications.</p>
                  <p>CCIP provides cross-chain messaging for apps moving messages and tokens across chains.</p>
                  <a href="https://docs.chain.link/data-feeds">Data Feeds</a>
                  <a href="https://docs.chain.link/resources/link-token-contracts">LINK Token Contracts</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://dev.chain.link/resources":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Developer Resources</h1>
                  <p>Use Data Feeds, CCIP, and oracle services in production applications.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.chain.link/data-feeds":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Data feeds and oracle networks deliver external data to smart contracts.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.chain.link/resources/link-token-contracts":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>LINK is used for payment for oracle services, payment abstraction, and network security.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url in {
            "https://chain.link/everything",
            "https://chain.link/build-program",
            "https://chain.link/economics/staking",
            "https://chain.link/use-cases/exchanges-trading-venues",
            "https://chain.link/cross-chain",
        }:
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Marketing page mentioning staking, rewards, token distributions, exchange venues, tokenized assets, and application growth.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Link", "ticker": "LINK", "coingecko_id": "chainlink"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "oracle"
    assert profile.business_model == "Supplies external data and pricing infrastructure to onchain applications."
    assert "feeds" in profile.key_product_entities
    assert "data" in profile.key_product_entities
    secondary_types = [item["type"] for item in profile.product_lines if item.get("role") == "secondary"]
    assert "bridge" in secondary_types
    assert "liquid_staking" not in secondary_types
    assert "synthetic_dollar" not in secondary_types
    assert "dex_spot" not in secondary_types


def test_docs_profile_treats_liquid_staking_and_stablecoin_asset_classes_as_oracle_context_for_chainlink_like_docs(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/chainlink"):
            return httpx.Response(200, json={"links": {"homepage": ["https://chain.link"]}})
        if url == "https://dl.example/protocol/chainlink":
            return httpx.Response(200, json={"slug": "chainlink", "name": "Chainlink", "url": "https://chain.link"})
        if url == "https://chain.link/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://docs.chain.link/docs">Docs</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url in {"https://docs.chain.link/docs", "https://docs.chain.link/", "https://docs.chain.link"}:
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Chainlink connects blockchains to real-world data, other blockchains, and external systems.</p>
                  <p>Developers use Chainlink Data Feeds and oracle services to build secure applications.</p>
                  <a href="https://docs.chain.link/data-feeds">Data Feeds</a>
                  <a href="https://docs.chain.link/resources/link-token-contracts">LINK Token Contracts</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.chain.link/data-feeds":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Liquid Staking Tokens (LSTs) and Liquid Restaking Tokens (LRTs) are supported asset categories for Chainlink Data Feeds.</p>
                  <p>Users should build applications with the understanding that data feeds for wrapped or liquid staking assets might have different thresholds.</p>
                  <p>Stablecoins, tokenized assets, and market data are delivered through oracle networks.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.chain.link/resources/link-token-contracts":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Payment for oracle services and payment abstraction are core LINK token functions.</p>
                  <p>In exchange for helping secure the network, stakers receive staking rewards.</p>
                  <p>Payments can be converted into LINK tokens using decentralized exchange infrastructure.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Link", "ticker": "LINK", "coingecko_id": "chainlink"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "oracle"
    assert profile.business_model == "Supplies external data and pricing infrastructure to onchain applications."
    secondary_types = [item["type"] for item in profile.product_lines if item.get("role") == "secondary"]
    assert "liquid_staking" not in secondary_types
    assert "synthetic_dollar" not in secondary_types
    assert "dex_spot" not in secondary_types


def test_docs_profile_prefers_interoperability_bridge_over_blockchain_for_layerzero_like_docs(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/layerzero"):
            return httpx.Response(200, json={"links": {"homepage": ["https://layerzero.network"]}})
        if url == "https://dl.example/protocol/layerzero":
            return httpx.Response(200, json={"slug": "layerzero", "name": "LayerZero", "url": "https://layerzero.network"})
        if url in {
            "https://developers.layerzero.network/",
            "https://developer.layerzero.network/",
            "https://learn.layerzero.network/",
            "https://layerzero.network/docs",
            "https://layerzero.network/developers",
            "https://layerzero.network/developer",
            "https://layerzero.network/learn",
            "https://layerzero.network/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://layerzero.network/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://docs.layerzero.network/">Docs</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.layerzero.network/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>LayerZero Docs</h1>
                  <a href="https://docs.layerzero.network/v2/concepts/getting-started/what-is-layerzero">What is LayerZero</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.layerzero.network/v2/concepts/getting-started/what-is-layerzero":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>What is LayerZero</h1>
                  <p>LayerZero is an interoperability protocol that enables applications to send messages across chains.</p>
                  <p>Developers use LayerZero Endpoints, OApps, and workers to build omnichain applications.</p>
                  <p>The protocol connects blockchains without operating as a layer 1 or layer 2 blockchain.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Zro", "ticker": "ZRO", "coingecko_id": "layerzero"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "bridge"
    assert profile.business_model == "Provides cross-chain messaging and interoperability infrastructure for applications across chains."
    assert "messages" in profile.key_product_entities
    assert profile.classification_flags["blockchain"] is False


def test_docs_profile_prefers_payment_blockchain_over_generic_interoperability_for_stellar_like_docs(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/stellar"):
            return httpx.Response(200, json={"links": {"homepage": ["https://www.stellar.org/"]}})
        if url == "https://dl.example/protocol/stellar":
            return httpx.Response(200, json={"slug": "stellar", "name": "Stellar", "url": "https://www.stellar.org/"})
        if url in {
            "https://docs.stellar.org/",
            "https://developer.stellar.org/",
            "https://learn.stellar.org/",
            "https://www.stellar.org/docs",
            "https://www.stellar.org/developer",
            "https://www.stellar.org/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://www.stellar.org/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Stellar</h1>
                  <a href="https://developers.stellar.org/docs">Dev Docs</a>
                  <a href="https://stellar.org/use-cases/payments">Payments</a>
                  <a href="https://stellar.org/use-cases/tokenization">Tokenization</a>
                  <p>Stellar is an open source decentralized network for payments and asset tokenization.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://developers.stellar.org/":
            return httpx.Response(404, text="not found")
        if url == "https://developers.stellar.org/docs":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Stellar Developers</h1>
                  <a href="https://developers.stellar.org/docs/learn/fundamentals/lumens">Lumens</a>
                  <a href="https://developers.stellar.org/docs/learn/fundamentals/fees-resource-limits-metering">Fees</a>
                  <p>Developers use Horizon API endpoints to submit transactions to the Stellar network.</p>
                  <p>The network supports accounts, trustlines, assets, ledgers, validators, and smart contract transactions.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://developers.stellar.org/docs/learn/fundamentals/lumens":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Lumens</h1>
                  <p>Lumens (XLM) are the native currency of the Stellar network.</p>
                  <p>They are used to pay all transaction fees, fund rent, and cover minimum balance requirements on the public network.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://developers.stellar.org/docs/learn/fundamentals/fees-resource-limits-metering":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Fees</h1>
                  <p>Stellar requires a fee for all transactions to make it to the ledger, and all fees are paid using the native Stellar token, the lumen or XLM.</p>
                  <p>This interoperability with financial rails is about payments and tokenized assets, not cross-chain messaging.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://stellar.org/use-cases/payments":
            return httpx.Response(
                200,
                text="<html><body><p>Stellar supports fast cross-border payments and payment operations.</p></body></html>",
                headers={"content-type": "text/html"},
            )
        if url == "https://stellar.org/use-cases/tokenization":
            return httpx.Response(
                200,
                text="<html><body><p>Assets can be issued and tokenized on the Stellar blockchain.</p></body></html>",
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Xlm", "ticker": "XLM", "coingecko_id": "stellar"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "blockchain"
    assert profile.project_subtype == "payments_tokenization_l1"
    assert profile.business_model == "Provides a public blockchain network for payments, asset issuance, tokenization, and smart-contract transactions."
    assert profile.classification_flags["bridge"] is False
    assert "transactions" in profile.key_product_entities
    assert any("transaction fees" in item.lower() or "fees are paid" in item.lower() for item in profile.revenue_model_points)


def test_docs_profile_drops_secondary_lines_for_blockchain_when_only_generic_site_pages_match(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/cardano"):
            return httpx.Response(200, json={"links": {"homepage": ["https://cardano.org/"]}})
        if url == "https://dl.example/protocol/cardano":
            return httpx.Response(200, json={"slug": "cardano", "name": "Cardano", "url": "https://cardano.org/"})
        if url in {
            "https://docs.cardano.org/",
            "https://developers.cardano.org/",
            "https://developer.cardano.org/",
            "https://learn.cardano.org/",
            "https://cardano.org/docs",
            "https://cardano.org/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://cardano.org/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Cardano</h1>
                  <a href="https://cardano.org/get-started">Get Started</a>
                  <a href="https://cardano.org/developers">Developers</a>
                  <a href="https://cardano.org/ouroboros">Ouroboros</a>
                  <a href="https://cardano.org/use-cases/oracle">Oracle</a>
                  <a href="https://cardano.org/use-cases/gaming">Gaming</a>
                  <a href="https://cardano.org/use-cases/stablecoins">Stablecoins</a>
                  <p>Cardano is a public blockchain network for payments, asset issuance, tokenization, and smart-contract transactions.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://cardano.org/get-started":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Users can send payments, issue native assets, and settle smart-contract transactions on Cardano.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://cardano.org/developers":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Developers build tokenization and payment applications on the Cardano blockchain.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://cardano.org/ouroboros":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Ouroboros is the proof-of-stake protocol securing the Cardano blockchain and validator set.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url in {
            "https://cardano.org/use-cases/oracle",
            "https://cardano.org/use-cases/gaming",
            "https://cardano.org/use-cases/stablecoins",
        }:
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Generic ecosystem page describing what teams may build on Cardano in this category.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Ada", "ticker": "ADA", "coingecko_id": "cardano"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "blockchain"
    assert profile.project_subtype == "payments_tokenization_l1"
    secondary_types = [item["type"] for item in profile.product_lines if item.get("role") == "secondary"]
    assert secondary_types == []


def test_docs_profile_classifies_helium_like_depin_wireless_and_extracts_data_credit_model(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/helium"):
            return httpx.Response(200, json={"links": {"homepage": ["https://www.helium.com/"]}})
        if url == "https://dl.example/protocol/helium":
            return httpx.Response(200, json={"slug": "helium", "name": "Helium", "url": "https://www.helium.com/"})
        if url in {
            "https://developers.helium.com/",
            "https://developer.helium.com/",
            "https://learn.helium.com/",
            "https://www.helium.com/docs",
            "https://www.helium.com/developers",
            "https://www.helium.com/developer",
            "https://www.helium.com/learn",
            "https://www.helium.com/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://www.helium.com/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Helium</h1>
                  <a href="https://docs.helium.com/">Docs</a>
                  <a href="https://www.helium.com/hnt">HNT</a>
                  <a href="https://www.helium.com/iot">IoT</a>
                  <p>Helium is a decentralized wireless network where Hotspots provide IoT and Mobile coverage.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.helium.com/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Helium Docs</h1>
                  <a href="https://docs.helium.com/tokens/hnt-token">HNT Token</a>
                  <a href="https://docs.helium.com/tokens/data-credit">Data Credits</a>
                  <a href="https://docs.helium.com/mobile/5g-on-helium">5G on Helium</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://www.helium.com/hnt":
            return httpx.Response(
                200,
                text="<html><body><p>HNT powers the Helium Network and supports hotspot rewards for coverage.</p></body></html>",
                headers={"content-type": "text/html"},
            )
        if url == "https://www.helium.com/iot":
            return httpx.Response(
                200,
                text="<html><body><p>The Helium IoT Network uses LoRaWAN Hotspots to provide wireless network coverage for devices.</p></body></html>",
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.helium.com/tokens/hnt-token":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>The Helium Network Token</h1>
                  <p>HNT is the native cryptocurrency and protocol token of the Helium Network.</p>
                  <p>Hotspot Hosts and Operators are rewarded in HNT while deploying and maintaining network coverage.</p>
                  <p>Enterprises and Developers use the Helium Network to connect devices and build network applications. Data Credits, which are a USD-pegged utility token derived from HNT, are used to pay transaction fees for wireless data transmissions on the Network.</p>
                  <p>Data Credits are only produced by burning HNT. This relationship is called burn and mint economics.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.helium.com/tokens/data-credit":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Data Credit</h1>
                  <p>Data Credits are the mechanism by which all Helium network usage is paid for.</p>
                  <p>DCs are used for data transfer on both the IoT and Mobile subnetworks and for onboarding a Hotspot.</p>
                  <p>At a network level, DCs are only generated through the conversion of HNT.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.helium.com/mobile/5g-on-helium":
            return httpx.Response(
                200,
                text="<html><body><p>The Mobile Network uses radios and Hotspots to provide decentralized wireless coverage.</p></body></html>",
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Helium", "ticker": "HNT", "coingecko_id": "helium"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "depin_wireless"
    assert profile.business_model == "Provides decentralized wireless network infrastructure where hotspots supply IoT or mobile coverage and users pay for network usage."
    assert profile.classification_flags["blockchain"] is True
    assert "hotspots" in profile.key_product_entities
    assert any("data credits" in item.lower() and "burn" in item.lower() for item in profile.value_capture_points)
    assert any("data credits" in item.lower() for item in profile.revenue_model_points)


def test_docs_profile_extracts_curve_fee_architecture_and_prefers_amm_subtype(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/curve-dao-token"):
            return httpx.Response(200, json={"links": {"homepage": ["https://curve.finance"]}})
        if url == "https://dl.example/protocol/curve-dao-token":
            return httpx.Response(200, json={"slug": "curve-dao-token", "name": "Curve", "url": "https://curve.finance"})
        if url in {
            "https://docs.curve.finance/",
            "https://developers.curve.finance/",
            "https://developer.curve.finance/",
            "https://learn.curve.finance/",
            "https://curve.finance/developers",
            "https://curve.finance/developer",
            "https://curve.finance/learn",
            "https://curve.finance/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://curve.finance/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://docs.curve.finance">Docs</a>
                  <a href="https://docs.curve.finance/fee-architecture">Fee Architecture</a>
                  <a href="https://docs.curve.finance/user/curve-tokens/crv">CRV</a>
                  <a href="https://docs.curve.finance/developer/amm/curve-amm-overview">Curve AMM Overview</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.curve.finance":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Curve Docs</h1>
                  <p>Curve is an automated market maker designed for efficient stable asset trading with liquidity pools.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.curve.finance/fee-architecture":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Fee Architecture</h1>
                  <p>Curve fee architecture routes swap fees through pool fee parameters and admin fees.</p>
                  <p>A share of admin fees accrues to veCRV holders while protocol fees are retained by the DAO.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.curve.finance/user/curve-tokens/crv":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>CRV</h1>
                  <p>CRV is the governance token of Curve Finance, used for voting and earning protocol fees through veCRV.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.curve.finance/developer/amm/curve-amm-overview":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Curve AMM Overview</h1>
                  <p>Curve AMM uses liquidity pools and stableswap mechanics for efficient spot trading.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Curve", "ticker": "CRV", "coingecko_id": "curve-dao-token"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "dex_spot"
    assert profile.project_subtype == "amm_spot_dex"
    assert any("fee architecture" in item.lower() or "admin fees" in item.lower() for item in profile.revenue_model_points)
    assert any("vecrv" in item.lower() or "earning protocol fees" in item.lower() for item in profile.value_capture_points)


def test_docs_profile_extracts_aave_revenue_model_from_reserve_factor_language(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/aave"):
            return httpx.Response(200, json={"links": {"homepage": ["https://aave.com"]}})
        if url == "https://dl.example/protocol/aave":
            return httpx.Response(200, json={"slug": "aave", "name": "Aave", "url": "https://aave.com"})
        if url in {
            "https://developers.aave.com/",
            "https://developer.aave.com/",
            "https://learn.aave.com/",
            "https://aave.com/developers",
            "https://aave.com/developer",
            "https://aave.com/learn",
            "https://aave.com/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://aave.com/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://aave.com/help">Help</a>
                  <a href="https://aave.com/help/borrowing">Borrowing</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://aave.com/help":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Aave Help</h1>
                  <p>Aave is an open source liquidity protocol where users supply assets to earn yield and borrow against collateral.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://aave.com/help/borrowing":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Borrowing</h1>
                  <p>Borrowers pay interest and a reserve factor directs a share of protocol fees to the protocol treasury.</p>
                  <p>The protocol captures revenue from reserve spreads and protocol fees across lending markets.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Aave", "ticker": "AAVE", "coingecko_id": "aave"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "lending"
    assert any("reserve factor" in item.lower() or "reserve spreads" in item.lower() for item in profile.revenue_model_points)


def test_docs_profile_classifies_morpho_style_lending_with_vaults_without_chain_shell_noise(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cg.example/coins/morpho"):
            return httpx.Response(200, json={"links": {"homepage": ["https://morpho.org"]}})
        if url == "https://dl.example/protocol/morpho":
            return httpx.Response(200, json={"slug": "morpho", "name": "Morpho", "url": "https://morpho.org"})
        if url in {
            "https://developers.morpho.org/",
            "https://developer.morpho.org/",
            "https://learn.morpho.org/",
            "https://morpho.org/developers",
            "https://morpho.org/developer",
            "https://morpho.org/learn",
            "https://morpho.org/documentation",
        }:
            return httpx.Response(404, text="not found")
        if url == "https://morpho.org/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://docs.morpho.org/">Docs</a>
                  <nav>Products Consumer Vaults Markets Prime Curate Rewards Infra API SDK Bitcoin Sui Sei</nav>
                  <p>Morpho is a lending protocol for crypto-backed loans and permissionless lending markets.</p>
                  <p>Vault curation lets teams build lending products that scale.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.morpho.org/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://docs.morpho.org/learn/concepts/overview">Overview</a>
                  <a href="https://docs.morpho.org/learn/concepts/governance-fees">Governance and fees</a>
                  <a href="https://docs.morpho.org/curate">Curate</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.morpho.org/learn/concepts/overview":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Overview</h1>
                  <p>Morpho is a decentralized protocol enabling overcollateralized lending and borrowing of crypto assets.</p>
                  <p>The protocol serves as a trustless base layer for lenders, borrowers, and applications.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.morpho.org/learn/concepts/governance-fees":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Governance and Fees</h1>
                  <p>Morpho has a fee switch built into the protocol.</p>
                  <p>Governance can enable a fee ranging from 0% to 25% of the total interest amount paid by borrowers for a given market.</p>
                  <p>If activated, revenue from fees would go directly to Morpho DAO.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.morpho.org/curate":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>Curate</h1>
                  <p>Morpho Vault creators have the option to set performance fees at the vault level.</p>
                  <p>Vaults are a way to run a scalable lending business on top of Morpho markets.</p>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(target={"name": "Morpho", "ticker": "MORPHO", "coingecko_id": "morpho"})
    )
    builder = DocumentationProfileBuilder(_settings(profile_cache_dir=str(tmp_path)))

    async def run() -> ProjectProfile:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await builder.build(request, client=client, deadline_at=time.monotonic() + 5)

    profile = asyncio.run(run())

    assert profile.project_type == "lending"
    assert profile.classification_flags["lending"] is True
    assert profile.classification_flags["vault_yield"] is True
    assert profile.supported_chains == []
    assert any("fee switch" in item.lower() or "interest amount paid by borrowers" in item.lower() for item in profile.revenue_model_points)
    assert any("performance fees" in item.lower() for item in profile.revenue_model_points)
