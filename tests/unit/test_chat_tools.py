"""Allowlist, argument validation, unit conversion and tool execution."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.contracts.types import ActionConfig
from src.integration import run_analysis
from src.llm.context import AnalysisContext
from src.llm.tools import (
    ALLOWED_TOOLS,
    CHAT_MAX_EVALUATIONS,
    TOOL_SPECS,
    ToolArgumentError,
    adoption_fraction,
    execute_tool,
    validate_arguments,
)
from tests.mocks import make_services
from tests.mocks.behavioral import BehavioralMockOptimizer


@pytest.fixture
def analysis(mock_services, request_ok):
    return run_analysis(request_ok, services=mock_services)


@pytest.fixture
def ctx(mock_services, request_ok, analysis):
    return AnalysisContext(mock_services, request_ok, analysis.baseline, analysis,
                           analysis.optimization.strategies[analysis.recommendation.strategy_id])


def run(ctx, name, args):
    return execute_tool(name, args, context=ctx, services=ctx.services)


def test_allowlist_matches_documented_tools():
    assert ALLOWED_TOOLS == ("get_baseline", "simulate_strategy", "optimize_strategies", "get_risk_summary",
                             "get_company_profile", "compare_actions", "get_public_reference", "get_forecast_drivers")
    assert [s.name for s in TOOL_SPECS] == list(ALLOWED_TOOLS)


@pytest.mark.parametrize("name,args,match", [
    ("run_shell", {"cmd": "ls"}, "unknown tool"),
    ("get_baseline", {"company_id": "other"}, "unknown fields"),
    ("simulate_strategy", {"company_id": "x"}, "unknown fields"),
    ("simulate_strategy", {"actions": {"solar": 0.5}}, "unknown fields"),
    ("simulate_strategy", {"actions": {"ev_adoption": 80}}, "pass a 0-1 ratio"),
    ("simulate_strategy", {"final_shares": {"ev_adoption": 80}}, "0.8 for 80%"),
    ("simulate_strategy", {"actions": {"ev_adoption": True}}, "finite number"),
    ("simulate_strategy", {"actions": {"ev_adoption": "0.5"}}, "finite number"),
    ("simulate_strategy", {"actions": {"ev_adoption": float("nan")}}, "finite number"),
    ("simulate_strategy", {"final_shares": {"cloud_efficiency": 0.5}}, "unknown fields"),
    ("simulate_strategy", {"actions": {"ev_adoption": 0.5}, "final_shares": {"ev_adoption": 0.8}}, "choose one"),
    ("simulate_strategy", {"start_from": "yesterday"}, "start_from"),
    ("optimize_strategies", {"budget_gbp": -1}, ">= 0"),
    ("get_forecast_drivers", {"top_k": 0}, ">= 1"),
    ("get_forecast_drivers", {"top_k": 2.5}, "whole number"),
    ("optimize_strategies", {"min_co2_reduction_ratio": 20}, "ratio"),
    ("optimize_strategies", {"endpoint": "http://x"}, "unknown fields"),
    ("get_risk_summary", {"strategy_id": ""}, "nonempty"),
    ("simulate_strategy", "not an object", "must be an object"),
])
def test_validation_rejects_malformed_arguments(name, args, match):
    with pytest.raises(ToolArgumentError, match=match):
        validate_arguments(name, args)


def test_invalid_call_returns_error_result_and_never_dispatches(ctx, monkeypatch):
    calls = []
    monkeypatch.setattr(type(ctx.services.simulator), "simulate", lambda *a, **k: calls.append(1))
    r = run(ctx, "simulate_strategy", {"actions": {"ev_adoption": 80}})
    assert r.status == "error" and "invalid arguments" in r.error and r.data is None and calls == []
    assert run(ctx, "delete_everything", {}).status == "error"


# --------------------------- adoption share conversion ----------------------- #


@pytest.mark.parametrize("v,target,x", [(0.2, 0.76, 0.7), (0.0, 0.8, 0.8), (0.2, 0.2, 0.0), (0.5, 1.0, 1.0)])
def test_adoption_fraction_uses_documented_formula(v, target, x):
    assert adoption_fraction(v, target) == pytest.approx(x)


def test_adoption_fraction_edge_cases():
    assert adoption_fraction(1.0, 1.0) == 0.0  # fully adopted baseline: no division by zero
    with pytest.raises(ToolArgumentError, match="below the current baseline"):
        adoption_fraction(0.5, 0.4)
    with pytest.raises(ToolArgumentError, match="unreachable"):
        adoption_fraction(0.0, 0.8, effectiveness=0.5)
    with pytest.raises(ToolArgumentError, match="zero effectiveness"):
        adoption_fraction(0.1, 0.5, effectiveness=0.0)


# ------------------------------- simulation --------------------------------- #


def test_simulate_final_share_equals_direct_service_call(ctx):
    r = run(ctx, "simulate_strategy", {"final_shares": {"ev_adoption": 0.8}})
    assert r.status == "ok"
    expected = replace(ctx.selected.config, ev_adoption=0.8)
    direct = ctx.services.simulate(ctx.baseline, expected)
    d = r.data
    assert d["strategy_id"] == direct.strategy_id and d["config"] == expected.as_dict()
    assert all(d["metrics"][k] == direct.metrics[k] for k in d["metrics"])
    assert d["conversions"] == [{"action": "ev_adoption", "baseline_share": 0.0, "target_final_share": 0.8,
                                 "fraction_of_remaining": 0.8}]
    assert d["resulting_shares"]["ev_adoption"] == {"baseline": 0.0, "resulting": pytest.approx(0.8)}
    assert d["is_mock"] is True  # provenance propagated from the mock backend


def test_final_share_conversion_for_renewable_uses_baseline_share(ctx):
    r = run(ctx, "simulate_strategy", {"start_from": "no_action", "final_shares": {"renewable_energy": 0.76}})
    assert r.data["config"]["renewable_energy"] == pytest.approx(0.7)  # baseline share 0.2
    assert r.data["conversions"][0]["baseline_share"] == 0.2


def test_fraction_semantics_differ_from_final_share(ctx):
    frac = run(ctx, "simulate_strategy", {"start_from": "no_action", "actions": {"renewable_energy": 0.7}})
    final = run(ctx, "simulate_strategy", {"start_from": "no_action", "final_shares": {"renewable_energy": 0.7}})
    assert frac.data["resulting_shares"]["renewable_energy"]["resulting"] == pytest.approx(0.76)
    assert final.data["resulting_shares"]["renewable_energy"]["resulting"] == pytest.approx(0.7)


def test_target_below_current_share_is_unsupported(ctx):
    r = run(ctx, "simulate_strategy", {"final_shares": {"renewable_energy": 0.1}})
    assert r.status == "error" and "below the current baseline" in r.error


def test_explain_selected_returns_stored_result_without_mutating_selection(ctx):
    r = run(ctx, "simulate_strategy", {"start_from": "selected_strategy"})
    assert r.data["matches_selected_strategy"] is True
    assert r.data["metrics"]["total_co2e_tco2e"] == ctx.selected.metrics["total_co2e_tco2e"]
    assert ctx.selected.config == ActionConfig.from_mapping(r.data["config"])


def test_no_selection_starts_from_no_action_with_note(mock_services, request_ok, analysis):
    c = AnalysisContext(mock_services, request_ok, analysis.baseline, None, None)
    r = run(c, "simulate_strategy", {})
    assert r.status == "ok" and r.data["config"] == ActionConfig.noop().as_dict()
    assert any("No strategy is selected" in n for n in r.data["notes"])
    assert r.data["metrics"]["co2_reduction_ratio"] == 0.0


def test_feasibility_comes_from_the_shared_constraint_evaluation(ctx):
    r = run(ctx, "simulate_strategy", {"start_from": "no_action"})
    # No action keeps the baseline profit (1.2m >= 1.0m floor) but misses the 20% target.
    assert r.data["feasibility"] == {"feasible": False, "failed": ["CO2 target"]}
    ok = run(ctx, "simulate_strategy", {"start_from": "selected_strategy"})
    assert ok.data["feasibility"] == {"feasible": True, "failed": []}


# ------------------------------- optimization ------------------------------- #


def test_optimize_uses_dashboard_constraints_unless_overridden(ctx):
    r = run(ctx, "optimize_strategies", {})
    assert r.data["constraints"] == {"budget_gbp": 500000.0, "min_total_profit_gbp": 1000000.0, "min_co2_reduction_ratio": 0.2}
    assert r.data["constraints_overridden"] == []
    r2 = run(ctx, "optimize_strategies", {"budget_gbp": 250000.0})
    assert r2.data["constraints"]["budget_gbp"] == 250000.0
    assert r2.data["constraints"]["min_total_profit_gbp"] == 1000000.0
    assert r2.data["constraints_overridden"] == ["budget_gbp"]
    assert ctx.request.constraints.budget_gbp == 500000.0  # dashboard request untouched


def test_optimize_matches_direct_service_call_and_bounds_evaluations(mock_services, request_ok, analysis):
    seen = {}

    class Spy(BehavioralMockOptimizer):
        def optimize(self, baseline, constraints, **kw):
            seen["max"] = kw["config"].max_evaluations
            return super().optimize(baseline, constraints, **kw)

    services = make_services({"optimizer": Spy()})
    big = replace(request_ok, optimizer_config=replace(request_ok.optimizer_config, max_evaluations=9000))
    c = AnalysisContext(services, big, analysis.baseline, None, None)
    r = run(c, "optimize_strategies", {})
    assert seen["max"] == CHAT_MAX_EVALUATIONS == r.data["max_evaluations_applied"]
    direct = services.optimizer.optimize(analysis.baseline, big.constraints, assumptions=services.assumptions,
                                          config=replace(big.optimizer_config, max_evaluations=CHAT_MAX_EVALUATIONS),
                                          simulator=services.simulator.simulate)
    rec = services.optimizer.recommend(direct)
    assert r.data["recommended"]["strategy_id"] == rec.strategy_id
    assert r.data["pareto_count"] == len(direct.pareto)


def test_infeasible_optimization_is_a_valid_result(ctx):
    r = run(ctx, "optimize_strategies", {"budget_gbp": 0.0})
    assert r.status == "ok" and r.data["status"] == "infeasible" and r.data["recommended"] is None


def test_infeasible_optimization_says_how_each_goal_could_be_met(ctx):
    r = run(ctx, "optimize_strategies", {"budget_gbp": 0.0})
    hints = r.data["how_to_meet_goals"]
    assert set(hints) == {"budget_gbp_needed", "highest_profit_floor_possible", "deepest_cut_within_budget_and_floor",
                          "deepest_cut_tried", "note"}
    assert hints["budget_gbp_needed"] is None or hints["budget_gbp_needed"] > 0
    assert run(ctx, "optimize_strategies", {}).data.get("how_to_meet_goals") is None  # feasible: nothing to fix


def test_invalid_optimize_target_for_zero_baseline_is_validation_error(mock_services, request_ok, analysis):
    zero = analysis.baseline.monthly.assign(scope1_tco2e=0.0, scope2_tco2e=0.0, scope3_tco2e=0.0, total_co2e_tco2e=0.0)
    b = replace(analysis.baseline, monthly=zero, totals={**analysis.baseline.totals, "total_co2e_tco2e": 0.0})
    c = AnalysisContext(mock_services, request_ok, b, None, None)
    r = run(c, "optimize_strategies", {"min_co2_reduction_ratio": 0.3})
    assert r.status == "error" and "undefined" in r.error


# ---------------------------------- others ---------------------------------- #


def test_get_baseline_reports_serialized_totals(ctx):
    r = run(ctx, "get_baseline", {})
    assert r.data["totals"] == {"revenue_gbp": 12e6, "operating_profit_gbp": 1.2e6, "total_co2e_tco2e": 1200.0}
    assert r.data["period"] == "Jan 2027 - Dec 2027" and r.data["is_mock"] is True


def test_get_baseline_says_which_model_forecasts_and_how_well(ctx):
    forecast = run(ctx, "get_baseline", {}).data["forecast"]
    assert forecast["model"] == "fixture-illustrative"
    emissions = forecast["accuracy_last_12_months"]["emissions"]
    # From the fixture backtest: MAE 1.545 vs 0.850 for repeating last year's month.
    assert emissions == {"average_monthly_miss": 1.5, "simple_repeat_miss": 0.8, "better_than_simple_repeat": False}
    assert "data_notes" in forecast


def test_forecast_drivers_rank_inputs_with_plain_names(ctx):
    r = run(ctx, "get_forecast_drivers", {"top_k": 2})
    assert r.status == "ok" and set(r.data["targets"]) == {"emissions", "operating_profit"}
    top = r.data["targets"]["emissions"]
    assert len(top["top_inputs"]) == 2 and top["top_inputs"][0]["share_pct"] >= top["top_inputs"][1]["share_pct"]
    assert {"input", "share_pct", "pushes_forecast"} <= set(top["top_inputs"][0])
    assert 0 < top["top_k_share_pct"] <= 100


def test_forecast_drivers_unavailable_without_shap(request_ok, analysis):
    services = make_services({"shap": "disabled"})
    c = AnalysisContext(services, request_ok, analysis.baseline, None, None)
    assert run(c, "get_forecast_drivers", {}).status == "unavailable"


def test_risk_unavailable_when_no_provider(request_ok, analysis):
    services = make_services({"risk": "disabled"})
    c = AnalysisContext(services, request_ok, analysis.baseline, analysis, None)
    r = run(c, "get_risk_summary", {})
    assert r.status == "unavailable" and "disabled by configuration" in r.error


def test_risk_requires_a_known_strategy_and_bounds_trials(ctx, mock_services):
    r = run(ctx, "get_risk_summary", {"strategy_id": "strategy-unknown"})
    assert r.status == "error" and "not part of the current analysis" in r.error
    fixture = make_services({"simulator": "fixture", "optimizer": "fixture"})
    req = replace(ctx.request, risk_config=replace(ctx.request.risk_config, n_simulations=5000))
    a = run_analysis(req, services=fixture)
    c = AnalysisContext(fixture, req, a.baseline, a, a.optimization.strategies["strategy-8be15857fffc57f6"])
    r = run(c, "get_risk_summary", {})
    assert r.status == "ok" and r.data["summary"]["target_probability"] == 0.96 and r.data["is_mock"] is True


def test_risk_mock_limits_surface_as_error_not_invented_numbers(ctx):
    r = run(ctx, "get_risk_summary", {})  # behavioral frontier is outside the fixture risk coverage
    assert r.status == "error" and r.data is None and "UnsupportedMockInput" in r.error
