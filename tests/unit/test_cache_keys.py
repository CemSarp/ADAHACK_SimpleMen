from __future__ import annotations

from dataclasses import replace

from src.contracts.types import OptimizerConfig, RiskConfig
from src.integration import cache_keys
from tests.mocks import fixtures, make_services
from tests.mocks.behavioral import BehavioralMockSimulator


def test_analysis_key_covers_every_outcome_input(request_ok, mock_services):
    base = cache_keys.analysis_key(request_ok, mock_services)
    variants = [
        replace(request_ok, constraints=replace(request_ok.constraints, budget_gbp=500_000.01)),
        replace(request_ok, constraints=replace(request_ok.constraints, min_total_profit_gbp=999_999.0)),
        replace(request_ok, constraints=replace(request_ok.constraints, min_co2_reduction_ratio=0.2000001)),
        replace(request_ok, horizon_months=36),
        replace(request_ok, company_id="other"),
        replace(request_ok, optimizer_config=OptimizerConfig(seed=8, max_evaluations=96)),
        replace(request_ok, optimizer_config=OptimizerConfig(seed=7, max_evaluations=97)),
        replace(request_ok, risk_enabled=True),
        replace(request_ok, explanation_enabled=True),
        replace(request_ok, benchmark_enabled=True),
    ]
    keys = {cache_keys.analysis_key(v, mock_services) for v in variants}
    assert base not in keys and len(keys) == len(variants)


def test_risk_seed_and_trials_change_key_only_when_risk_enabled(request_ok, mock_services):
    on = replace(request_ok, risk_enabled=True)
    assert cache_keys.analysis_key(on, mock_services) != cache_keys.analysis_key(
        replace(on, risk_config=RiskConfig(seed=1)), mock_services)
    assert cache_keys.analysis_key(on, mock_services) != cache_keys.analysis_key(
        replace(on, risk_config=RiskConfig(n_simulations=2000)), mock_services)
    assert cache_keys.analysis_key(request_ok, mock_services) == cache_keys.analysis_key(
        replace(request_ok, risk_config=RiskConfig(seed=1)), mock_services)


def test_tolerance_only_changes_recommendation_key(request_ok, mock_services):
    other = replace(request_ok, tolerance="aggressive")
    assert cache_keys.analysis_key(request_ok, mock_services) == cache_keys.analysis_key(other, mock_services)
    assert cache_keys.recommendation_key(request_ok, mock_services) != cache_keys.recommendation_key(other, mock_services)


def test_provider_identity_and_assumptions_are_part_of_keys(request_ok, mock_services):
    fixture_sim = make_services({"simulator": "fixture"})
    assert cache_keys.analysis_key(request_ok, mock_services) != cache_keys.analysis_key(request_ok, fixture_sim)
    a = fixtures.assumptions()
    alt = make_services({"simulator": BehavioralMockSimulator(replace(a, version="1.0.1"))})
    assert cache_keys.analysis_key(request_ok, mock_services) != cache_keys.analysis_key(request_ok, alt)
    assert cache_keys.services_key(mock_services) != cache_keys.services_key(alt)


def test_simulation_key_uses_full_precision_config(mock_services):
    b = fixtures.baseline()
    c = fixtures.action_config()
    assert cache_keys.simulation_key(b, c, mock_services) != cache_keys.simulation_key(
        b, replace(c, travel_reduction=0.3 + 1e-15), mock_services)
    assert cache_keys.simulation_key(b, c, mock_services) == cache_keys.simulation_key(b, replace(c), mock_services)
