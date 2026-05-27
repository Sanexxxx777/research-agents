import asyncio

import httpx
import pytest

import market_intel_agent.project_analysis.sources as sources_module
from market_intel_agent.project_analysis.sources import DefiLlamaBudgetExceeded, ProjectAnalysisSources


def test_defillama_call_budget_exhaustion_flag_and_exception():
    sources = ProjectAnalysisSources(
        config={"project_analysis": {"defillama_max_calls_per_run": 2}},
        cache=None,
    )

    sources._register_network_call("defillama")
    sources._register_network_call("defillama")

    with pytest.raises(DefiLlamaBudgetExceeded):
        sources._register_network_call("defillama")

    assert sources._defillama_budget_exhausted is True


def test_defillama_retry_delay_prefers_retry_after_header():
    sources = ProjectAnalysisSources(
        config={"project_analysis": {"defillama_retry_backoff_ms": 500}},
        cache=None,
    )

    response = httpx.Response(429, headers={"retry-after": "3"})
    assert sources._defillama_retry_delay(response=response, attempt=1) == 3.0

    fallback_response = httpx.Response(503, headers={"retry-after": "abc"})
    assert sources._defillama_retry_delay(response=fallback_response, attempt=2) == 1.0


def test_coingecko_retry_delay_prefers_retry_after_header():
    sources = ProjectAnalysisSources(
        config={"project_analysis": {"coingecko_retry_backoff_ms": 500}},
        cache=None,
    )

    response = httpx.Response(429, headers={"retry-after": "3"})
    assert sources._coingecko_retry_delay(response=response, attempt=1) == 3.0

    fallback_response = httpx.Response(503, headers={"retry-after": "abc"})
    assert sources._coingecko_retry_delay(response=fallback_response, attempt=2) == 1.0


def test_cached_get_json_retries_coingecko_http_429(monkeypatch):
    responses = [
        httpx.Response(
            429,
            headers={"retry-after": "0"},
            request=httpx.Request("GET", "https://api.coingecko.com/api/v3/search"),
        ),
        httpx.Response(
            200,
            json={"coins": [{"id": "aave"}]},
            request=httpx.Request("GET", "https://api.coingecko.com/api/v3/search"),
        ),
    ]
    call_count = {"n": 0}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            call_count["n"] += 1
            return responses.pop(0)

    monkeypatch.setattr(sources_module.httpx, "AsyncClient", _Client)

    sources = ProjectAnalysisSources(
        config={"project_analysis": {"coingecko_retry_max": 2, "coingecko_retry_backoff_ms": 0}},
        cache=None,
    )
    loop = asyncio.get_event_loop()
    payload = loop.run_until_complete(
        sources._cached_get_json(
            cache_key="pa:test:cg:429",
            url="https://api.coingecko.com/api/v3/search",
            params={"query": "aave"},
            source="coingecko",
        )
    )

    assert payload == {"coins": [{"id": "aave"}]}
    assert call_count["n"] == 2
    assert sources._network_call_counters.get("coingecko") == 2


def test_cached_get_json_retries_coingecko_transport_error(monkeypatch):
    call_count = {"n": 0}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise httpx.RequestError("transport fail", request=httpx.Request("GET", url))
            return httpx.Response(200, json={"ok": True}, request=httpx.Request("GET", url))

    monkeypatch.setattr(sources_module.httpx, "AsyncClient", _Client)

    sources = ProjectAnalysisSources(
        config={"project_analysis": {"coingecko_retry_max": 2, "coingecko_retry_backoff_ms": 0}},
        cache=None,
    )
    loop = asyncio.get_event_loop()
    payload = loop.run_until_complete(
        sources._cached_get_json(
            cache_key="pa:test:cg:transport",
            url="https://api.coingecko.com/api/v3/ping",
            source="coingecko",
        )
    )

    assert payload == {"ok": True}
    assert call_count["n"] == 2
    assert sources._network_call_counters.get("coingecko") == 2


def test_cached_get_json_memoizes_failed_coingecko_fetch(monkeypatch):
    call_count = {"n": 0}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            call_count["n"] += 1
            raise httpx.RequestError("transport fail", request=httpx.Request("GET", url))

    monkeypatch.setattr(sources_module.httpx, "AsyncClient", _Client)

    sources = ProjectAnalysisSources(
        config={
            "project_analysis": {
                "coingecko_retry_max": 0,
                "coingecko_retry_backoff_ms": 0,
                "error_cache_ttl_sec": 30,
            }
        },
        cache=None,
    )
    loop = asyncio.get_event_loop()
    payload_1 = loop.run_until_complete(
        sources._cached_get_json(
            cache_key="pa:test:cg:memoized-fail",
            url="https://api.coingecko.com/api/v3/ping",
            source="coingecko",
        )
    )
    payload_2 = loop.run_until_complete(
        sources._cached_get_json(
            cache_key="pa:test:cg:memoized-fail",
            url="https://api.coingecko.com/api/v3/ping",
            source="coingecko",
        )
    )

    assert payload_1 is None
    assert payload_2 is None
    assert call_count["n"] == 1
    assert sources._network_call_counters.get("coingecko") == 1


def test_cached_get_json_failed_fetch_not_memoized_when_ttl_zero(monkeypatch):
    call_count = {"n": 0}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            call_count["n"] += 1
            raise httpx.RequestError("transport fail", request=httpx.Request("GET", url))

    monkeypatch.setattr(sources_module.httpx, "AsyncClient", _Client)

    sources = ProjectAnalysisSources(
        config={
            "project_analysis": {
                "coingecko_retry_max": 0,
                "coingecko_retry_backoff_ms": 0,
                "error_cache_ttl_sec": 0,
            }
        },
        cache=None,
    )
    loop = asyncio.get_event_loop()
    payload_1 = loop.run_until_complete(
        sources._cached_get_json(
            cache_key="pa:test:cg:not-memoized-fail",
            url="https://api.coingecko.com/api/v3/ping",
            source="coingecko",
        )
    )
    payload_2 = loop.run_until_complete(
        sources._cached_get_json(
            cache_key="pa:test:cg:not-memoized-fail",
            url="https://api.coingecko.com/api/v3/ping",
            source="coingecko",
        )
    )

    assert payload_1 is None
    assert payload_2 is None
    assert call_count["n"] == 2
    assert sources._network_call_counters.get("coingecko") == 2
