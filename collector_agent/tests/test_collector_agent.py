from __future__ import annotations

import asyncio
from pathlib import Path
import time
from typing import Any

import httpx

from collector_agent.config import Settings
from collector_agent.contracts import CollectorRequest, CollectorResponse, Provenance, Quality, SourceResult, TargetRef
from collector_agent.docs_profile import DocumentationProfileBuilder, ProjectProfile, ProjectProfileCache
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
        "dune_api_key": "",
        "dune_base_url": "https://api.dune.com/api/v1",
        "dune_query_timeout_seconds": 25.0,
        "dune_poll_interval_seconds": 1.0,
        "dune_query_ids": {},
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


class _DuneGapAdapter:
    def __init__(self, *, expected_asset_type: str, return_metrics: dict[str, Any] | None = None) -> None:
        self.expected_asset_type = expected_asset_type
        self.return_metrics = return_metrics or {}
        self.last_gap_metrics: list[str] = []

    async def collect(
        self,
        request: CollectorRequest,
        *,
        client,
        deadline_at: float,
        gap_metrics: list[str] | None = None,
        asset_type: str = "unknown_other",
    ) -> SourceResult:
        del request, client, deadline_at
        assert asset_type == self.expected_asset_type
        self.last_gap_metrics = list(gap_metrics or [])
        return _success_result("dune", metrics=self.return_metrics, metadata={"gap_metrics": self.last_gap_metrics})


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
    assert "active_addresses" in response.diagnostics["unavailable_until_dune"]
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


def test_dune_source_returns_key_missing_without_api_key():
    request = CollectorRequest.model_validate(
        _request_payload(
            sources=["dune"],
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
        adapters=build_default_adapters(_settings()),
        client_factory=_NoopAsyncClient,
    )

    response = asyncio.run(service.collect(request))

    assert response.status == "error"
    assert response.source_results[0].error.code == "key_missing"
    assert response.diagnostics["asset_type"] == "unknown_other"


def test_dune_gap_fill_runs_after_defillama_and_marks_metric_found():
    request = CollectorRequest.model_validate(
        _request_payload(
            sources=["defillama", "dune"],
            target={"name": "Hyperliquid", "ticker": "HYPE", "coingecko_id": "hyperliquid"},
        )
    )
    dune = _DuneGapAdapter(
        expected_asset_type="perp_dex",
        return_metrics={"active_traders": 12345.0, "funding_rate": 0.0002},
    )
    service = CollectorAgentService(
        settings=_settings(dune_api_key="test", dune_query_ids={"perp_dex": 123}),
        adapters={
            "defillama": _StaticAdapter(
                _success_result(
                    "defillama",
                    metrics={
                        "trading_volume_24h": 120_000_000.0,
                        "open_interest_usd": 320_000_000.0,
                        "fees_24h": 350_000.0,
                        "protocol_revenue_24h": 110_000.0,
                    },
                    metadata={"category": "Derivatives"},
                    items=[
                        {
                            "metadata": {
                                "competitors": [
                                    {"name": "dYdX", "volume_24h": 50_000_000.0},
                                ],
                                "target_snapshot": {"volume_24h": 120_000_000.0},
                            }
                        }
                    ],
                )
            ),
            "dune": dune,
        },
        client_factory=_NoopAsyncClient,
    )

    response = asyncio.run(service.collect(request))

    assert response.status == "ok"
    assert "active_traders" in dune.last_gap_metrics
    assert any(result.source == "dune" and result.success for result in response.source_results)
    assert "active_traders" in response.diagnostics["found_metrics"]


def test_dune_source_executes_query_and_maps_gap_metrics():
    async def handler(request: httpx.Request) -> httpx.Response:
        path = str(request.url.path)
        if path.endswith("/query/123/execute"):
            return httpx.Response(200, json={"execution_id": "exec-1"})
        if path.endswith("/execution/exec-1/status"):
            return httpx.Response(200, json={"state": "QUERY_STATE_COMPLETED"})
        if path.endswith("/execution/exec-1/results"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "rows": [
                            {
                                "open_interest_usd": 321_000_000.0,
                                "active_traders": 4200,
                                "funding_rate": 0.00031,
                            }
                        ]
                    }
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    request = CollectorRequest.model_validate(
        _request_payload(
            target={"name": "Hyperliquid", "ticker": "HYPE", "coingecko_id": "hyperliquid"},
            sources=["dune"],
        )
    )
    source = build_default_adapters(
        _settings(
            dune_api_key="test-key",
            dune_base_url="https://dune.example/api/v1",
            dune_query_ids={"perp_dex": 123},
            dune_poll_interval_seconds=0.01,
        )
    )["dune"]

    async def run() -> SourceResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None) as client:
            return await source.collect(
                request,
                client=client,
                deadline_at=time.monotonic() + 2,
                gap_metrics=["open_interest", "active_traders", "funding_rate"],
                asset_type="perp_dex",
            )

    result = asyncio.run(run())

    assert result.success is True
    assert result.metrics is not None
    assert result.metrics["open_interest"] == 321_000_000.0
    assert result.metrics["open_interest_usd"] == 321_000_000.0
    assert result.metrics["active_traders"] == 4200
    assert result.metrics["funding_rate"] == 0.00031
    assert result.metadata["query_id"] == 123


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
    assert diagnostics["source_priority"] == ["defillama", "future:dune"]
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
    assert "deposits" in diagnostics["unavailable_until_dune"]
    assert "borrows" in diagnostics["unavailable_until_dune"]
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


def test_rule_layer_marks_perp_dex_dune_gap_honestly():
    request = CollectorRequest.model_validate(
        _request_payload(
            target={"name": "Hyperliquid", "ticker": "HYPE", "coingecko_id": "hyperliquid"},
            sources=["defillama"],
        )
    )
    result = _success_result(
        "defillama",
        metrics={"volume_24h": 900_000_000.0},
        metadata={"category": "Derivatives"},
        items=[
            {
                "metadata": {
                    "competitors": [{"name": "dYdX", "volume_24h": 300_000_000.0}],
                    "target_snapshot": {"volume_24h": 900_000_000.0},
                }
            }
        ],
    )

    diagnostics = build_agent_diagnostics(request, [result])

    assert diagnostics["asset_type"] == "perp_dex"
    assert "trading_volume" in diagnostics["found_metrics"]
    assert "market_share" in diagnostics["found_metrics"]
    assert "open_interest" in diagnostics["not_found_metrics"]
    assert "active_traders" in diagnostics["unavailable_until_dune"]
    assert "fees" in diagnostics["not_found_metrics"]


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
    assert "active_traders" in diagnostics["unavailable_until_dune"]


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
