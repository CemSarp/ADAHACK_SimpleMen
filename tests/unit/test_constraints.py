"""Shared constraint evaluation and the manual what-if boundary (docs/ACTION_MODEL.md §5)."""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from src.actions import simulate_strategy
from src.contracts import ACTION_NAMES, ActionConfig, ConstraintConfig, ContractValidationError
from src.contracts import serialization as ser
from src.contracts import validation as val
from src.optimization.constraints import (
    SOLVER_FEASIBILITY_TOLERANCE,
    evaluate_constraints,
    evaluate_what_if,
)
from tests.mocks.affine_simulator import affine_simulator
from tests.support import assumptions_with, frames_identical, load_fixture, make_baseline


def only(**actions: float) -> ActionConfig:
    values = dict.fromkeys(ACTION_NAMES, 0.0)
    values.update(actions)
    return ActionConfig(**values)


def with_metrics(result, **fields):
    return dataclasses.replace(result, metrics={**result.metrics, **fields})


@pytest.fixture
def noop(baseline, assumptions):
    return simulate_strategy(baseline, ActionConfig.noop(), assumptions=assumptions)


@pytest.fixture
def nonzero(baseline, assumptions, example_config):
    return simulate_strategy(baseline, example_config, assumptions=assumptions)


def test_fixture_candidate_values_and_signs(noop, nonzero, example_constraints):
    ok = load_fixture("optimization_ok.json")["candidates"]
    for result, row in ((noop, ok[0]), (nonzero, ok[1])):
        evaluation = evaluate_constraints(result, example_constraints)
        for name in ("g_budget", "g_profit", "g_target"):
            assert getattr(evaluation, name) == pytest.approx(row[name], rel=1e-12, abs=1e-15)
        assert evaluation.feasible is row["feasible"]
    # Hand values: g_budget = (186,581.12 - 500,000) / 500,000; g_profit = (1e6 - 1,210,940.78...) / 1.2e6.
    evaluation = evaluate_constraints(nonzero, example_constraints)
    assert evaluation.g_budget == pytest.approx((186_581.12 - 500_000) / 500_000, rel=1e-12)
    assert evaluation.g_profit == pytest.approx((1_000_000 - 1_210_940.7847619047) / 1_200_000, rel=1e-12)
    assert evaluation.g_target == pytest.approx(0.2 - 0.29688, rel=1e-12)
    assert evaluation.raw_violations["budget_gbp"] == 0.0
    noop_eval = evaluate_constraints(noop, example_constraints)
    assert noop_eval.satisfied["budget"] and noop_eval.satisfied["profit"] and not noop_eval.satisfied["target"]
    assert noop_eval.raw_violations["reduction_ratio"] == pytest.approx(0.2)


def test_budget_zero(noop, nonzero):
    constraints = ConstraintConfig(budget_gbp=0.0, min_total_profit_gbp=1_000_000.0, min_co2_reduction_ratio=0.2)
    assert evaluate_constraints(noop, constraints).g_budget == 0.0  # 0 / max(0, 1)
    over = evaluate_constraints(nonzero, constraints)
    assert over.g_budget == pytest.approx(186_581.12, rel=1e-12)  # normalized by 1 GBP when budget is 0
    assert over.raw_violations["budget_gbp"] == pytest.approx(186_581.12, rel=1e-12)
    assert not over.feasible and not over.satisfied["budget"]
    boundary = ConstraintConfig(budget_gbp=0.0, min_total_profit_gbp=1_200_000.0, min_co2_reduction_ratio=0.0)
    assert evaluate_constraints(noop, boundary).feasible  # every constraint exactly at its boundary


def test_negative_profit_floor_is_allowed(nonzero):
    constraints = ConstraintConfig(budget_gbp=500_000.0, min_total_profit_gbp=-5_000_000.0, min_co2_reduction_ratio=0.2)
    evaluation = evaluate_constraints(nonzero, constraints)
    assert evaluation.g_profit == pytest.approx((-5_000_000 - 1_210_940.7847619047) / 5_000_000, rel=1e-12)
    assert evaluation.feasible


