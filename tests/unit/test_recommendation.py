"""Deterministic (P0) and risk-aware (P1) recommendation with hand-authored expectations."""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from src.actions import simulate_strategy
from src.contracts import (
    ActionConfig,
    ConstraintConfig,
    ContractValidationError,
    OptimizationResult,
    Provenance,
    RiskResult,
    RiskSummary,
)
from src.contracts import serialization as ser
from src.optimization import evaluate_what_if, optimize_strategies, recommend_strategy, select_risk_pool
from src.optimization.recommendation import DETERMINISTIC_POLICY, normalized_score
from tests.support import (
    candidate_table,
    fixture_assumptions,
    fixture_baseline,
    frames_identical,
    load_fixture,
)

PROVENANCE = Provenance(provider="test", is_mock=False, seed=42, input_hash="h", config_id="c", assumptions_id="a")


def optimization_with(points, *, status="ok", is_mock=False) -> OptimizationResult:
    """OptimizationResult whose frontier is exactly ``points`` = [(strategy_id, emissions, profit), ...]."""
    frame = candidate_table(*({"strategy_id": s, "total_co2e_tco2e": e, "total_profit_gbp": p} for s, e, p in points))
    frame["pareto_rank"] = 0
    placeholder = simulate_strategy(fixture_baseline(), ActionConfig.zeros(), assumptions=fixture_assumptions())
    return OptimizationResult(
        schema_version="1.0.0",
        run_id="optimization-test",
        provenance=dataclasses.replace(PROVENANCE, is_mock=is_mock),
        status=status,
        baseline_id="baseline-demo-v1",
        constraints=ConstraintConfig(1e6, 0.0, 0.0),
        strategies={s: dataclasses.replace(placeholder, strategy_id=s) for s, _, _ in points},
        candidates=frame,
        pareto=frame if status == "ok" else frame.iloc[0:0],
        diagnostics={},
    )


def risk(sid, *, co2_mean, co2_p95, profit_mean, profit_p05, joint, baseline_id="baseline-demo-v1", uncertainty_id="u-1", seed=42):
    summary = RiskSummary(
        co2_mean_tco2e=co2_mean,
        co2_p05_tco2e=co2_mean - 5.0,
        co2_p95_tco2e=co2_p95,
        profit_mean_gbp=profit_mean,
        profit_p05_gbp=profit_p05,
        profit_p95_gbp=profit_mean + 50.0,
        cost_mean_gbp=1_000.0,
        cost_p95_gbp=1_100.0,
        target_probability=joint,
        profit_floor_probability=1.0,
        budget_probability=1.0,
        joint_feasibility_probability=joint,
        target_probability_mc_standard_error=None if joint is None else math.sqrt(joint * (1 - joint) / 1_000),
    )
    return RiskResult(
        schema_version="1.0.0",
        run_id=f"risk-{sid}",
        provenance=Provenance(provider="risk-test", is_mock=True, seed=seed, input_hash=f"h-{sid}", config_id="c", assumptions_id="a"),
        strategy_id=sid,
        baseline_id=baseline_id,
        summary=summary,
        n_simulations=1_000,
        uncertainty_id=uncertainty_id,
    )


# Four frontier strategies ordered by emissions, with risk profiles chosen so that the three
# tolerances select three different strategies.
FRONTIER = [("strategy-a", 100.0, 1_000.0), ("strategy-b", 112.0, 1_400.0), ("strategy-c", 120.0, 1_450.0), ("strategy-d", 140.0, 1_500.0)]
RISK_PROFILES = {
    "strategy-a": dict(co2_mean=100.0, co2_p95=105.0, profit_mean=1_000.0, profit_p05=990.0, joint=0.97),
    "strategy-b": dict(co2_mean=112.0, co2_p95=140.0, profit_mean=1_400.0, profit_p05=1_100.0, joint=0.92),
    "strategy-c": dict(co2_mean=120.0, co2_p95=130.0, profit_mean=1_450.0, profit_p05=1_300.0, joint=0.91),
    "strategy-d": dict(co2_mean=140.0, co2_p95=150.0, profit_mean=1_500.0, profit_p05=1_450.0, joint=0.60),
}


