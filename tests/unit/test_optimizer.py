"""Constrained NSGA-II: adapter signs, toy problem, budget, infeasibility, failures, audit parity.

Stochastic-search tests assert reproducibility and valid feasible output, plus loose bounds
derived from the toy problem's analytical frontier; they never assert a global optimum.
"""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

import src.optimization.optimizer as optimizer_module
from src.actions import simulate_strategy
from src.contracts.identity import strategy_id_from_identity
from src.contracts import (
    ACTION_NAMES,
    ActionConfig,
    ConstraintConfig,
    ContractValidationError,
    OptimizationError,
    OptimizerConfig,
)
from src.contracts import serialization as ser
from src.contracts import validation as val
from src.contracts.types import OPTIMIZATION_TABLE_COLUMNS
from src.optimization import evaluate_constraints, optimize_strategies
from src.optimization.optimizer import default_seed_configs, objective_vector, solver_constraint_vector
from src.optimization.pareto import dominance_tolerances, dominated_mask
from tests.mocks.affine_simulator import affine_simulator
from tests.support import frames_identical, load_fixture, make_baseline, snapshot

SMALL = OptimizerConfig(seed=7, population_size=16, generations=5, max_evaluations=80)
NOOP_ID = "strategy-84d0730a93b9d729"


def counting(simulator):
    calls: list[ActionConfig] = []

    def wrapped(baseline, config, *, assumptions):
        calls.append(config)
        return simulator(baseline, config, assumptions=assumptions)

    return wrapped, calls


@pytest.fixture(scope="module")
def small_run():
    from tests.support import fixture_assumptions, fixture_baseline

    baseline, assumptions = fixture_baseline(), fixture_assumptions()
    constraints = ser.constraints_from_dict(load_fixture("constraints.json"))
    result = optimize_strategies(baseline, constraints, assumptions=assumptions, config=SMALL, simulator=simulate_strategy)
    return baseline, assumptions, constraints, result


def assert_valid_frontier(result, constraints):
    pareto = result.pareto
    assert len(pareto) > 0 and pareto["feasible"].all() and (pareto["pareto_rank"] == 0).all()
    for sid in pareto["strategy_id"]:
        metrics = result.strategies[sid].metrics
        assert metrics["total_cost_gbp"] <= constraints.budget_gbp + 0.01
        assert metrics["total_profit_gbp"] >= constraints.min_total_profit_gbp - 0.01
        assert metrics["co2_reduction_ratio"] >= constraints.min_co2_reduction_ratio - 1e-8
    emissions, profits = pareto["total_co2e_tco2e"].to_numpy(), pareto["total_profit_gbp"].to_numpy()
    declared = result.diagnostics["dominance_tolerances"]
    assert (declared["emissions_tco2e"], declared["profit_gbp"]) == dominance_tolerances(result.candidates)
    assert not dominated_mask(
        emissions, profits, emissions_tol=declared["emissions_tco2e"], profit_tol=declared["profit_gbp"]
    ).any()


# ---------------------------------------------------------------------------
# Adapter: seeds, objective signs, constraint direction
# ---------------------------------------------------------------------------


def test_deterministic_seed_configurations():
    seeds = default_seed_configs()
    assert seeds[0] == ActionConfig.noop()
    for i, name in enumerate(ACTION_NAMES, start=1):
        assert seeds[i] == ActionConfig(**{n: (1.0 if n == name else 0.0) for n in ACTION_NAMES})
    assert seeds[7] == ActionConfig(*[1.0] * 6) and seeds[8] == ActionConfig(*[0.5] * 6)


def test_objectives_minimize_emissions_and_negative_profit(baseline, assumptions, example_config):
    result = simulate_strategy(baseline, example_config, assumptions=assumptions)
    co2, negative_profit = objective_vector(result)
    assert co2 == pytest.approx(843.744) and negative_profit == pytest.approx(-1_210_940.7847619047)


