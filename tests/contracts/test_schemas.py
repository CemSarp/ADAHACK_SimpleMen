"""Contract 1.0.0: fixture validation, JSON round-trips and rejection cases."""

from __future__ import annotations

import json
import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.contracts import serialization as ser
from src.contracts import validation as val
from src.contracts.errors import ContractValidationError, UnsupportedHorizon
from src.contracts.identity import compute_strategy_id
from src.contracts.types import (
    ACTION_NAMES,
    ActionConfig,
    BacktestReport,
    BaselineBundle,
    BenchmarkResult,
    ConstraintConfig,
    ExplanationResult,
    OptimizationResult,
    RiskResult,
    SimulationResult,
)
from tests.mocks import fixtures

ROUND_TRIP_CASES = [
    ("baseline_12m.json", BaselineBundle),
    ("simulation_noop.json", SimulationResult),
    ("simulation_nonzero.json", SimulationResult),
    ("optimization_ok.json", OptimizationResult),
    ("optimization_infeasible.json", OptimizationResult),
    ("risk_summary.json", RiskResult),
    ("benchmark_result.json", BenchmarkResult),
    ("backtest_report.json", BacktestReport),
    ("shap_explanation.json", ExplanationResult),
]


@pytest.mark.parametrize("name,cls", ROUND_TRIP_CASES)
def test_fixture_json_round_trip_is_lossless(name, cls):
    raw = fixtures.load_json(name)
    obj = ser.from_dict(cls, raw)
    again = ser.from_json(cls, ser.to_json(obj))
    assert ser.to_dict(again) == ser.to_dict(obj)
    # Documented fields survive unchanged (fixture_note is a fixture-only annotation).
    original = {k: v for k, v in raw.items() if k != "fixture_note"}
    assert ser.to_dict(obj) == original


def test_all_fixtures_validate():
    baseline = fixtures.baseline()
    for name in ("noop", "nonzero"):
        val.validate_simulation_result(fixtures.simulation(name), baseline)
    for name in ("ok", "infeasible"):
        val.validate_optimization_result(fixtures.optimization(name))
    val.validate_assumptions(fixtures.assumptions())
    val.validate_constraints(fixtures.constraints())
    val.validate_risk_result(fixtures.risk())
    val.validate_benchmark_result(fixtures.benchmark())
    val.validate_backtest_report(fixtures.backtest())
    val.validate_explanation(fixtures.explanation())
    val.validate_history_frame(fixtures.history())


def test_baseline_round_trip_preserves_dates_dtypes_and_totals():
    baseline = fixtures.baseline()
    again = ser.from_json(BaselineBundle, ser.to_json(baseline))
    pd.testing.assert_frame_equal(again.monthly, baseline.monthly)
    assert str(again.monthly["timestamp"].dtype) == "datetime64[ns]"
    assert again.monthly["employees"].dtype == np.int64
    assert again.totals == baseline.totals == {"revenue_gbp": 12e6, "operating_profit_gbp": 1.2e6, "total_co2e_tco2e": 1200.0}
    assert len(again.monthly) == 12 and again.monthly["timestamp"].iloc[0] == pd.Timestamp("2027-01-01")


def test_strategy_ids_reproduce_fixture_identity_at_full_precision():
    a = fixtures.assumptions()
    assert compute_strategy_id("baseline-demo-v1", fixtures.action_config(), a.assumptions_id, a.version) == "strategy-8be15857fffc57f6"
    assert compute_strategy_id("baseline-demo-v1", ActionConfig.noop(), a.assumptions_id, a.version) == "strategy-84d0730a93b9d729"
    nudged = replace(fixtures.action_config(), renewable_energy=0.7 + 1e-12)
    assert compute_strategy_id("baseline-demo-v1", nudged, a.assumptions_id, a.version) != "strategy-8be15857fffc57f6"


def test_full_precision_config_survives_round_trip():
    sim = fixtures.simulation("nonzero")
    precise = replace(sim, config=replace(sim.config, cloud_efficiency=0.123456789012345678))
    again = ser.from_json(SimulationResult, ser.to_json(precise))
    assert again.config.cloud_efficiency == 0.123456789012345678