def test_zero_target_rejects_emission_increases(baseline, assumptions):
    dirty = simulate_strategy(baseline, only(ev_adoption=1.0), assumptions=assumptions_with(assumptions, grid_tco2e_per_kwh=0.01))
    constraints = ConstraintConfig(budget_gbp=1e9, min_total_profit_gbp=-1e9, min_co2_reduction_ratio=0.0)
    evaluation = evaluate_constraints(dirty, constraints)
    assert evaluation.g_target == pytest.approx(0.72) and not evaluation.satisfied["target"]
    assert evaluation.raw_violations["reduction_ratio"] == pytest.approx(0.72)


def test_impossible_target_is_infeasible_even_at_full_implementation(baseline, assumptions):
    full = simulate_strategy(baseline, ActionConfig(*[1.0] * 6), assumptions=assumptions)
    evaluation = evaluate_constraints(full, ConstraintConfig(1e12, -1e12, 1.0))
    assert full.metrics["co2_reduction_ratio"] < 1.0
    assert evaluation.g_target == pytest.approx(1.0 - full.metrics["co2_reduction_ratio"]) and not evaluation.feasible


def test_zero_baseline_with_positive_target_is_invalid(assumptions):
    baseline = make_baseline(scope1_tco2e=0.0, scope2_tco2e=0.0, scope3_tco2e=0.0)
    result = simulate_strategy(baseline, only(ev_adoption=1.0), assumptions=assumptions)
    with pytest.raises(ContractValidationError) as info:
        evaluate_constraints(result, ConstraintConfig(1e9, -1e9, 0.1))
    assert info.value.field == "constraints.min_co2_reduction_ratio"
    evaluation = evaluate_constraints(result, ConstraintConfig(1e9, -1e9, 0.0))
    assert evaluation.g_target == 0.0 and evaluation.raw_violations["reduction_ratio"] == 0.0 and evaluation.feasible


@pytest.mark.parametrize(
    "budget, cost, satisfied",
    [
        (500_000.0, 500_000.0, True),
        (500_000.0, 500_000.004, True),  # g = 8e-9 <= 1e-8 and raw 0.004 <= 0.01 GBP
        (500_000.0, 500_000.02, False),  # g = 4e-8 > 1e-8
        (1e9, 1e9 + 5.0, False),  # g = 5e-9 passes the solver test, raw 5 GBP fails: no material excess
        (0.0, 5e-9, True),
        (0.0, 0.02, False),
    ],
)
def test_budget_epsilon_boundary(noop, budget, cost, satisfied):
    result = with_metrics(noop, total_cost_gbp=cost)
    evaluation = evaluate_constraints(result, ConstraintConfig(budget, 0.0, 0.0))
    assert evaluation.satisfied["budget"] is satisfied
    assert evaluation.g_budget == pytest.approx((cost - budget) / max(budget, 1.0), rel=1e-12, abs=1e-18)


@pytest.mark.parametrize(
    "profit, satisfied", [(1_000_000.0, True), (1_000_000.0 - 0.005, True), (1_000_000.0 - 0.02, False)]
)
def test_profit_epsilon_boundary(noop, profit, satisfied):
    result = with_metrics(noop, total_profit_gbp=profit)
    evaluation = evaluate_constraints(result, ConstraintConfig(1e9, 1_000_000.0, 0.0))
    assert evaluation.satisfied["profit"] is satisfied
    assert evaluation.g_profit == pytest.approx((1_000_000.0 - profit) / 1_200_000.0, abs=1e-18)


@pytest.mark.parametrize("ratio, satisfied", [(0.2, True), (0.2 - 5e-9, True), (0.2 - 2e-8, False), (0.5, True)])
def test_target_epsilon_boundary(noop, ratio, satisfied):
    result = with_metrics(noop, co2_reduction_ratio=ratio)
    evaluation = evaluate_constraints(result, ConstraintConfig(1e9, -1e9, 0.2))
    assert evaluation.satisfied["target"] is satisfied
    assert evaluation.g_target == pytest.approx(0.2 - ratio, abs=1e-18)
    assert SOLVER_FEASIBILITY_TOLERANCE == 1e-8


