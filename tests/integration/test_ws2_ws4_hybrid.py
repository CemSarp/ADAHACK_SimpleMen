"""WS2 x WS4 hybrid integration: fixture forecast + real WS2 simulator/optimizer/recommendation.

Exercises the documented preset end to end through WS4's services, pipeline and dashboard
state. Search runs are seeded with an explicit evaluation budget; nothing here asserts a
global optimum.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from src.actions.engine import compute_action_breakdown, simulate_strategy
from src.contracts import validation as val
from src.contracts.errors import ProviderConfigurationError
from src.contracts.identity import config_from_row
from src.contracts.types import ActionConfig, AnalysisRequest, ConstraintConfig, OptimizerConfig
from src.dashboard.presentation import resulting_share
from src.dashboard.state import INFEASIBLE, INITIAL, READY, DashboardState, slider_key
from src.integration import real_providers, run_analysis
from src.integration.services import DEFAULT_HYBRID_PRESET, create_services, preset_overrides
from src.optimization.constraints import evaluate_constraints
from tests.mocks import fixtures

SEARCH = OptimizerConfig(seed=42, population_size=32, generations=8, max_evaluations=256)


class CountingRealSimulator(real_providers.RealSimulatorProvider):
    """The real WS2 provider, counting calls so tests can prove which simulator ran."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def simulate(self, baseline, config, *, assumptions):
        self.calls += 1
        return super().simulate(baseline, config, assumptions=assumptions)


@pytest.fixture(scope="module")
def hybrid():
    return create_services(mode="hybrid", provider_overrides=preset_overrides(DEFAULT_HYBRID_PRESET))


@pytest.fixture(scope="module")
def request_demo() -> AnalysisRequest:
    """Documented feasible demonstration request: fixture constraints, seeded explicit budget."""
    return AnalysisRequest(company_id="demo-company", horizon_months=12, constraints=fixtures.constraints(),
                           optimizer_config=SEARCH)


@pytest.fixture(scope="module")
def bundle(hybrid, request_demo):
    return run_analysis(request_demo, services=hybrid)


# 1-2 ----------------------------------------------------------------------------------


def test_canonical_fixture_baseline_is_accepted_by_real_ws2(hybrid):
    baseline = hybrid.forecast.get_baseline(company_id="demo-company", horizon_months=12)
    result = val.validate_simulation_result(hybrid.simulate(baseline, fixtures.action_config()), baseline)
    assert result.strategy_id == fixtures.simulation("nonzero").strategy_id
    assert result.metrics["total_co2e_tco2e"] == pytest.approx(843.744, rel=1e-12)


def test_noop_preserves_baseline_and_costs_nothing(hybrid):
    baseline = hybrid.forecast.get_baseline(company_id="demo-company", horizon_months=12)
    noop = hybrid.simulate(baseline, ActionConfig.noop())
    for column in ("operating_profit_gbp", "scope1_tco2e", "scope2_tco2e", "scope3_tco2e", "total_co2e_tco2e"):
        assert np.array_equal(noop.monthly[column].to_numpy(), baseline.monthly[column].to_numpy()), column
    for column in ("capex_gbp", "incremental_opex_gbp", "operating_savings_gbp", "depreciation_gbp", "budget_cost_gbp"):
        assert (noop.monthly[column] == 0.0).all(), column
    assert noop.metrics["total_profit_gbp"] == baseline.totals["operating_profit_gbp"]
    assert noop.metrics["total_co2e_tco2e"] == baseline.totals["total_co2e_tco2e"]


# 3-6 ----------------------------------------------------------------------------------


def test_real_optimizer_uses_the_bound_real_simulator(request_demo):
    simulator = CountingRealSimulator()
    services = create_services(mode="hybrid", provider_overrides={**preset_overrides(DEFAULT_HYBRID_PRESET),
                                                                  "simulator": simulator})
    result = run_analysis(request_demo, services=services)
    diagnostics = result.optimization.diagnostics
    assert simulator.calls == diagnostics["unique_count"] + diagnostics["revalidated_pareto_count"]
    assert diagnostics["simulator_providers"] == ["action-engine"]
    assert diagnostics["solver"] == "pymoo.NSGA2" and diagnostics["evaluated_count"] <= SEARCH.max_evaluations
    assert {s.provenance.provider for s in result.optimization.strategies.values()} == {"action-engine"}


