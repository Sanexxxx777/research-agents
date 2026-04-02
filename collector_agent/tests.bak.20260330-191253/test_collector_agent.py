from __future__ import annotations

import asyncio

import httpx

from collector_agent.config import Settings
from collector_agent.contracts import CollectorRequest, CollectorResponse, Provenance, Quality, SourceResult, TargetRef
from collector_agent.http_app import app
from collector_agent.service import CollectorAgentService
from collector_agent.sources import build_default_adapters


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


def _success_result(source: str, *, metrics=None, items=None) -> SourceResult:
    return SourceResult(
        source=source,
        method="api",
        elapsed_ms=0,
        success=True,
        metrics=metrics,
        items=items,
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
        lambda: Settings(
            service_token="secret",
            http_timeout_seconds=10,
            coingecko_base_url="https://cg.example",
            defillama_base_url="https://dl.example",
        ),
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
        lambda: Settings(
            service_token="secret",
            http_timeout_seconds=10,
            coingecko_base_url="https://cg.example",
            defillama_base_url="https://dl.example",
        ),
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
        lambda: Settings(
            service_token="",
            http_timeout_seconds=10,
            coingecko_base_url="https://cg.example",
            defillama_base_url="https://dl.example",
        ),
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
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = CollectorAgentService(
        settings=Settings(
            service_token="",
            http_timeout_seconds=10,
            coingecko_base_url="https://cg.example",
            defillama_base_url="https://dl.example",
        ),
        adapters=build_default_adapters(
            Settings(
                service_token="",
                http_timeout_seconds=10,
                coingecko_base_url="https://cg.example",
                defillama_base_url="https://dl.example",
            )
        ),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None),
    )

    response = asyncio.run(service.collect(CollectorRequest.model_validate(_request_payload())))

    assert response.status == "ok"
    assert len(response.source_results) == 2
    assert response.source_results[0].metrics["price_usd"] == 100000
    assert response.source_results[1].metrics["tvl"] == 123456789
    cg_item = response.source_results[0].items[0]
    dl_item = response.source_results[1].items[0]
    assert cg_item["content_type"] == "metric"
    assert dl_item["content_type"] == "protocol_data"
    assert cg_item["metadata"]["official_links"]["github"] == "https://github.com/bitcoin/bitcoin"
    assert dl_item["metadata"]["website"] == "https://bitcoin.org"


def test_partial_when_one_source_fails():
    request = CollectorRequest.model_validate(_request_payload())
    service = CollectorAgentService(
        settings=Settings(
            service_token="",
            http_timeout_seconds=10,
            coingecko_base_url="https://cg.example",
            defillama_base_url="https://dl.example",
        ),
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


def test_timeout_deadline_behavior():
    request = CollectorRequest.model_validate(_request_payload(deadline_sec=0.01))
    service = CollectorAgentService(
        settings=Settings(
            service_token="",
            http_timeout_seconds=10,
            coingecko_base_url="https://cg.example",
            defillama_base_url="https://dl.example",
        ),
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
        settings=Settings(
            service_token="",
            http_timeout_seconds=10,
            coingecko_base_url="https://cg.example",
            defillama_base_url="https://dl.example",
        ),
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


def test_dune_placeholder_is_extension_point():
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
        settings=Settings(
            service_token="",
            http_timeout_seconds=10,
            coingecko_base_url="https://cg.example",
            defillama_base_url="https://dl.example",
        ),
        adapters=build_default_adapters(
            Settings(
                service_token="",
                http_timeout_seconds=10,
                coingecko_base_url="https://cg.example",
                defillama_base_url="https://dl.example",
            )
        ),
        client_factory=_NoopAsyncClient,
    )

    response = asyncio.run(service.collect(request))

    assert response.status == "error"
    assert response.source_results[0].error.code == "not_implemented"
