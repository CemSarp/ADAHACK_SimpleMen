"""WS2 financial accounting (docs/ACTION_MODEL.md §4) with hand-calculated expectations.

Capex is cash charged once in month 1; straight-line depreciation hits operating profit
until the asset life ends; incremental opex and savings are monthly operating flows; the
budget is gross outlay (capex + incremental opex) and never nets savings.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.actions import config_from_vector, simulate_strategy
from src.contracts import ACTION_NAMES, ActionConfig
from src.contracts import serialization as ser
from tests.support import assumptions_with_cost, load_fixture, make_baseline


def only(**actions: float) -> ActionConfig:
    values = dict.fromkeys(ACTION_NAMES, 0.0)
    values.update(actions)
    return ActionConfig(**values)


def close(value: float, rel: float = 1e-12, abs_: float = 1e-9):
    return pytest.approx(value, rel=rel, abs=abs_)


# Golden nonzero config (examples/action_config.json), derived by hand:
CAPEX = 70_000 + 60_000 + 16_000 + 3_000 + 5_000 + 10_000  # capex_at_full * x per action = 164,000
DEPRECIATION = 70_000 / 120 + 60_000 / 84 + 16_000 / 120 + 3_000 / 36 + 5_000 / 36 + 10_000 / 120  # 1,736.5079...
OPEX = 164.0 + 4_000 * 0.15 + 99_800 * 0.56 * 0.02  # fixed + EV kWh + renewable premium = 1,881.76
SAVINGS = 4_200 * 0.15 + 3_000 * 0.05 + 20_000 * 0.12 + 20_000 * 0.3 * 0.2 + 10_000 * 0.1 * 0.05 + 1_000 * 0.1  # 4,530
PROFIT = 100_000 + SAVINGS - OPEX - DEPRECIATION  # 100,911.732...


def test_golden_nonzero_monthly_accounting(baseline, assumptions, example_config):
    assert CAPEX == 164_000 and SAVINGS == close(4_530.0) and OPEX == close(1_881.76)
    result = simulate_strategy(baseline, example_config, assumptions=assumptions)
    frame = result.monthly
    assert frame["capex_gbp"].tolist() == [close(CAPEX)] + [0.0] * 11
    assert frame["depreciation_gbp"].to_numpy() == pytest.approx([DEPRECIATION] * 12, rel=1e-12)
    assert frame["incremental_opex_gbp"].to_numpy() == pytest.approx([OPEX] * 12, rel=1e-12)
    assert frame["operating_savings_gbp"].to_numpy() == pytest.approx([SAVINGS] * 12, rel=1e-12)
    assert frame["operating_profit_gbp"].to_numpy() == pytest.approx([PROFIT] * 12, rel=1e-12)
    assert frame["budget_cost_gbp"].iloc[0] == close(CAPEX + OPEX)  # 165,881.76
    assert frame["budget_cost_gbp"].iloc[1] == close(OPEX)
    assert frame["net_cash_impact_gbp"].iloc[0] == close(SAVINGS - OPEX - CAPEX)  # -161,351.76
    assert frame["net_cash_impact_gbp"].iloc[5] == close(SAVINGS - OPEX)  # 2,648.24
    assert frame["revenue_gbp"].tolist() == [1_000_000.0] * 12


def test_golden_nonzero_horizon_totals(baseline, assumptions, example_config):
    metrics = simulate_strategy(baseline, example_config, assumptions=assumptions).metrics
    # Delivered golden totals (TESTING_AND_MOCKS.md §4).
    assert metrics["total_co2e_tco2e"] == close(843.744)
    assert metrics["total_profit_gbp"] == close(1_210_940.7847619047)
    assert metrics["total_capex_gbp"] == close(164_000.0)
    assert metrics["total_cost_gbp"] == close(186_581.12)
    assert metrics["total_incremental_opex_gbp"] == close(12 * 1_881.76)
    assert metrics["total_operating_savings_gbp"] == close(54_360.0)
    assert metrics["net_cash_impact_gbp"] == close(54_360.0 - 22_581.12 - 164_000.0)
    assert metrics["co2_reduction_tco2e"] == close(356.256)
    assert metrics["co2_reduction_ratio"] == close(0.29688)
    assert metrics["profit_change_gbp"] == close(12 * (SAVINGS - OPEX - DEPRECIATION))
    assert metrics["profit_change_ratio"] == close(12 * (SAVINGS - OPEX - DEPRECIATION) / 1_200_000)


def test_matches_delivered_nonzero_fixture(baseline, assumptions, example_config):
    golden = ser.simulation_from_dict(load_fixture("simulation_nonzero.json"))
    result = simulate_strategy(baseline, example_config, assumptions=assumptions)
    assert result.strategy_id == golden.strategy_id
    for column in golden.monthly.columns:
        if column != "timestamp":
            assert result.monthly[column].to_numpy() == pytest.approx(golden.monthly[column].to_numpy(), rel=1e-12, abs=1e-9)
    for name in ("total_co2e_tco2e", "total_profit_gbp", "total_cost_gbp", "net_cash_impact_gbp", "co2_reduction_ratio"):
        assert result.metrics[name] == close(golden.metrics[name])


def test_capex_is_charged_once_even_over_long_horizons(assumptions, example_config):
    result = simulate_strategy(make_baseline(months=60), example_config, assumptions=assumptions)
    capex = result.monthly["capex_gbp"].to_numpy()
    assert capex[0] == close(CAPEX) and (capex[1:] == 0.0).all()
    assert result.metrics["total_capex_gbp"] == close(CAPEX)


def test_depreciation_stops_at_the_asset_life_boundary(baseline, assumptions):
    short_life = assumptions_with_cost(assumptions, "travel_reduction", asset_life_months=6)
    frame = simulate_strategy(baseline, only(travel_reduction=1.0), assumptions=short_life).monthly
    depreciation = frame["depreciation_gbp"].to_numpy()
    assert depreciation[:6] == pytest.approx([10_000 / 6] * 6, rel=1e-12)
    assert (depreciation[6:] == 0.0).all()
    assert math.fsum(depreciation) == close(10_000.0)
    # After the cut-off, profit = baseline + savings - opex: 100,000 + 4,000 - 10.
    assert frame["operating_profit_gbp"].iloc[8] == close(103_990.0)


def test_depreciation_cutoff_on_a_60_month_horizon(assumptions, example_config):
    frame = simulate_strategy(make_baseline(months=60), example_config, assumptions=assumptions).monthly
    depreciation = frame["depreciation_gbp"].to_numpy()
    assert depreciation[:36] == pytest.approx([DEPRECIATION] * 36, rel=1e-12)
    # Travel (3,000/36) and cloud (5,000/36) assets end after month 36.
    assert depreciation[36:] == pytest.approx([70_000 / 120 + 60_000 / 84 + 16_000 / 120 + 10_000 / 120] * 24, rel=1e-12)
    # No asset is depreciated beyond its capex.
    assert math.fsum(depreciation) <= CAPEX


def test_profit_and_cash_are_distinct(baseline, assumptions, example_config):
    metrics = simulate_strategy(baseline, example_config, assumptions=assumptions).metrics
    total_depreciation = 12 * DEPRECIATION
    # Profit carries depreciation, not capex; cash carries capex, not depreciation.
    assert metrics["profit_change_gbp"] == close(metrics["total_operating_savings_gbp"] - metrics["total_incremental_opex_gbp"] - total_depreciation)
    assert metrics["net_cash_impact_gbp"] == close(metrics["total_operating_savings_gbp"] - metrics["total_incremental_opex_gbp"] - CAPEX)
    assert metrics["profit_change_gbp"] - metrics["net_cash_impact_gbp"] == close(CAPEX - total_depreciation)


def test_budget_is_gross_outlay_and_never_nets_savings(baseline, assumptions):
    # EV only at x=1: capex 150,000; opex 150 + 10,000 kWh * 0.15 = 1,650/month; fuel savings 50,000 km * 0.12 = 6,000/month.
    metrics = simulate_strategy(baseline, only(ev_adoption=1.0), assumptions=assumptions).metrics
    assert metrics["total_operating_savings_gbp"] == close(72_000.0)
    assert metrics["total_cost_gbp"] == close(150_000.0 + 12 * 1_650.0)  # 169,800, savings excluded
    assert metrics["net_cash_impact_gbp"] == close(72_000.0 - 19_800.0 - 150_000.0)


def test_operating_profit_can_be_negative(assumptions):
    baseline = make_baseline(operating_profit_gbp=1_000.0)
    # Renewable x=1: opex 100 + 100,000 kWh * 0.8 * 0.02 = 1,700; depreciation 100,000/120.
    result = simulate_strategy(baseline, only(renewable_energy=1.0), assumptions=assumptions)
    monthly_profit = 1_000.0 - 1_700.0 - 100_000 / 120
    assert result.monthly["operating_profit_gbp"].to_numpy() == pytest.approx([monthly_profit] * 12, rel=1e-12)
    assert result.metrics["total_profit_gbp"] == close(12 * monthly_profit)
    assert result.metrics["profit_change_ratio"] == close((12 * monthly_profit - 12_000.0) / 12_000.0)


def test_loss_making_and_zero_profit_baselines(assumptions, example_config):
    loss = simulate_strategy(make_baseline(operating_profit_gbp=-20_000.0), example_config, assumptions=assumptions).metrics
    assert loss["baseline_total_profit_gbp"] == -240_000.0
    assert loss["profit_change_ratio"] == close(loss["profit_change_gbp"] / 240_000.0)  # divides by |baseline|
    zero = simulate_strategy(make_baseline(operating_profit_gbp=0.0), example_config, assumptions=assumptions).metrics
    assert zero["baseline_total_profit_gbp"] == 0.0 and zero["profit_change_ratio"] is None


def test_horizon_metrics_reconcile_with_monthly_columns(assumptions):
    rng = np.random.default_rng(5)
    for months in (12, 36, 60):
        baseline = make_baseline(months=months)
        for _ in range(15):
            result = simulate_strategy(baseline, config_from_vector(rng.random(6)), assumptions=assumptions)
            frame, m = result.monthly, result.metrics
            assert m["total_cost_gbp"] == pytest.approx(m["total_capex_gbp"] + m["total_incremental_opex_gbp"], abs=0.01)
            assert m["net_cash_impact_gbp"] == pytest.approx(
                m["total_operating_savings_gbp"] - m["total_incremental_opex_gbp"] - m["total_capex_gbp"], abs=0.01
            )
            assert m["total_profit_gbp"] == pytest.approx(
                m["baseline_total_profit_gbp"]
                + m["total_operating_savings_gbp"]
                - m["total_incremental_opex_gbp"]
                - math.fsum(frame["depreciation_gbp"]),
                abs=0.01,
            )
            assert m["total_co2e_tco2e"] == pytest.approx(math.fsum(frame["total_co2e_tco2e"]), rel=1e-12)
            assert (frame["capex_gbp"].to_numpy()[1:] == 0.0).all()
