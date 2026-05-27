from market_intel_agent.project_analysis.calculators import LocalMetricsCalculator
from market_intel_agent.project_analysis.models import AnalysisState


def test_local_ratio_computation():
    state = AnalysisState.initialize(asset_input="AAVE", skills=[])
    state.universal.market_cap = 1_000.0
    state.universal.fdv = 2_000.0
    state.universal.circulating_supply = 100.0
    state.universal.max_supply = 200.0
    state.universal.token_unlocks_12m = 10.0
    state.universal.annualized_protocol_revenue = 100.0
    state.universal.annualized_tokenholder_revenue = 50.0
    state.sector_metrics.borrowed_tvl = 300.0
    state.sector_metrics.supplied_tvl = 600.0
    state.sector_metrics.volume = 900.0
    state.sector_metrics.tvl = 300.0
    state.sector_metrics.open_interest = 450.0

    calculator = LocalMetricsCalculator()
    computed_count = calculator.apply(state)

    assert computed_count > 0
    assert state.computed.fdv_mc_ratio == 2.0
    assert state.computed.circulating_ratio == 0.5
    assert state.computed.unlocks_12m_pct_of_circulating == 0.1
    assert state.computed.mc_to_revenue == 10.0
    assert state.computed.revenue_yield == 0.1
    assert state.computed.lending_utilization == 0.5
    assert state.computed.dex_volume_tvl == 3.0
    assert state.computed.perp_volume_oi == 2.0
