from market_intel_agent.config import PROFILE_REQUIRED_METRICS, PROFILE_SOURCE_REGISTRY, SUPPORTED_PROFILES
from market_intel_agent.sector_resolver import SectorResolver
from market_intel_agent.sector_schema import normalize_alerts_sector_name
from market_intel_agent.sources import _build_alerts_sector_block


def _alerts_payload():
    return {
        "success": True,
        "timestamp": "2026-04-23T00:00:00Z",
        "tokenCount": 176,
        "data": {
            "virtual-protocol": {"id": "virtual-protocol", "symbol": "VIRTUAL", "change_24h": 4.5},
            "blur": {"id": "blur", "symbol": "BLUR", "change_24h": 8.0},
        },
        "sectors": {
            "AI Agents": {
                "mcap": 810_000_000,
                "avg24h": 1.2,
                "avg7d": 5.0,
                "avg30d": 19.0,
                "tokenCount": 10,
                "best": {"symbol": "AIXBT", "value": 2.2},
            },
            "NFT Marketplaces": {
                "mcap": 242_000_000,
                "avg24h": 2.2,
                "avg7d": 2.8,
                "avg30d": 0.4,
                "tokenCount": 7,
                "best": {"symbol": "BLUR", "value": 10.6},
            },
        },
        "sectorTokens": {
            "AI Agents": ["virtual-protocol", "ai16z", "giza"],
            "NFT Marketplaces": ["blur", "looks-rare", "x2y2"],
        },
    }


def test_alerts_sector_names_normalize_to_market_intel_profiles():
    assert normalize_alerts_sector_name("Layer 1") == "l1_l2"
    assert normalize_alerts_sector_name("DEX Aggregators") == "dex_aggregators"
    assert normalize_alerts_sector_name("NFT Marketplaces") == "nft_marketplaces"
    assert normalize_alerts_sector_name("AI Agents") == "ai"


def test_new_alerts_only_profiles_are_supported_and_have_alerts_source():
    for profile in ("dex_aggregators", "asset_management", "nft_marketplaces", "gaming", "social", "prediction_markets", "memes"):
        assert profile in SUPPORTED_PROFILES
        assert "alerts_sector" in PROFILE_SOURCE_REGISTRY[profile]
        assert PROFILE_REQUIRED_METRICS[profile] == [
            "sector_mcap",
            "sector_avg_24h",
            "sector_avg_7d",
            "sector_avg_30d",
            "sector_token_count",
        ]


def test_alerts_sector_block_provides_generic_metrics_and_alpha():
    block = _build_alerts_sector_block(_alerts_payload(), {"coingecko_id": "virtual-protocol", "ticker": "VIRTUAL"})

    assert block is not None
    assert block["sector"] == "ai"
    assert block["source_sector"] == "AI Agents"
    assert block["sector_metrics"]["must"]["sector_mcap"] == 810_000_000.0
    assert block["sector_metrics"]["must"]["sector_avg_24h"] == 1.2
    assert block["sector_metrics"]["must"]["sector_target_alpha_24h"] == 3.3
    assert "virtual-protocol" in block["peers"]


def test_sector_resolver_prefers_alerts_sector_membership_over_heuristics():
    resolver = SectorResolver()
    resolution = resolver.resolve(
        target={"coingecko_id": "blur", "name": "Blur", "category": ""},
        market_status={},
        coingecko_payload={"categories": ["NFT"]},
        alerts_payload=_alerts_payload(),
    )

    assert resolution["sector"] == "nft_marketplaces"
    assert "alerts_sector" in resolution["resolution_source"]