def test_solver_constraints_are_shifted_by_tolerance_and_respect_raw_boundaries(baseline, assumptions, example_config):
    result = simulate_strategy(baseline, example_config, assumptions=assumptions)
    evaluation = evaluate_constraints(result, ConstraintConfig(500_000.0, 1_000_000.0, 0.2))
    assert solver_constraint_vector(evaluation) == pytest.approx(
        (evaluation.g_budget - 1e-8, evaluation.g_profit - 1e-8, evaluation.g_target - 1e-8)
    )
    # Over a 1e9 budget by 5 GBP: normalized g = 5e-9 passes, raw boundary fails -> stays positive for the solver.
    over = dataclasses.replace(result, metrics={**result.metrics, "total_cost_gbp": 1e9 + 5.0})
    raw_only = evaluate_constraints(over, ConstraintConfig(1e9, -1e9, 0.0))
    assert raw_only.g_budget <= 1e-8 and not raw_only.satisfied["budget"]
    assert solver_constraint_vector(raw_only)[0] > 0.0


def test_toy_problem_moves_toward_the_known_frontier(baseline, assumptions):
    # Affine double: E = 1200(1 - 0.2a - 0.1b), cost = 100,000a + 150,000b, profit = 1.2e6 - 0.01*cost.
    # Budget 120,000 and target 0.15 give min E = 944.0 (a=1, b=0.1333) and max profit 1,199,250 (a=0.75, b=0).
    # The best deterministic seeds reach only E = 960 and profit 1,199,000.
    constraints = ConstraintConfig(budget_gbp=120_000.0, min_total_profit_gbp=1_000_000.0, min_co2_reduction_ratio=0.15)
    result = optimize_strategies(
        baseline,
        constraints,
        assumptions=assumptions,
        config=OptimizerConfig(seed=42, population_size=32, generations=30, max_evaluations=960),
        simulator=affine_simulator,
    )
    assert result.status == "ok"
    assert_valid_frontier(result, constraints)
    min_emissions = result.pareto["total_co2e_tco2e"].min()
    max_profit = result.pareto["total_profit_gbp"].max()
    assert 944.0 - 1e-6 <= min_emissions < 959.0  # beats the seeds, never beats the analytical optimum
    assert 1_199_001.0 < max_profit <= 1_199_250.0 + 0.01
    assert result.provenance.is_mock and result.diagnostics["simulator_providers"] == ["affine-test-double"]


# ---------------------------------------------------------------------------
# Real simulator: validity, audit parity, reproducibility, budget
# ---------------------------------------------------------------------------


def test_small_real_run_returns_a_validated_frontier(small_run):
    _, _, constraints, result = small_run
    assert result.status == "ok"
    assert_valid_frontier(result, constraints)
    candidates = result.candidates
    assert list(candidates.columns) == list(OPTIMIZATION_TABLE_COLUMNS)
    assert candidates["strategy_id"].is_unique and not candidates.duplicated(subset=list(ACTION_NAMES)).any()
    assert set(candidates["strategy_id"]) == set(result.strategies)
    assert set(result.pareto["strategy_id"]) == set(candidates.loc[candidates["pareto_rank"] == 0, "strategy_id"])
    assert (candidates.loc[~candidates["feasible"], "pareto_rank"] == -1).all()
    diagnostics = result.diagnostics
    assert diagnostics["tested_noop_strategy_id"] == NOOP_ID and NOOP_ID in result.strategies
    assert diagnostics["unique_count"] == len(candidates) <= diagnostics["evaluated_count"] <= SMALL.max_evaluations
    assert diagnostics["revalidated_pareto_count"] == len(result.pareto)
    assert diagnostics["repair_policy"] == "clip_to_unit_interval"