def test_returned_strategies_satisfy_shared_accounting_and_constraints(bundle, request_demo):
    opt = bundle.optimization
    assert opt.status == "ok" and len(opt.pareto) > 0
    c = request_demo.constraints
    for sid in opt.pareto["strategy_id"]:
        stored = val.validate_simulation_result(opt.strategies[sid], bundle.baseline)
        m, frame = stored.metrics, stored.monthly
        assert evaluate_constraints(stored, c).feasible
        assert m["total_cost_gbp"] <= c.budget_gbp + 0.01
        assert m["total_profit_gbp"] >= c.min_total_profit_gbp - 0.01
        assert m["co2_reduction_ratio"] >= c.min_co2_reduction_ratio - 1e-8
        # Budget is gross outlay; profit carries depreciation, not capex; cash carries capex.
        assert m["total_cost_gbp"] == pytest.approx(m["total_capex_gbp"] + m["total_incremental_opex_gbp"], abs=0.01)
        assert m["total_profit_gbp"] == pytest.approx(
            m["baseline_total_profit_gbp"] + m["total_operating_savings_gbp"] - m["total_incremental_opex_gbp"]
            - math.fsum(frame["depreciation_gbp"]), abs=0.01)
        assert m["net_cash_impact_gbp"] == pytest.approx(
            m["total_operating_savings_gbp"] - m["total_incremental_opex_gbp"] - m["total_capex_gbp"], abs=0.01)
        assert (frame["capex_gbp"].to_numpy()[1:] == 0.0).all()


def test_pareto_rows_join_to_stored_strategy_objects(bundle):
    opt = bundle.optimization
    for _, row in opt.pareto.iterrows():
        stored = opt.strategies[row["strategy_id"]]
        assert stored.strategy_id == row["strategy_id"]
        assert config_from_row(row) == stored.config  # exact, unrounded
        assert row["total_co2e_tco2e"] == stored.metrics["total_co2e_tco2e"]
        assert row["total_profit_gbp"] == stored.metrics["total_profit_gbp"]
        assert row["total_cost_gbp"] == stored.metrics["total_cost_gbp"]
    assert bundle.recommendation.strategy_id in set(opt.pareto["strategy_id"])


def test_direct_simulation_of_selected_config_matches_stored_result(bundle, hybrid):
    stored = bundle.optimization.strategies[bundle.recommendation.strategy_id]
    direct = simulate_strategy(bundle.baseline, stored.config, assumptions=hybrid.assumptions)
    assert direct.strategy_id == stored.strategy_id and direct.metrics == stored.metrics
    assert direct.monthly.equals(stored.monthly)


# 7-9: dashboard state ----------------------------------------------------------------------


@pytest.fixture
def state(hybrid, request_demo):
    s = DashboardState({})
    s.sync_services(hybrid)
    s.ensure_baseline(request_demo, hybrid)
    return s


def test_dashboard_whatif_matches_direct_real_simulation(state, hybrid, request_demo):
    state.run_optimize(request_demo, hybrid)
    assert state.status == READY
    selected = state.selected_strategy()
    assert selected.strategy_id == state.analysis.recommendation.strategy_id
    state.load_whatif(selected.config)
    assert state.store[slider_key("renewable_energy")] == selected.config.renewable_energy  # exact, not rounded
    whatif = state.ensure_whatif(hybrid)
    direct = simulate_strategy(state.baseline, selected.config, assumptions=hybrid.assumptions)
    assert whatif.strategy_id == selected.strategy_id == direct.strategy_id
    assert whatif.metrics == selected.metrics == direct.metrics
    check = state.whatif_constraint_check(hybrid, request_demo)
    assert check.feasible and check.satisfied == {"budget": True, "profit": True, "target": True}
    # A slider change recomputes through the real simulator and keeps the other exact values.
    state.set_whatif_action("ev_adoption", 0.0)
    moved = state.ensure_whatif(hybrid)
    assert moved.provenance.provider == "action-engine"
    assert moved.config == replace(selected.config, ev_adoption=0.0)
    assert moved.metrics == simulate_strategy(state.baseline, moved.config, assumptions=hybrid.assumptions).metrics