def test_profit_normalization_uses_largest_scale(noop):
    tiny = ConstraintConfig(budget_gbp=0.0, min_total_profit_gbp=0.5, min_co2_reduction_ratio=0.0)
    zero_profit = with_metrics(noop, total_profit_gbp=0.0, baseline_total_profit_gbp=0.0, profit_change_gbp=0.0, profit_change_ratio=None)
    assert evaluate_constraints(zero_profit, tiny).g_profit == 0.5  # max(|0.5|, |0|, 1) = 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"budget_gbp": -1.0, "min_total_profit_gbp": 0.0, "min_co2_reduction_ratio": 0.0},
        {"budget_gbp": 1.0, "min_total_profit_gbp": math.nan, "min_co2_reduction_ratio": 0.0},
        {"budget_gbp": 1.0, "min_total_profit_gbp": 0.0, "min_co2_reduction_ratio": 1.5},
        {"budget_gbp": 1.0, "min_total_profit_gbp": 0.0, "min_co2_reduction_ratio": 20},
        {"budget_gbp": 1.0, "min_total_profit_gbp": 0.0, "min_co2_reduction_ratio": -0.1},
        {"budget_gbp": True, "min_total_profit_gbp": 0.0, "min_co2_reduction_ratio": 0.0},
    ],
)
def test_invalid_constraint_configs_are_rejected(kwargs):
    with pytest.raises(ContractValidationError):
        val.validate_constraints(ConstraintConfig(**kwargs))
    with pytest.raises(ContractValidationError):  # and the evaluator never computes with them
        evaluate_constraints(None, ConstraintConfig(**kwargs))  # type: ignore[arg-type]


def test_constraint_file_parses_to_horizon_totals():
    assert ser.constraints_from_dict(load_fixture("constraints.json")) == ConstraintConfig(500_000.0, 1_000_000.0, 0.2)
    with pytest.raises(ContractValidationError, match="required"):
        ser.constraints_from_dict({"budget_gbp": 1.0, "min_total_profit_gbp": 0.0})


def test_wrong_types_are_rejected(nonzero, example_constraints):
    with pytest.raises(ContractValidationError):
        evaluate_constraints({"metrics": {}}, example_constraints)  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError):
        evaluate_constraints(nonzero, {"budget_gbp": 1})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Manual what-if boundary
# ---------------------------------------------------------------------------


def test_what_if_equals_direct_simulation_and_constraint_call(baseline, assumptions, example_config, example_constraints):
    what_if = evaluate_what_if(baseline, example_config, assumptions=assumptions, constraints=example_constraints)
    direct = simulate_strategy(baseline, example_config, assumptions=assumptions)
    assert what_if.simulation.strategy_id == direct.strategy_id
    assert what_if.simulation.metrics == direct.metrics
    assert frames_identical(what_if.simulation.monthly, direct.monthly)
    assert what_if.constraints == evaluate_constraints(direct, example_constraints)


def test_what_if_from_a_ui_json_payload_is_identical(baseline, assumptions, example_config):
    payload = json.loads(json.dumps({"config": example_config.as_dict()}))
    from_ui = evaluate_what_if(baseline, ser.action_config_from_dict(payload["config"]), assumptions=assumptions)
    direct = simulate_strategy(baseline, example_config, assumptions=assumptions)
    assert from_ui.constraints is None
    assert from_ui.simulation.strategy_id == direct.strategy_id and from_ui.simulation.metrics == direct.metrics


def test_what_if_uses_the_injected_simulator(baseline, assumptions, example_config):
    what_if = evaluate_what_if(baseline, example_config, assumptions=assumptions, simulator=affine_simulator)
    assert what_if.simulation.provenance.provider == "affine-test-double"