def risk_pool(**overrides):
    profiles = {sid: dict(profile, **overrides.get(sid, {})) for sid, profile in RISK_PROFILES.items()}
    return {sid: risk(sid, **profile) for sid, profile in profiles.items()}


# ---------------------------------------------------------------------------
# P0 deterministic equal-weight policy
# ---------------------------------------------------------------------------


def test_equal_weight_score_hand_calculation():
    # emissions 100/150/200 -> 0, 0.5, 1; negative profit -1000/-1500/-1800 -> 1, 0.375, 0
    # scores 0.5, 0.4375, 0.5 -> the middle strategy.
    result = recommend_strategy(optimization_with([("strategy-x", 100.0, 1_000.0), ("strategy-y", 150.0, 1_500.0), ("strategy-z", 200.0, 1_800.0)]))
    assert result.strategy_id == "strategy-y" and result.score == pytest.approx(0.4375)
    assert result.policy == DETERMINISTIC_POLICY and result.risk_status == "not_requested"
    assert result.tolerance == "balanced"


def test_equal_scores_break_ties_by_smallest_strategy_id():
    result = recommend_strategy(optimization_with([("strategy-b", 100.0, 1_000.0), ("strategy-a", 200.0, 2_000.0)]))
    assert result.strategy_id == "strategy-a" and result.score == pytest.approx(0.5)


def test_constant_objectives_contribute_zero():
    scores = normalized_score([100.0, 100.0 + 1e-7], [1_000.0, 1_500.0])  # emissions constant within tolerance
    assert scores.tolist() == pytest.approx([0.5, 0.0])
    both_constant = optimization_with([("strategy-q", 100.0, 1_000.0), ("strategy-p", 100.0 + 1e-7, 1_000.004)])
    result = recommend_strategy(both_constant)
    assert result.strategy_id == "strategy-p" and result.score == 0.0


def test_single_point_frontier_is_selected():
    result = recommend_strategy(optimization_with([("strategy-only", 500.0, 1.0)]))
    assert result.strategy_id == "strategy-only" and result.score == 0.0


def test_infeasible_optimization_has_null_recommendation():
    infeasible = optimization_with([("strategy-a", 1.0, 1.0)], status="infeasible")
    plain = recommend_strategy(infeasible)
    assert plain.strategy_id is None and plain.score is None and plain.risk_status == "not_requested"
    assert "not a proof" in plain.reason
    assert recommend_strategy(infeasible, risk_results={}, tolerance="conservative").risk_status == "unavailable"


def test_invalid_requests_are_rejected():
    optimization = optimization_with(FRONTIER)
    with pytest.raises(ContractValidationError, match="tolerance"):
        recommend_strategy(optimization, tolerance="reckless")
    with pytest.raises(ContractValidationError, match="optimization"):
        recommend_strategy({"status": "ok"})  # type: ignore[arg-type]
    broken = dataclasses.replace(optimization, strategies={})
    with pytest.raises(ContractValidationError, match="missing Pareto strategies"):
        recommend_strategy(broken)


def test_fixture_optimization_selects_its_single_feasible_strategy():
    optimization = ser.optimization_result_from_dict(load_fixture("optimization_ok.json"))
    result = recommend_strategy(optimization)
    assert result.strategy_id == "strategy-8be15857fffc57f6" and result.provenance.is_mock


def test_real_optimization_recommendation_is_deterministic_and_matches_manual_what_if():
    baseline, assumptions = fixture_baseline(), fixture_assumptions()
    constraints = ser.constraint_config_from_dict(load_fixture("constraints.json"))
    from src.contracts import OptimizerConfig

    optimization = optimize_strategies(
        baseline, constraints, assumptions=assumptions, config=OptimizerConfig(seed=5, population_size=16, generations=4, max_evaluations=64),
        simulator=simulate_strategy,
    )
    first, second = recommend_strategy(optimization), recommend_strategy(optimization)
    assert first == second and first.strategy_id in set(optimization.pareto["strategy_id"])
    stored = optimization.strategies[first.strategy_id]
    manual = evaluate_what_if(baseline, stored.config, assumptions=assumptions, constraints=constraints)
    assert manual.simulation.metrics == stored.metrics and frames_identical(manual.simulation.monthly, stored.monthly)
    assert manual.constraints.feasible


