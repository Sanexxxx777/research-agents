from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT_PATH = Path("/root/research-agents/market_intel_agent/scripts/execute_first_pass_skill.py")
_SPEC = importlib.util.spec_from_file_location("execute_first_pass_skill", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


def test_parse_parent_slug():
    assert _MOD._parse_parent_slug("parent#aave") == "aave"
    assert _MOD._parse_parent_slug("aave-v3") == "aave-v3"
    assert _MOD._parse_parent_slug("") == ""


def test_related_slug_candidates_include_parent_and_gecko_matches(tmp_path: Path):
    cache = _MOD._FileCache(cache_dir=tmp_path, cache_key="x", ttl_sec=60)
    bridge = _MOD.DefiLlamaSkillBridge(run_py="", uv_bin="uv", base_url="https://api.llama.fi", cache=cache)

    def _fake_protocols():
        return [
            {"slug": "aave", "tvl": 100.0, "gecko_id": "aave", "symbol": "AAVE", "name": "Aave"},
            {"slug": "aave-v3", "tvl": 300.0, "parentProtocol": "parent#aave", "gecko_id": "aave", "symbol": "AAVE", "name": "Aave V3"},
            {"slug": "aave-arc", "tvl": 50.0, "parentProtocol": "parent#aave", "gecko_id": "aave", "symbol": "AAVE", "name": "Aave Arc"},
        ]

    bridge.protocols_list = _fake_protocols  # type: ignore[method-assign]

    protocol = {"parentProtocol": "parent#aave"}
    slugs = bridge.related_slug_candidates(
        primary_slug="aave-v3",
        protocol=protocol,
        coingecko_id="aave",
        symbol="AAVE",
        asset="Aave",
        max_candidates=6,
    )

    assert slugs[0] == "aave-v3"
    assert "aave" in slugs
    assert "aave-arc" in slugs


def test_resolve_protocol_falls_back_to_protocols_list(tmp_path: Path):
    cache = _MOD._FileCache(cache_dir=tmp_path, cache_key="y", ttl_sec=60)
    bridge = _MOD.DefiLlamaSkillBridge(run_py="", uv_bin="uv", base_url="https://api.llama.fi", cache=cache)

    def _fake_protocol(slug: str):
        if slug == "aave-v3":
            return {"slug": "aave-v3", "name": "Aave V3"}
        return None

    def _fake_protocols():
        return [
            {"slug": "aave-v3", "tvl": 300.0, "gecko_id": "aave", "symbol": "AAVE", "name": "Aave V3"},
            {"slug": "aave", "tvl": 100.0, "gecko_id": "aave", "symbol": "AAVE", "name": "Aave"},
        ]

    bridge.protocol = _fake_protocol  # type: ignore[method-assign]
    bridge.protocols_list = _fake_protocols  # type: ignore[method-assign]

    payload, slug, attempts = bridge.resolve_protocol(
        explicit_slug="",
        coingecko_id="aave",
        symbol="AAVE",
        asset="Aave",
    )
    assert payload is not None
    assert slug == "aave-v3"
    assert "aave-v3" in attempts


def test_build_market_analysis_perp_emits_unavailable_reasons():
    payload, audit = _MOD._build_market_analysis(
        sector="perp_dex",
        protocol={"tvl": [{"date": 1, "totalLiquidityUSD": 1000.0}]},
        dex_summary=None,
        dex_attempts=None,
        perps_summary=None,
        perps_attempts=["dydx-v4", "dydx"],
    )
    assert payload.get("market_depth_or_liquidity") == 1000.0
    assert any(item.get("metric") == "volume" and "attempted_slugs" in str(item.get("reason") or "") for item in audit)
    assert any(item.get("metric") == "open_interest" for item in audit)
    assert any(item.get("metric") == "markets_count" for item in audit)
    assert any(item.get("metric") == "main_demand_kpi" for item in audit)
    assert any(item.get("metric") == "retention" for item in audit)
