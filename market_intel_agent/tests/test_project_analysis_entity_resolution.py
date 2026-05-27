import asyncio

from market_intel_agent.project_analysis.entity_resolution import EntityResolver


class _FakeSources:
    async def search_coingecko(self, query: str):
        return {"id": "aave", "symbol": "aave", "name": "Aave"}

    async def resolve_defillama_protocol(self, *, asset_input, candidate_slug, coingecko_id, token_symbol):
        return {"slug": "aave", "name": "Aave", "category": "Lending"}


def test_entity_resolution_prefers_protocol_slug_when_available():
    resolver = EntityResolver(sources=_FakeSources(), cache=None, queries=None)
    loop = asyncio.get_event_loop()
    entity = loop.run_until_complete(resolver.resolve("AAVE"))

    assert entity.name == "Aave"
    assert entity.coingecko_id == "aave"
    assert entity.defillama_slug == "aave"
    assert entity.entity_type == "protocol"
