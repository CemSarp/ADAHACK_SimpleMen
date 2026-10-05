"""End-to-end pipeline behaviour against mocks: provenance, infeasible/empty
results, typed failures and optional-capability isolation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.contracts import serialization as ser
from src.contracts import validation as val
from src.contracts.errors import (
    ContractValidationError,
    ForecastError,
    RiskError,
    SimulationError,
    UnsupportedHorizon,
    UnsupportedMockInput,
)
from src.contracts.identity import config_from_row
from src.contracts.types import AnalysisBundle, ConstraintConfig
from src.integration import run_analysis
from src.integration.pipeline import rerun_recommendation
from src.optimization.recommendation import risk_pool_from_frontier
from tests.mocks import fixtures, make_services
from tests.mocks.behavioral import BehavioralMockSimulator
from tests.mocks.fixture_providers import (
    FixtureBenchmarkProvider,
    FixtureExplanationProvider,
    FixtureForecastProvider,
    FixtureRiskProvider,
)


def test_mock_run_is_valid_serializable_and_labelled(mock_services, request_ok):
    bundle = run_analysis(request_ok, services=mock_services)
    assert bundle.optimization.status == "ok"
    val.validate_recommendation(bundle.recommendation, bundle.optimization)
    assert bundle.provenance.is_mock is True
    assert bundle.provenance.provider == "pipeline"
    assert {s: i.kind for s, i in bundle.providers.items()} == {
        "forecast": "fixture", "simulator": "behavioral-mock", "optimizer": "behavioral-mock"}
    assert bundle.baseline.provenance.is_mock and bundle.backtest.provenance.is_mock
    assert all(s.provenance.is_mock for s in bundle.optimization.strategies.values())
    again = ser.from_json(AnalysisBundle, ser.to_json(bundle))
    assert ser.to_dict(again) == ser.to_dict(bundle)
    assert again.providers == bundle.providers


def test_run_is_deterministic_for_same_inputs(mock_services, request_ok):
    a = run_analysis(request_ok, services=mock_services)
    b = run_analysis(request_ok, services=mock_services)
    assert a.optimization.pareto.equals(b.optimization.pareto)
    assert a.recommendation.strategy_id == b.recommendation.strategy_id


def test_every_stored_point_equals_canonical_simulation(mock_services, request_ok):
    bundle = run_analysis(request_ok, services=mock_services)
    for _, row in bundle.optimization.pareto.iterrows():
        direct = mock_services.simulate(bundle.baseline, config_from_row(row))
        stored = bundle.optimization.strategies[row["strategy_id"]]
        assert direct.strategy_id == stored.strategy_id
        assert direct.metrics == stored.metrics
        assert mock_services.optimizer.evaluate_constraints(stored, request_ok.constraints).feasible


def test_noop_is_evaluated_and_exact(mock_services, request_ok):
    bundle = run_analysis(request_ok, services=mock_services)
    noop_id = bundle.optimization.diagnostics["tested_noop_strategy_id"]
    noop = bundle.optimization.strategies[noop_id]
    assert noop.metrics["total_co2e_tco2e"] == bundle.baseline.totals["total_co2e_tco2e"]
    assert noop.metrics["total_profit_gbp"] == bundle.baseline.totals["operating_profit_gbp"]
    assert noop.metrics["total_cost_gbp"] == 0.0


def test_impossible_request_gives_empty_frontier_and_no_recommendation(mock_services, request_infeasible):
    bundle = run_analysis(request_infeasible, services=mock_services)
    assert bundle.optimization.status == "infeasible"
    assert len(bundle.optimization.pareto) == 0
    assert bundle.recommendation.strategy_id is None and bundle.recommendation.score is None
    assert len(bundle.optimization.candidates) > 0  # audit trail retained
    assert "minimum_normalized_violations" in bundle.optimization.diagnostics


def test_fixture_mode_reproduces_fixture_payloads(fixture_services, request_ok, request_infeasible):
    ok = run_analysis(request_ok, services=fixture_services)
    assert ok.recommendation.strategy_id == "strategy-8be15857fffc57f6"
    infeasible = run_analysis(request_infeasible, services=fixture_services)
    assert infeasible.optimization.status == "infeasible" and infeasible.recommendation.strategy_id is None


def test_fixture_stubs_refuse_uncovered_inputs(fixture_services, request_ok):
    baseline = fixtures.baseline()
    with pytest.raises(UnsupportedMockInput):
        fixture_services.simulate(baseline, replace(fixtures.action_config(), ev_adoption=0.41))
    with pytest.raises(UnsupportedMockInput):
        run_analysis(replace(request_ok, constraints=ConstraintConfig(400_000.0, 1e6, 0.2)), services=fixture_services)


def test_unsupported_horizon_rejected_before_computation(request_ok):
    class Spy(FixtureForecastProvider):
        called = False

        def get_baseline(self, **kwargs):
            Spy.called = True
            return super().get_baseline(**kwargs)

    services = make_services({"forecast": Spy()})
    for horizon in (36, 60):
        with pytest.raises(UnsupportedHorizon):
            run_analysis(replace(request_ok, horizon_months=horizon), services=services)
    assert Spy.called is False


def test_zero_baseline_co2_with_target_is_validation_error(request_ok):
    class ZeroForecast(FixtureForecastProvider):
        def get_baseline(self, **kwargs):
            b = super().get_baseline(**kwargs)
            m = b.monthly.assign(scope1_tco2e=0.0, scope2_tco2e=0.0, scope3_tco2e=0.0, total_co2e_tco2e=0.0)
            return replace(b, monthly=m, totals={**b.totals, "total_co2e_tco2e": 0.0})

    services = make_services({"forecast": ZeroForecast()})
    with pytest.raises(ContractValidationError, match="undefined"):
        run_analysis(request_ok, services=services)


def test_p0_provider_failures_propagate_typed(request_ok):
    class BrokenForecast(FixtureForecastProvider):
        def get_baseline(self, **kwargs):
            raise ForecastError("prediction failed")

    class BrokenSimulator(BehavioralMockSimulator):
        def simulate(self, *args, **kwargs):
            raise SimulationError("engine failed")

    with pytest.raises(ForecastError):
        run_analysis(request_ok, services=make_services({"forecast": BrokenForecast()}))
    with pytest.raises(SimulationError):
        run_analysis(request_ok, services=make_services({"simulator": BrokenSimulator()}))


def test_malformed_provider_output_is_rejected(request_ok):
    class BadForecast(FixtureForecastProvider):
        def get_baseline(self, **kwargs):
            b = super().get_baseline(**kwargs)
            return replace(b, monthly=b.monthly.assign(renewable_energy_share=20.0))

    with pytest.raises(ContractValidationError, match="renewable_energy_share"):
        run_analysis(request_ok, services=make_services({"forecast": BadForecast()}))


def test_optional_capabilities_produce_results_or_warnings(mock_services, request_ok):
    bundle = run_analysis(replace(request_ok, risk_enabled=True, explanation_enabled=True, benchmark_enabled=True),
                          services=mock_services)
    assert bundle.explanation is not None and bundle.benchmark.status == "ok"
    # Fixture risk covers one config only, so the behavioral frontier gets no risk;
    # the recommendation must say risk is unavailable, never claim a risk-aware pick.
    assert bundle.risk_results == {}
    assert bundle.recommendation.risk_status == "unavailable"
    assert any("Risk evaluated for 0" in w for w in bundle.warnings)


def test_optional_failures_never_break_p0(request_ok):
    class FailingRisk(FixtureRiskProvider):
        def evaluate(self, *args, **kwargs):
            raise RiskError("trial budget exceeded")

    class FailingShap(FixtureExplanationProvider):
        def explain(self, baseline):
            raise ForecastError("no tree model")

    services = make_services({"risk": FailingRisk(), "shap": FailingShap(),
                                                                 "benchmark": "disabled"})
    bundle = run_analysis(replace(request_ok, risk_enabled=True, explanation_enabled=True, benchmark_enabled=True),
                          services=services)
    assert bundle.optimization.status == "ok" and bundle.recommendation.strategy_id
    assert bundle.risk_results == {} and bundle.explanation is None and bundle.benchmark is None
    text = " ".join(bundle.warnings)
    assert "trial budget exceeded" in text and "no tree model" in text and "Benchmark is unavailable" in text
    assert "risk" not in bundle.providers and "shap" not in bundle.providers


def test_risk_results_flow_to_recommendation_when_available(fixture_services, request_ok):
    bundle = run_analysis(replace(request_ok, risk_enabled=True), services=fixture_services)
    assert set(bundle.risk_results) == {"strategy-8be15857fffc57f6"}
    assert bundle.providers["risk"].is_mock
    rerun = rerun_recommendation(bundle, "conservative", services=fixture_services)
    assert rerun.recommendation.tolerance == "conservative" and rerun.risk_results is bundle.risk_results


def test_benchmark_unavailable_is_a_valid_result(request_ok):
    class NoPeers(FixtureBenchmarkProvider):
        def benchmark(self, baseline):
            return replace(super().benchmark(baseline), status="unavailable", reason="fewer than 10 compatible peers",
                           percentile=None, better_than_pct=None)

    services = make_services({"benchmark": NoPeers()})
    bundle = run_analysis(replace(request_ok, benchmark_enabled=True), services=services)
    assert bundle.benchmark.status == "unavailable" and bundle.optimization.status == "ok"


def test_risk_pool_keeps_endpoints_and_bounds_size(mock_services, request_ok):
    pareto = run_analysis(request_ok, services=mock_services).optimization.pareto
    pool = risk_pool_from_frontier(pareto, max_size=5)
    ordered = pareto.sort_values(["total_co2e_tco2e", "strategy_id"])["strategy_id"].tolist()
    assert len(pool) == min(5, len(ordered))
    assert pool[0] == ordered[0] and pool[-1] == ordered[-1]