def test_stored_outcomes_equal_direct_simulation(small_run):
    baseline, assumptions, constraints, result = small_run
    rows = result.candidates.set_index("strategy_id")
    for sid, stored in result.strategies.items():
        direct = simulate_strategy(baseline, stored.config, assumptions=assumptions)
        assert direct.strategy_id == sid
        assert direct.metrics == stored.metrics and frames_identical(direct.monthly, stored.monthly)
        row, evaluation = rows.loc[sid], evaluate_constraints(direct, constraints)
        assert row["total_co2e_tco2e"] == direct.metrics["total_co2e_tco2e"]
        assert row["total_profit_gbp"] == direct.metrics["total_profit_gbp"]
        assert row["total_cost_gbp"] == direct.metrics["total_cost_gbp"]
        assert (row["g_budget"], row["g_profit"], row["g_target"]) == (evaluation.g_budget, evaluation.g_profit, evaluation.g_target)
        assert bool(row["feasible"]) is evaluation.feasible
        assert tuple(row[list(ACTION_NAMES)]) == stored.config.as_vector()


def test_seeded_runs_are_reproducible_and_seeds_matter(baseline, assumptions, example_constraints):
    def run(seed):
        return optimize_strategies(
            baseline, example_constraints, assumptions=assumptions, config=dataclasses.replace(SMALL, seed=seed), simulator=simulate_strategy
        )

    first, second, other = run(7), run(7), run(8)
    assert frames_identical(first.candidates, second.candidates) and frames_identical(first.pareto, second.pareto)
    assert first.run_id == second.run_id and first.provenance == second.provenance
    strip = lambda d: {k: v for k, v in d.items() if k != "runtime_seconds"}  # noqa: E731
    assert strip(first.diagnostics) == strip(second.diagnostics)
    assert set(first.candidates["strategy_id"]) != set(other.candidates["strategy_id"])


def test_evaluation_budget_includes_initialization(baseline, assumptions, example_constraints):
    simulator, calls = counting(simulate_strategy)
    config = OptimizerConfig(seed=3, population_size=10, generations=50, max_evaluations=37)
    result = optimize_strategies(baseline, example_constraints, assumptions=assumptions, config=config, simulator=simulator)
    diagnostics = result.diagnostics
    assert diagnostics["evaluated_count"] == 37  # 10 initial + 10 + 10 + 7 (last generation truncated)
    assert diagnostics["termination_reason"] == "max_evaluations"
    assert diagnostics["unique_count"] <= 37
    assert len(calls) == diagnostics["unique_count"] + diagnostics["revalidated_pareto_count"]


def test_a_budget_of_one_evaluates_only_the_noop(baseline, assumptions, example_constraints):
    simulator, calls = counting(simulate_strategy)
    config = OptimizerConfig(seed=1, population_size=64, generations=32, max_evaluations=1)
    result = optimize_strategies(baseline, example_constraints, assumptions=assumptions, config=config, simulator=simulator)
    assert calls == [ActionConfig.noop()]
    assert result.candidates["strategy_id"].tolist() == [NOOP_ID]
    assert result.status == "infeasible"  # the no-op misses the 20% reduction target
    assert result.diagnostics["evaluated_count"] == 1


def test_infeasible_search_returns_typed_empty_frontier_and_diagnostics(baseline, assumptions):
    constraints = ConstraintConfig(budget_gbp=0.0, min_total_profit_gbp=1_000_000.0, min_co2_reduction_ratio=0.2)
    result = optimize_strategies(baseline, constraints, assumptions=assumptions, config=SMALL, simulator=simulate_strategy)
    assert result.status == "infeasible"
    assert len(result.pareto) == 0
    assert list(result.pareto.columns) == list(OPTIMIZATION_TABLE_COLUMNS)
    assert str(result.pareto["feasible"].dtype) == "bool" and str(result.pareto["pareto_rank"].dtype) == "int64"
    assert len(result.candidates) > 0 and (~result.candidates["feasible"]).all()
    assert (result.candidates["pareto_rank"] == -1).all()
    diagnostics = result.diagnostics
    fixture_keys = set(load_fixture("optimization_infeasible.json")["diagnostics"])
    assert fixture_keys <= set(diagnostics)
    # Each constraint is individually reachable (the no-op spends nothing; full implementation meets
    # the target), but no candidate satisfies them jointly.
    assert diagnostics["minimum_normalized_violations"]["budget"] == 0.0
    assert diagnostics["minimum_normalized_violations"]["target"] == 0.0
    assert diagnostics["minimum_total_normalized_violation"] > 0.0
    assert diagnostics["least_violating_strategy_id"] in result.strategies
    assert "not a proof" in diagnostics["warning"]