def test_recommendation_json_round_trip():
    result = recommend_strategy(optimization_with(FRONTIER), risk_results=risk_pool(), tolerance="conservative")
    restored = ser.recommendation_from_dict(json.loads(ser.to_json(result)))
    assert restored == result


# ---------------------------------------------------------------------------
# P1 risk-aware policies (hand-authored summaries)
# ---------------------------------------------------------------------------


def test_tolerances_select_different_strategies_from_the_same_pool():
    optimization, results = optimization_with(FRONTIER), risk_pool()
    conservative = recommend_strategy(optimization, risk_results=results, tolerance="conservative")
    balanced = recommend_strategy(optimization, risk_results=results, tolerance="balanced")
    aggressive = recommend_strategy(optimization, risk_results=results, tolerance="aggressive")
    # Conservative: eligible a,b,c (joint >= 0.90); p95 105/140/130 -> 0, 1, 25/35;
    # negative p05 -990/-1100/-1300 -> 1, 200/310, 0; scores 0.5, 0.8226, 0.3571 -> c.
    assert conservative.strategy_id == "strategy-c" and conservative.score == pytest.approx(0.5 * 25 / 35)
    # Balanced: eligible a,b,c (joint >= 0.75); mean CO2e -> 0, 0.6, 1; negative mean profit -> 1, 50/450, 0;
    # scores 0.5, 0.3556, 0.5 -> b.
    assert balanced.strategy_id == "strategy-b" and balanced.score == pytest.approx(0.5 * 0.6 + 0.5 * 50 / 450)
    # Aggressive: all four; 0.75 * (0, 0.3, 0.5, 1) + 0.25 * (1, 0.2, 0.1, 0) -> a.
    assert aggressive.strategy_id == "strategy-a" and aggressive.score == pytest.approx(0.25)
    for result, policy in ((conservative, "risk_conservative"), (balanced, "risk_balanced"), (aggressive, "risk_aggressive")):
        assert result.risk_status == "evaluated" and result.policy == policy
        assert result.diagnostics["coverage"] == "full" and result.diagnostics["pool_size"] == 4
        assert result.provenance.is_mock  # risk inputs are labelled mock


def test_threshold_unmet_picks_highest_joint_probability_and_reports_shortfall():
    results = risk_pool(**{"strategy-a": {"joint": 0.85}, "strategy-b": {"joint": 0.88}, "strategy-c": {"joint": 0.88}, "strategy-d": {"joint": 0.5}})
    result = recommend_strategy(optimization_with(FRONTIER), risk_results=results, tolerance="conservative")
    # b and c tie at 0.88; over all four, conservative scores are b 0.769 and c 0.441 -> c.
    assert result.strategy_id == "strategy-c" and result.risk_status == "threshold_unmet"
    assert result.diagnostics["shortfall"] == pytest.approx(0.02)
    assert result.diagnostics["selected_joint_feasibility_probability"] == pytest.approx(0.88)
    assert "shortfall" in result.reason


def test_partial_coverage_is_visible():
    results = risk_pool()
    del results["strategy-d"]
    result = recommend_strategy(optimization_with(FRONTIER), risk_results=results, tolerance="aggressive")
    assert result.risk_status == "partial" and result.strategy_id == "strategy-a"
    assert result.diagnostics["coverage"] == "partial"
    assert result.diagnostics["excluded_strategy_ids"] == {"strategy-d": "missing"}
    assert "partial" in result.reason