@pytest.mark.parametrize(
    "change",
    [
        {"budget_gbp": 400_000.0},
        {"min_co2_reduction_ratio": 0.3},
        {"min_total_profit_gbp": 900_000.0},
    ],
)
def test_budget_target_and_profit_changes_invalidate_results(state, hybrid, request_demo, change):
    state.run_optimize(request_demo, hybrid)
    assert state.analysis is not None and state.selected_strategy_id is not None
    changed = replace(request_demo, constraints=replace(request_demo.constraints, **change))
    state.sync_inputs(changed, hybrid)
    assert state.analysis is None and state.selected_strategy_id is None
    assert state.status == INITIAL and state.invalidated
    state.run_optimize(changed, hybrid)
    assert state.analysis.optimization.constraints == changed.constraints  # optimize consumes current inputs


def test_infeasible_result_has_no_recommendation_or_selection(state, hybrid, request_demo):
    impossible = replace(request_demo, constraints=ConstraintConfig(budget_gbp=0.0, min_total_profit_gbp=1_000_000.0,
                                                                    min_co2_reduction_ratio=0.2))
    state.run_optimize(impossible, hybrid)
    assert state.status == INFEASIBLE
    assert len(state.analysis.optimization.pareto) == 0
    assert state.analysis.recommendation.strategy_id is None and state.selected_strategy() is None
    assert "not a proof" in state.analysis.optimization.diagnostics["warning"]


# 10-12: provenance, real mode, optional capabilities --------------------------------------


def test_hybrid_provenance_names_every_provider(hybrid, bundle):
    assert hybrid.provenance_summary() == (
        "Baseline: fixture · Simulator: WS2 · Optimizer: WS2 · Risk: WS3 · SHAP: unavailable · "
        "Benchmark: WS3"
    )
    kinds = {slot: (info.kind, info.is_mock) for slot, info in bundle.providers.items()}
    assert kinds == {"forecast": ("fixture", True), "simulator": ("real", False), "optimizer": ("real", False)}
    # One fixture input means the analysis as a whole is never labelled real.
    assert bundle.provenance.is_mock and bundle.optimization.provenance.is_mock
    assert bundle.recommendation.provenance.is_mock


def test_real_mode_fails_explicitly_while_ws1_is_missing():
    with pytest.raises(ProviderConfigurationError) as exc:
        create_services(mode="real")
    assert exc.value.missing == ("forecast",)
    assert "src.forecasting.provider is not implemented yet" in str(exc.value)


def test_ws3_optional_capabilities_do_not_break_startup_or_analysis(hybrid, request_demo):
    assert hybrid.risk is not None and hybrid.shap is None and hybrid.benchmark is not None
    caps = hybrid.capabilities
    assert caps.risk_available and caps.benchmark_available and caps.shap_available_targets == ()
    assert hybrid.unavailable["shap"] == "disabled by configuration"
    request = replace(request_demo, risk_enabled=True, benchmark_enabled=True, explanation_enabled=True)
    result = run_analysis(request, services=hybrid)
    assert result.optimization.status == "ok"
    assert result.risk_results
    assert result.benchmark.status == "ok" and result.benchmark.is_synthetic
    assert result.recommendation.risk_status == "evaluated"  # evaluated, but not used by the deterministic policy
    assert result.recommendation.policy == "risk_balanced"
    assert not any("Risk is unavailable" in w or "Benchmark is unavailable" in w for w in result.warnings)


def test_dashboard_resulting_share_matches_ws2_engine(hybrid):
    baseline = hybrid.forecast.get_baseline(company_id="demo-company", horizon_months=12)
    for action, column in (("renewable_energy", "renewable_energy_share"), ("ev_adoption", "ev_share")):
        for x in (0.0, 0.37, 1.0):
            config = replace(ActionConfig.noop(), **{action: x})
            engine = compute_action_breakdown(baseline, config, assumptions=hybrid.assumptions)[column]
            share = resulting_share(baseline, action, x, hybrid.assumptions)
            assert share.resulting_min == pytest.approx(engine.min(), abs=1e-12)
            assert share.resulting_max == pytest.approx(engine.max(), abs=1e-12)