def test_zero_baseline_with_positive_target_fails_before_any_simulation(assumptions):
    baseline = make_baseline(scope1_tco2e=0.0, scope2_tco2e=0.0, scope3_tco2e=0.0)
    simulator, calls = counting(simulate_strategy)
    with pytest.raises(ContractValidationError) as info:
        optimize_strategies(baseline, ConstraintConfig(1e6, 0.0, 0.1), assumptions=assumptions, config=SMALL, simulator=simulator)
    assert info.value.field == "constraints.min_co2_reduction_ratio" and calls == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"population_size": 0},
        {"generations": 0},
        {"max_evaluations": 0},
        {"seed": -1},
        {"seed": 1.5},
        {"population_size": 64.0},
        {"generations": True},
    ],
)
def test_invalid_optimizer_configs_are_rejected(kwargs):
    with pytest.raises(ContractValidationError):
        val.validate_optimizer_config(OptimizerConfig(**kwargs))


def test_inputs_are_validated_and_not_mutated(baseline, assumptions, example_constraints):
    with pytest.raises(ContractValidationError, match="simulator"):
        optimize_strategies(baseline, example_constraints, assumptions=assumptions, config=SMALL, simulator="simulate")  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError, match="optimizer_config"):
        optimize_strategies(baseline, example_constraints, assumptions=assumptions, config={"seed": 1}, simulator=simulate_strategy)  # type: ignore[arg-type]
    before = (snapshot(baseline), snapshot(assumptions), example_constraints)
    optimize_strategies(baseline, example_constraints, assumptions=assumptions, config=SMALL, simulator=simulate_strategy)
    assert frames_identical(baseline.monthly, before[0].monthly) and assumptions == before[1]
    assert example_constraints == before[2]


def test_global_numpy_random_state_is_untouched(baseline, assumptions, example_constraints):
    before = np.random.get_state()
    optimize_strategies(baseline, example_constraints, assumptions=assumptions, config=SMALL, simulator=simulate_strategy)
    after = np.random.get_state()
    assert before[0] == after[0] and np.array_equal(before[1], after[1]) and before[2:] == after[2:]


# ---------------------------------------------------------------------------
# Failure typing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fail_on_call", [1, 5])
def test_unexpected_simulator_failure_is_an_optimization_error(baseline, assumptions, example_constraints, fail_on_call):
    count = {"n": 0}

    def flaky(b, config, *, assumptions):
        count["n"] += 1
        if count["n"] == fail_on_call:
            raise RuntimeError("simulated crash")
        return simulate_strategy(b, config, assumptions=assumptions)

    with pytest.raises(OptimizationError) as info:
        optimize_strategies(baseline, example_constraints, assumptions=assumptions, config=SMALL, simulator=flaky)
    assert isinstance(info.value.__cause__, RuntimeError)


def test_invalid_simulator_output_is_a_contract_error(baseline, assumptions, example_constraints):
    def wrong_config(b, config, *, assumptions):
        return simulate_strategy(b, ActionConfig(*[0.5] * 6), assumptions=assumptions)

    with pytest.raises(ContractValidationError, match="different configuration"):
        optimize_strategies(baseline, example_constraints, assumptions=assumptions, config=SMALL, simulator=wrong_config)
    with pytest.raises(ContractValidationError):
        optimize_strategies(baseline, example_constraints, assumptions=assumptions, config=SMALL, simulator=lambda b, c, *, assumptions: {})


def test_simulator_input_validation_errors_propagate_unwrapped(assumptions, example_constraints):
    with pytest.raises(ContractValidationError) as info:
        optimize_strategies(make_baseline(fleet_km=0.0), example_constraints, assumptions=assumptions, config=SMALL, simulator=simulate_strategy)
    assert info.value.field == "baseline.monthly.fleet_km"