def test_unavailable_risk_falls_back_without_claiming_risk_selection():
    optimization = optimization_with(FRONTIER)
    fallback = recommend_strategy(optimization, risk_results={}, tolerance="conservative")
    deterministic = recommend_strategy(optimization)
    assert fallback.risk_status == "unavailable" and fallback.policy == DETERMINISTIC_POLICY
    assert fallback.strategy_id == deterministic.strategy_id and fallback.score == deterministic.score
    assert "no conservative risk selection is claimed" in fallback.reason


def test_invalid_or_mismatched_risk_results_are_excluded_with_reasons():
    results = risk_pool()
    results["strategy-a"] = risk("strategy-a", **RISK_PROFILES["strategy-a"], baseline_id="another-baseline")
    results["strategy-b"] = results["strategy-c"]  # keyed under the wrong strategy
    result = recommend_strategy(optimization_with(FRONTIER), risk_results=results, tolerance="aggressive")
    excluded = result.diagnostics["excluded_strategy_ids"]
    assert set(excluded) == {"strategy-a", "strategy-b"} and result.risk_status == "partial"
    assert result.strategy_id in {"strategy-c", "strategy-d"}


def test_null_joint_probability_excludes_only_threshold_policies():
    results = risk_pool(**{"strategy-c": {"joint": None}})
    balanced = recommend_strategy(optimization_with(FRONTIER), risk_results=results, tolerance="balanced")
    assert "strategy-c" in balanced.diagnostics["excluded_strategy_ids"]
    aggressive = recommend_strategy(optimization_with(FRONTIER), risk_results=results, tolerance="aggressive")
    assert aggressive.diagnostics["coverage"] == "full"


def test_mismatched_trial_sets_are_rejected():
    results = risk_pool()
    results["strategy-d"] = risk("strategy-d", **RISK_PROFILES["strategy-d"], uncertainty_id="u-2")
    with pytest.raises(ContractValidationError, match="one trial set"):
        recommend_strategy(optimization_with(FRONTIER), risk_results=results, tolerance="balanced")


def test_results_outside_the_pool_are_ignored():
    results = {**risk_pool(), "strategy-zz": risk("strategy-zz", **RISK_PROFILES["strategy-a"])}
    result = recommend_strategy(optimization_with(FRONTIER), risk_results=results, tolerance="balanced")
    assert result.diagnostics["ignored_outside_pool"] == ["strategy-zz"] and result.risk_status == "evaluated"


def test_fixture_risk_summary_on_fixture_frontier():
    optimization = ser.optimization_result_from_dict(load_fixture("optimization_ok.json"))
    summary = ser.risk_result_from_dict(load_fixture("risk_summary.json"))
    result = recommend_strategy(optimization, risk_results={summary.strategy_id: summary}, tolerance="conservative")
    assert result.strategy_id == "strategy-8be15857fffc57f6" and result.risk_status == "evaluated"
    assert result.diagnostics["selected_joint_feasibility_probability"] == pytest.approx(0.96)


def test_risk_pool_keeps_endpoints_and_samples_evenly():
    points = [(f"strategy-{i:02d}", 100.0 + i, 1_000.0 + 10 * i) for i in range(45)]
    pool = select_risk_pool(optimization_with(points))
    order = [sid for sid, _, _ in points]
    positions = [order.index(sid) for sid in pool]
    assert len(pool) == 20 and positions[0] == 0 and positions[-1] == 44
    assert positions == sorted(set(positions))  # unique, in emissions order
    assert max(b - a for a, b in zip(positions, positions[1:])) <= 3  # 44 / 19 ~ 2.3 apart
    assert select_risk_pool(optimization_with(points[:7])) == tuple(order[:7])
    assert select_risk_pool(optimization_with([("strategy-a", 1.0, 1.0)], status="infeasible")) == ()
    with pytest.raises(ContractValidationError):
        select_risk_pool(optimization_with(points), max_size=1)


def test_pool_order_ignores_input_row_order():
    shuffled = optimization_with(list(reversed(FRONTIER)))
    assert select_risk_pool(shuffled) == ("strategy-a", "strategy-b", "strategy-c", "strategy-d")
