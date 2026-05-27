from market_intel_agent.project_analysis.normalization import normalize_first_pass_output


def test_normalization_handles_dict_payload():
    payload = {
        "annualized_revenue": 100.0,
        "token_unlocks_12m": 25.0,
        "value_capture_type": "revshare",
        "main_demand_kpi": 42.0,
    }
    normalized = normalize_first_pass_output(payload)
    assert normalized["token_unlocks_12m"] == 25.0
    assert normalized["value_capture_type"] == "revshare"
    assert normalized["main_demand_kpi"] == 42.0


def test_normalization_handles_text_payload():
    text = "annualized revenue: 1200\\nopen interest: 44\\nvalue capture: burn"
    normalized = normalize_first_pass_output(text)
    assert normalized["annualized_protocol_revenue"] == 1200.0
    assert normalized["open_interest"] == 44.0
    assert normalized["value_capture_type"] == "burn"


def test_normalization_passthroughs_lending_mix_fields():
    payload = {
        "collateral_mix": [{"asset": "WETH", "pct": 0.5}],
        "borrow_mix": [{"asset": "USDC", "pct": 0.4}],
        "concentration_metric": 0.31,
    }
    normalized = normalize_first_pass_output(payload)
    assert normalized["collateral_mix"][0]["asset"] == "WETH"
    assert normalized["borrow_mix"][0]["asset"] == "USDC"
    assert normalized["concentration_metric"] == 0.31