def test_empty_frames_keep_columns_and_dtypes():
    opt = ser.from_json(OptimizationResult, ser.to_json(fixtures.optimization("infeasible")))
    assert len(opt.pareto) == 0
    assert list(opt.pareto.columns)[:7] == ["strategy_id", *ACTION_NAMES]
    assert opt.pareto["feasible"].dtype == bool and opt.pareto["pareto_rank"].dtype == np.int64


# --------------------------------------------------------------------------- #
# Rejections
# --------------------------------------------------------------------------- #


def _history() -> pd.DataFrame:
    return fixtures.history().copy()


@pytest.mark.parametrize(
    "mutate,field",
    [
        (lambda h: pd.concat([h, h.tail(1)], ignore_index=True), "history.timestamp"),
        (lambda h: h.drop(index=5).reset_index(drop=True), "history.timestamp"),
        (lambda h: h.assign(company_id=["a"] * (len(h) - 1) + ["b"]), "history.company_id"),
        (lambda h: h.assign(gas_kwh=h["gas_kwh"].where(h.index != 3, np.nan)), "history.gas_kwh"),
        (lambda h: h.assign(revenue_gbp=h["revenue_gbp"].where(h.index != 3, np.inf)), "history.revenue_gbp"),
        (lambda h: h.assign(scope1_tco2e=h["scope1_tco2e"] + 1.0), "history.total_co2e_tco2e"),
        (lambda h: h.assign(renewable_energy_share=h["renewable_energy_share"] * 100), "history.renewable_energy_share"),
        (lambda h: h.assign(timestamp=h["timestamp"] + pd.Timedelta(days=3)), "history.timestamp"),
        (lambda h: h.drop(columns=["cloud_compute_hours"]), "history"),
    ],
    ids=["duplicate-month", "missing-month", "two-companies", "nan", "inf", "scope-mismatch", "percent-0-100",
         "not-month-start", "missing-column"],
)
def test_history_rejections(mutate, field):
    with pytest.raises(ContractValidationError) as exc:
        val.validate_history_frame(mutate(_history()))
    assert exc.value.field == field


def test_baseline_rejects_row_count_and_totals_mismatch():
    b = fixtures.baseline()
    with pytest.raises(ContractValidationError, match="exactly 12 rows"):
        val.validate_baseline(replace(b, monthly=b.monthly.head(11)))
    with pytest.raises(ContractValidationError, match="sum of monthly"):
        val.validate_baseline(replace(b, totals={**b.totals, "total_co2e_tco2e": 1201.0}))
    with pytest.raises(ContractValidationError, match="history_end"):
        val.validate_baseline(replace(b, history_end=b.history_end.replace(month=11)))


@pytest.mark.parametrize("value", [-0.01, 1.01, 70.0, float("nan"), True])
def test_action_config_rejects_out_of_range_and_percentages(value):
    with pytest.raises(ContractValidationError) as exc:
        val.validate_action_config(replace(ActionConfig.noop(), ev_adoption=value))
    assert exc.value.field == "config.ev_adoption"


def test_constraints_rejections():
    with pytest.raises(ContractValidationError, match="budget_gbp"):
        val.validate_constraints(ConstraintConfig(-1.0, 0.0, 0.1))
    with pytest.raises(ContractValidationError, match="0-100 percentages"):
        val.validate_constraints(ConstraintConfig(1.0, 0.0, 20.0))
    val.validate_constraints(ConstraintConfig(0.0, -5e5, 0.0))  # negative profit floor is allowed


def test_zero_baseline_co2_with_positive_target_is_invalid():
    b = fixtures.baseline()
    zero = b.monthly.assign(scope1_tco2e=0.0, scope2_tco2e=0.0, scope3_tco2e=0.0, total_co2e_tco2e=0.0)
    zb = replace(b, monthly=zero, totals={**b.totals, "total_co2e_tco2e": 0.0})
    val.validate_baseline(zb)
    with pytest.raises(ContractValidationError, match="undefined"):
        val.validate_constraints_for_baseline(ConstraintConfig(1.0, 0.0, 0.1), zb)
    val.validate_constraints_for_baseline(ConstraintConfig(1.0, 0.0, 0.0), zb)


