import asyncio

from market_intel_agent.project_analysis.models import ResolvedEntity
from market_intel_agent.project_analysis.sector_routing import SectorRouter


def test_sector_routing_prefers_metadata_category():
    router = SectorRouter(cache=None)
    entity = ResolvedEntity(
        name="Aave",
        slug="aave",
        metadata={"db_category": "Lending"},
    )
    loop = asyncio.get_event_loop()
    sector, reason = loop.run_until_complete(router.resolve(entity, coingecko_categories=["DeFi"]))
    assert sector == "lending"
    assert reason.startswith("metadata:")


def test_sector_routing_keyword_fallback():
    router = SectorRouter(cache=None)
    entity = ResolvedEntity(name="Hyperliquid", slug="hyperliquid-perp")
    loop = asyncio.get_event_loop()
    sector, reason = loop.run_until_complete(router.resolve(entity, coingecko_categories=[]))
    assert sector == "perp_dex"
    assert reason == "keyword_fallback"
