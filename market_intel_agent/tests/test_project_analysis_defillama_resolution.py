import asyncio

import httpx

from market_intel_agent.project_analysis.sources import ProjectAnalysisSources


class _FakeSources(ProjectAnalysisSources):
    def __init__(self):
        super().__init__(config={"project_analysis": {}}, cache=None)

    async def _fetch_protocol(self, slug: str):
        if slug == "aave":
            return {"name": "Aave", "slug": "aave", "category": None, "tvl": []}
        if slug == "aave-v3":
            return {"name": "Aave V3", "slug": "aave-v3", "category": "Lending", "tvl": []}
        return None

    async def _fetch_protocols_list(self):
        return [
            {"name": "Aave V3", "slug": "aave-v3", "symbol": "AAVE", "gecko_id": None, "tvl": 1_000.0},
        ]


def test_defillama_resolution_prefers_categorized_protocol_over_token_like_match():
    sources = _FakeSources()
    loop = asyncio.get_event_loop()
    payload = loop.run_until_complete(
        sources.resolve_defillama_protocol(
            asset_input="AAVE",
            candidate_slug=None,
            coingecko_id="aave",
            token_symbol="AAVE",
        )
    )
    assert payload is not None
    assert payload.get("slug") == "aave-v3"
    assert payload.get("category") == "Lending"


class _HTTP400Sources(ProjectAnalysisSources):
    def __init__(self):
        super().__init__(config={"project_analysis": {}}, cache=None)

    async def _cached_get_json(self, *, cache_key, url, params=None, source="unknown"):
        req = httpx.Request("GET", url)
        resp = httpx.Response(400, request=req)
        raise httpx.HTTPStatusError("bad request", request=req, response=resp)


def test_fetch_protocol_treats_http_400_as_missing_candidate():
    sources = _HTTP400Sources()
    loop = asyncio.get_event_loop()
    payload = loop.run_until_complete(sources._fetch_protocol("uni"))
    assert payload is None


class _TransportErrorSources(ProjectAnalysisSources):
    def __init__(self):
        super().__init__(config={"project_analysis": {"defillama_retry_max": 0}}, cache=None)

    async def _cached_get_json(self, *, cache_key, url, params=None, source="unknown"):
        req = httpx.Request("GET", url)
        raise httpx.RequestError("transport fail", request=req)


def test_fetch_protocol_treats_transport_error_as_missing_candidate():
    sources = _TransportErrorSources()
    loop = asyncio.get_event_loop()
    payload = loop.run_until_complete(sources._fetch_protocol("uniswap"))
    assert payload is None