def test_unsupported_horizon_and_schema_major():
    with pytest.raises(UnsupportedHorizon):
        val.validate_horizon(36, supported=(12,))
    with pytest.raises(ContractValidationError):
        val.validate_horizon(24)
    raw = fixtures.load_json("baseline_12m.json")
    raw["schema_version"] = "2.0.0"
    with pytest.raises(ContractValidationError, match="unsupported major"):
        ser.baseline_from_dict(raw)
    raw["schema_version"] = "1.1.0"  # additive minor versions are accepted
    ser.baseline_from_dict(raw)


def test_json_rejects_nan_infinity_and_malformed_text():
    sim = fixtures.simulation("nonzero")
    bad = replace(sim, metrics={**sim.metrics, "total_cost_gbp": float("inf")})
    with pytest.raises(ContractValidationError):
        ser.to_json(bad)
    with pytest.raises(ContractValidationError, match="not permitted"):
        ser.from_json(SimulationResult, ser.to_json(sim).replace('"total_cost_gbp": 186581.1200000001', '"total_cost_gbp": NaN'))
    with pytest.raises(ContractValidationError, match="malformed"):
        ser.from_json(SimulationResult, "{not json")


def test_missing_required_field_fails_early():
    raw = fixtures.load_json("simulation_nonzero.json")
    del raw["strategy_id"]
    with pytest.raises(ContractValidationError, match="strategy_id"):
        ser.simulation_from_dict(raw)
    raw = fixtures.load_json("action_config.json")
    raw["solar_panels"] = 0.1
    with pytest.raises(ContractValidationError, match="unknown action"):
        ser.action_config_from_dict(raw)


def test_optimization_invariants_rejected():
    ok = fixtures.optimization("ok")
    with pytest.raises(ContractValidationError, match="at least one feasible"):
        val.validate_optimization_result(replace(ok, pareto=ok.pareto.iloc[0:0]))
    with pytest.raises(ContractValidationError, match="must be feasible"):
        val.validate_optimization_result(replace(ok, pareto=ok.pareto.assign(feasible=False)))
    altered = ok.pareto.assign(renewable_energy=0.70000001)
    with pytest.raises(ContractValidationError, match="exact config"):
        val.validate_optimization_result(replace(ok, pareto=altered))
    infeasible = fixtures.optimization("infeasible")
    with pytest.raises(ContractValidationError, match="empty Pareto"):
        val.validate_optimization_result(replace(infeasible, pareto=ok.pareto))


def test_simulation_metrics_must_match_monthly_sums():
    sim = fixtures.simulation("nonzero")
    with pytest.raises(ContractValidationError, match="horizon sum"):
        val.validate_simulation_result(replace(sim, metrics={**sim.metrics, "total_cost_gbp": 1.0}))


def test_benchmark_and_risk_semantics():
    b = fixtures.benchmark()
    with pytest.raises(ContractValidationError, match="100 - percentile"):
        val.validate_benchmark_result(replace(b, better_than_pct=50.0))
    unavailable = replace(b, status="unavailable", reason="too few compatible peers", percentile=None)
    val.validate_benchmark_result(unavailable)
    r = fixtures.risk()
    with pytest.raises(ContractValidationError, match="probability"):
        val.validate_risk_result(replace(r, summary={**r.summary, "target_probability": 1.2}))
    with pytest.raises(ContractValidationError, match="co2_p05"):
        val.validate_risk_result(replace(r, summary={**r.summary, "co2_p05_tco2e": 999.0}))


def test_fixture_numbers_match_documented_golden_totals():
    m = fixtures.simulation("nonzero").metrics
    assert math.isclose(m["total_co2e_tco2e"], 843.744, abs_tol=1e-6)
    assert math.isclose(m["total_profit_gbp"], 1210940.7847619047, abs_tol=0.01)
    assert m["total_capex_gbp"] == 164000.0
    assert math.isclose(m["total_cost_gbp"], 186581.12, abs_tol=0.01)
    assert json.loads(ser.to_json(fixtures.simulation("noop")))["metrics"]["total_cost_gbp"] == 0.0