def test_nondeterministic_simulator_is_caught_by_frontier_revalidation(baseline, assumptions, example_constraints):
    count = {"n": 0}

    def drifting(b, config, *, assumptions):
        count["n"] += 1
        result = simulate_strategy(b, config, assumptions=assumptions)
        drift = count["n"] * 1e-7  # tiny, still inside every reconciliation tolerance
        return dataclasses.replace(result, metrics={**result.metrics, "total_profit_gbp": result.metrics["total_profit_gbp"] + drift})

    with pytest.raises(OptimizationError, match="not deterministic"):
        optimize_strategies(baseline, example_constraints, assumptions=assumptions, config=SMALL, simulator=drifting)


def test_truncated_id_collision_is_extended_end_to_end(baseline, assumptions, example_constraints, monkeypatch):
    collide = "strategy-0000000000000000"
    real_assign = optimizer_module.assign_strategy_id

    def forced(identity, taken, **kwargs):
        def id_fn(text, *, hex_length):
            return collide if hex_length == 16 else strategy_id_from_identity(text, hex_length=hex_length)

        return real_assign(identity, taken, id_fn=id_fn)

    monkeypatch.setattr(optimizer_module, "assign_strategy_id", forced)
    result = optimize_strategies(baseline, example_constraints, assumptions=assumptions, config=SMALL, simulator=simulate_strategy)
    assert collide in result.strategies  # the first candidate keeps the colliding 16-hex ID
    extended = [sid for sid in result.strategies if sid != collide]
    assert extended and all(len(sid) > len(collide) for sid in extended)
    assert all(result.strategies[sid].strategy_id == sid for sid in result.strategies)
    assert set(result.candidates["strategy_id"]) == set(result.strategies)


# ---------------------------------------------------------------------------
# Provenance, serialization and the reference configuration
# ---------------------------------------------------------------------------


def test_mock_provenance_propagates_and_real_inputs_are_not_mock(assumptions, example_constraints):
    mock = optimize_strategies(make_baseline(), example_constraints, assumptions=assumptions, config=SMALL, simulator=simulate_strategy)
    real = optimize_strategies(make_baseline(is_mock=False), example_constraints, assumptions=assumptions, config=SMALL, simulator=simulate_strategy)
    assert mock.provenance.is_mock and "mock provenance" in mock.diagnostics["warning"]
    assert not real.provenance.is_mock and "warning" not in real.diagnostics
    assert real.provenance.provider == "nsga2-optimizer" and real.provenance.seed == SMALL.seed
    assert real.provenance.assumptions_id == "demo-actions-v1"


def test_optimization_json_round_trip_through_shared_serializers(small_run):
    _, _, _, result = small_run
    restored = val.validate_optimization_result(ser.optimization_from_dict(json.loads(ser.to_json(result))))
    assert frames_identical(restored.candidates, result.candidates) and frames_identical(restored.pareto, result.pareto)
    assert set(restored.strategies) == set(result.strategies)
    for sid, stored in result.strategies.items():
        assert restored.strategies[sid].metrics == stored.metrics
        assert frames_identical(restored.strategies[sid].monthly, stored.monthly)
        assert restored.strategies[sid].config == stored.config
    assert dict(restored.diagnostics) == dict(result.diagnostics)
    assert (restored.run_id, restored.provenance, restored.status) == (result.run_id, result.provenance, result.status)


def test_reference_configuration_respects_budget_and_constraints(baseline, assumptions, example_constraints):
    config = OptimizerConfig()  # documented reference: 64 x 32 = 2,048 evaluations
    result = optimize_strategies(baseline, example_constraints, assumptions=assumptions, config=config, simulator=simulate_strategy)
    diagnostics = result.diagnostics
    assert result.status == "ok"
    assert diagnostics["evaluated_count"] <= config.max_evaluations
    assert diagnostics["termination_reason"] in {"max_generations", "max_evaluations"}
    assert diagnostics["revalidated_pareto_count"] == len(result.pareto)
    assert diagnostics["runtime_seconds"] > 0.0
    assert_valid_frontier(result, example_constraints)
