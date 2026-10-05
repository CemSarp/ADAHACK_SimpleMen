"""Session state, cache invalidation, exact selection and manual what-if parity."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.contracts.errors import ForecastError, OptimizationError
from src.contracts.types import ACTION_NAMES, ActionConfig, ConstraintConfig, OptimizerConfig
from src.dashboard.state import (
    INFEASIBLE,
    INITIAL,
    PROVIDER_ERROR,
    READY,
    VALIDATION_ERROR,
    DashboardState,
    slider_key,
)
from tests.mocks import make_services
from tests.mocks.behavioral import BehavioralMockOptimizer, BehavioralMockSimulator
from tests.mocks.fixture_providers import FixtureForecastProvider


class CountingOptimizer(BehavioralMockOptimizer):
    def __init__(self) -> None:
        super().__init__()
        self.optimize_calls = 0
        self.recommend_calls = 0

    def optimize(self, *args, **kwargs):
        self.optimize_calls += 1
        return super().optimize(*args, **kwargs)

    def recommend(self, *args, **kwargs):
        self.recommend_calls += 1
        return super().recommend(*args, **kwargs)


class CountingSimulator(BehavioralMockSimulator):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def simulate(self, *args, **kwargs):
        self.calls += 1
        return super().simulate(*args, **kwargs)


class CountingForecast(FixtureForecastProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def get_baseline(self, **kwargs):
        self.calls += 1
        return super().get_baseline(**kwargs)


@pytest.fixture
def spies():
    return CountingForecast(), CountingSimulator(), CountingOptimizer()


@pytest.fixture
def services(spies):
    forecast, simulator, optimizer = spies
    return make_services({"forecast": forecast, "simulator": simulator, "optimizer": optimizer})


@pytest.fixture
def state(services, request_ok):
    st = DashboardState({})
    st.sync_services(services)
    st.ensure_baseline(request_ok, services)
    return st


def test_initial_state_has_no_results(state):
    assert state.status == INITIAL and state.analysis is None and state.selected_strategy_id is None
    assert state.baseline is not None and state.whatif_config == ActionConfig.noop()


def test_optimize_stores_ready_result_and_selects_recommendation(state, services, request_ok):
    state.run_optimize(request_ok, services)
    assert state.status == READY
    assert state.selected_strategy_id == state.analysis.recommendation.strategy_id


@pytest.mark.parametrize(
    "change",
    [
        lambda r: replace(r, constraints=replace(r.constraints, budget_gbp=r.constraints.budget_gbp + 1.0)),
        lambda r: replace(r, constraints=replace(r.constraints, min_total_profit_gbp=900_000.0)),
        lambda r: replace(r, constraints=replace(r.constraints, min_co2_reduction_ratio=0.25)),
        lambda r: replace(r, optimizer_config=OptimizerConfig(seed=8, max_evaluations=96)),
        lambda r: replace(r, risk_enabled=True),
        lambda r: replace(r, benchmark_enabled=True),
    ],
    ids=["budget", "profit-floor", "target", "seed", "risk-flag", "benchmark-flag"],
)
def test_outcome_inputs_invalidate_analysis_and_selection(state, services, request_ok, change):
    state.run_optimize(request_ok, services)
    state.sync_inputs(change(request_ok), services)
    assert state.analysis is None
    assert state.selected_strategy_id is None
    assert state.status == INITIAL and state.invalidated


def test_unchanged_inputs_keep_result(state, services, request_ok):
    state.run_optimize(request_ok, services)
    bundle = state.analysis
    state.sync_inputs(replace(request_ok), services)
    assert state.analysis is bundle and not state.invalidated


def test_budget_change_never_reuses_other_budget_result(state, services, request_ok, spies):
    _, _, optimizer = spies
    state.run_optimize(request_ok, services)
    other = replace(request_ok, constraints=replace(request_ok.constraints, budget_gbp=250_000.0))
    state.sync_inputs(other, services)
    state.run_optimize(other, services)
    assert optimizer.optimize_calls == 2
    assert state.analysis.optimization.constraints.budget_gbp == 250_000.0


def test_tolerance_change_reruns_only_recommendation(state, services, request_ok, spies):
    _, _, optimizer = spies
    state.run_optimize(request_ok, services)
    before = optimizer.optimize_calls, optimizer.recommend_calls
    state.sync_inputs(replace(request_ok, tolerance="conservative"), services)
    assert optimizer.optimize_calls == before[0]
    assert optimizer.recommend_calls == before[1] + 1
    assert state.analysis.recommendation.tolerance == "conservative"


def test_horizon_or_provider_change_resets_baseline_and_whatif(state, services, request_ok):
    state.run_optimize(request_ok, services)
    state.load_whatif(state.selected_strategy().config)
    state.ensure_whatif(services)
    assert state.sync_services(services) is False  # same provider identities: keep everything
    other_services = make_services({"simulator": "fixture"})
    assert state.sync_services(other_services) is True
    assert state.baseline is None and state.analysis is None and state.whatif_result is None
    assert state.whatif_config == ActionConfig.noop()
    assert all(state.store[slider_key(n)] == 0.0 for n in ACTION_NAMES)


def test_selection_uses_exact_stored_strategy(state, services, request_ok):
    state.run_optimize(request_ok, services)
    pareto = state.analysis.optimization.pareto
    unrounded = [
        sid for sid, row in pareto.set_index("strategy_id").iterrows()
        if any(float(row[n]) != round(float(row[n]), 2) for n in ACTION_NAMES)
    ]
    assert unrounded, "expected full-precision configs on the frontier"
    sid = unrounded[-1]
    selected = state.select_strategy(sid)
    assert selected is state.analysis.optimization.strategies[sid]
    row = pareto.set_index("strategy_id").loc[sid]
    assert all(float(row[n]) == getattr(selected.config, n) for n in ACTION_NAMES)
    assert state.selected_strategy() is selected


def test_selection_rejects_infeasible_or_unknown_ids(state, services, request_ok):
    state.run_optimize(request_ok, services)
    cand = state.analysis.optimization.candidates
    infeasible = cand.loc[~cand["feasible"], "strategy_id"].iloc[0]
    with pytest.raises(KeyError):
        state.select_strategy(infeasible)
    with pytest.raises(KeyError):
        state.select_strategy("strategy-does-not-exist")


def test_whatif_of_selected_strategy_equals_stored_and_direct_call(state, services, request_ok, spies):
    _, simulator, optimizer = spies
    state.run_optimize(request_ok, services)
    stored = state.selected_strategy()
    optimize_calls = optimizer.optimize_calls
    state.load_whatif(stored.config)
    assert state.store[slider_key("ev_adoption")] == stored.config.ev_adoption  # sliders receive exact values
    whatif = state.ensure_whatif(services)
    direct = services.simulator.simulate(state.baseline, stored.config, assumptions=services.assumptions)
    assert whatif.strategy_id == stored.strategy_id == direct.strategy_id
    assert whatif.metrics == stored.metrics == direct.metrics
    assert whatif.monthly.equals(direct.monthly)
    assert optimizer.optimize_calls == optimize_calls  # what-if never re-optimizes


def test_slider_change_calls_only_simulation_and_keeps_other_exact_values(state, services, request_ok, spies):
    forecast, simulator, optimizer = spies
    state.run_optimize(request_ok, services)
    state.load_whatif(state.selected_strategy().config)
    state.ensure_whatif(services)
    calls = forecast.calls, simulator.calls, optimizer.optimize_calls
    exact = state.whatif_config
    state.set_whatif_action("renewable_energy", 0.33)
    result = state.ensure_whatif(services)
    assert (forecast.calls, simulator.calls, optimizer.optimize_calls) == (calls[0], calls[1] + 1, calls[2])
    assert result.config == replace(exact, renewable_energy=0.33)
    state.ensure_whatif(services)  # same key -> cached, no extra call
    assert simulator.calls == calls[1] + 1
    assert state.analysis is not None  # optimization result untouched


def test_whatif_rejects_out_of_range_slider(state):
    with pytest.raises(Exception):
        state.set_whatif_action("ev_adoption", 1.5)
    assert state.whatif_config == ActionConfig.noop()


def test_infeasible_state_has_no_selection(state, services, request_infeasible):
    state.run_optimize(request_infeasible, services)
    assert state.status == INFEASIBLE
    assert len(state.analysis.optimization.pareto) == 0
    assert state.selected_strategy_id is None and state.selected_strategy() is None


def test_validation_error_state(state, services, request_ok):
    bad = replace(request_ok, constraints=ConstraintConfig(-5.0, 0.0, 0.2))
    state.run_optimize(bad, services)
    assert state.status == VALIDATION_ERROR and state.analysis is None
    assert state.error.error_type == "ContractValidationError"
    # Fixing the input clears the stale error.
    state.sync_inputs(request_ok, services)
    assert state.status == INITIAL and state.error is None


class FailingOptimizer(BehavioralMockOptimizer):
    def optimize(self, *args, **kwargs):
        raise OptimizationError("solver crashed")


class FailingForecast(FixtureForecastProvider):
    def get_baseline(self, **kwargs):
        raise ForecastError("model artifact unreadable")


def test_provider_error_state_is_typed_and_not_replaced(request_ok):
    services = make_services({"optimizer": FailingOptimizer()})
    st = DashboardState({})
    st.sync_services(services)
    st.run_optimize(request_ok, services)
    assert st.status == PROVIDER_ERROR and st.analysis is None
    assert st.error.error_type == "OptimizationError" and "solver crashed" in st.error.message


def test_forecast_failure_surfaces_as_baseline_error(request_ok):
    services = make_services({"forecast": FailingForecast()})
    st = DashboardState({})
    st.sync_services(services)
    assert st.ensure_baseline(request_ok, services) is None
    assert st.baseline_error.error_type == "ForecastError"
    st.run_optimize(request_ok, services)
    assert st.status == PROVIDER_ERROR


def test_unsupported_horizon_is_validation_error(request_ok, services):
    st = DashboardState({})
    st.sync_services(services)
    st.run_optimize(replace(request_ok, horizon_months=36), services)
    assert st.status == VALIDATION_ERROR and st.error.error_type == "UnsupportedHorizon"


def test_transient_forecast_failure_can_retry(request_ok, monkeypatch):
    forecast = CountingForecast()
    original = forecast.get_baseline

    def fail_once(**kwargs):
        if forecast.calls == 0:
            forecast.calls += 1
            raise ForecastError("temporary forecast failure")
        return original(**kwargs)

    monkeypatch.setattr(forecast, "get_baseline", fail_once)
    services = make_services({"forecast": forecast})
    state = DashboardState({})
    state.sync_services(services)
    assert state.ensure_baseline(request_ok, services) is None
    assert state.ensure_baseline(request_ok, services) is not None
    assert state.baseline_error is None
    assert forecast.calls == 2
    state.ensure_baseline(request_ok, services)
    assert forecast.calls == 2
