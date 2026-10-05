from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.contracts import serialization as ser
from src.contracts.errors import ContractValidationError, RiskError, SimulationError
from src.contracts.identity import compute_strategy_id
from src.contracts.types import ACTION_NAMES, ActionConfig, ConstraintConfig, RiskConfig
from src.risk.monte_carlo import (
    EFFECT_FIELDS,
    UncertaintySpec,
    evaluate_strategy_risk,
    load_uncertainty,
    sample_multipliers,
)
from tests.mocks import fixtures, make_services
from tests.mocks.behavioral import BehavioralMockSimulator


def _run(action=None, *, spec=None, config=RiskConfig(seed=7, n_simulations=50), simulator=None, constraints=None):
    return evaluate_strategy_risk(
        fixtures.baseline(),
        action or fixtures.action_config(),
        constraints=constraints or fixtures.constraints(),
        assumptions=fixtures.assumptions(),
        uncertainty=spec or load_uncertainty(),
        config=config,
        simulator=simulator or BehavioralMockSimulator().simulate,
    )


def test_neutral_uncertainty_matches_deterministic_simulation():
    det = BehavioralMockSimulator().simulate(fixtures.baseline(), fixtures.action_config(), assumptions=fixtures.assumptions())
    s = _run(spec=UncertaintySpec.neutral()).summary
    for stat in ("mean", "p05", "p95"):
        assert s[f"co2_{stat}_tco2e"] == pytest.approx(det.metrics["total_co2e_tco2e"], rel=1e-12)
        assert s[f"profit_{stat}_gbp"] == pytest.approx(det.metrics["total_profit_gbp"], rel=1e-12)
    assert s["cost_mean_gbp"] == s["cost_p95_gbp"] == pytest.approx(det.metrics["total_cost_gbp"], rel=1e-12)
    assert s["target_probability_mc_standard_error"] == 0.0


def test_noop_is_unaffected_by_uncertainty():
    b = fixtures.baseline()
    r = _run(ActionConfig.noop())
    s = r.summary
    assert s["co2_p05_tco2e"] == s["co2_p95_tco2e"] == pytest.approx(b.totals["total_co2e_tco2e"])
    assert s["profit_mean_gbp"] == pytest.approx(b.totals["operating_profit_gbp"])
    assert s["cost_mean_gbp"] == s["cost_p95_gbp"] == 0.0
    assert s["target_probability"] == 0.0  # 20% target, zero reduction
    assert s["budget_probability"] == 1.0


def test_inputs_are_not_mutated_and_ids_are_original():
    b, a, x, c = fixtures.baseline(), fixtures.assumptions(), fixtures.action_config(), fixtures.constraints()
    before = (ser.baseline_to_dict(b), ser.assumptions_to_dict(a), x.as_dict(), dict(c.__dict__))
    r = evaluate_strategy_risk(b, x, constraints=c, assumptions=a, uncertainty=load_uncertainty(),
                               config=RiskConfig(seed=1, n_simulations=20), simulator=BehavioralMockSimulator().simulate)
    assert (ser.baseline_to_dict(b), ser.assumptions_to_dict(a), x.as_dict(), dict(c.__dict__)) == before
    assert r.strategy_id == compute_strategy_id(b.baseline_id, x, a.assumptions_id, a.version)
    assert r.provenance.is_mock is True and r.provenance.assumptions_id == a.assumptions_id


def test_sampled_assumptions_map_all_18_channels():
    seen = []
    mock = BehavioralMockSimulator()

    def recording(baseline, config, *, assumptions):
        seen.append(assumptions)
        return mock.simulate(baseline, config, assumptions=assumptions)

    spec, parent = load_uncertainty(), fixtures.assumptions()
    _run(spec=spec, config=RiskConfig(seed=3, n_simulations=10), simulator=recording)
    draws = sample_multipliers(spec, 3, 10)
    assert len({s.assumptions_id for s in seen}) == 10
    for t, sampled in enumerate(seen):
        for i, name in enumerate(ACTION_NAMES):
            eff, capex, opex = draws[t, 3 * i : 3 * i + 3]
            for f in EFFECT_FIELDS[name]:  # includes supplier monthly savings
                assert getattr(sampled, f) == pytest.approx(getattr(parent, f) * eff)
            assert sampled.costs[name].capex_at_full_gbp == pytest.approx(parent.costs[name].capex_at_full_gbp * capex)
            assert sampled.costs[name].monthly_opex_at_full_gbp == pytest.approx(parent.costs[name].monthly_opex_at_full_gbp * opex)
            assert sampled.costs[name].asset_life_months == parent.costs[name].asset_life_months
        assert sampled.grid_tco2e_per_kwh == parent.grid_tco2e_per_kwh
    assert draws.min() >= 0.85 and draws.max() <= 1.1


def test_probabilities_quantiles_and_tolerance_boundaries():
    # co2, profit, cost, reduction ratio  -> target / profit / budget flags
    trials = iter([
        (10.0, 999.99, 100.01, 0.2 - 5e-9),  # T T T (all at raw-tolerance boundary)
        (20.0, 999.98, 50.0, 0.3),           # T F T
        (30.0, 500.0, 0.0, 0.1),             # F F T
        (40.0, 2000.0, 100.02, 0.2 - 1e-6),  # F T F
    ])

    def stub(baseline, config, *, assumptions):
        co2, profit, cost, ratio = next(trials)
        return SimpleNamespace(provenance=SimpleNamespace(is_mock=True), metrics={
            "total_co2e_tco2e": co2, "total_profit_gbp": profit, "total_cost_gbp": cost, "co2_reduction_ratio": ratio})

    s = _run(config=RiskConfig(seed=0, n_simulations=4), simulator=stub,
             constraints=ConstraintConfig(budget_gbp=100.0, min_total_profit_gbp=1000.0, min_co2_reduction_ratio=0.2)).summary
    assert (s["co2_mean_tco2e"], s["co2_p05_tco2e"], s["co2_p95_tco2e"]) == pytest.approx((25.0, 11.5, 38.5))
    assert s["target_probability"] == 0.5
    assert s["profit_floor_probability"] == 0.5
    assert s["budget_probability"] == 0.75
    assert s["joint_feasibility_probability"] == 0.25
    assert s["target_probability_mc_standard_error"] == pytest.approx(0.25)


def test_common_trials_and_retained_samples_do_not_change_summary():
    a = _run(config=RiskConfig(seed=11, n_simulations=30))
    b = _run(config=RiskConfig(seed=11, n_simulations=30, retain_samples=True))
    assert a.summary == b.summary and a.samples is None
    assert len(b.samples) == 30 and b.samples["total_co2e_tco2e"].mean() == pytest.approx(a.summary["co2_mean_tco2e"])
    assert all(math.isfinite(v) for v in a.summary.values())


def test_failed_trial_aborts_with_risk_error():
    def failing(baseline, config, *, assumptions):
        raise SimulationError("boom")

    with pytest.raises(RiskError):
        _run(simulator=failing)


@pytest.mark.parametrize("mutate", [
    lambda d: d["actions"].pop("ev_adoption"),
    lambda d: d.update(distribution="normal"),
    lambda d: d.update(correlation=[[1]]),
    lambda d: d["actions"]["ev_adoption"].update(capex=[1.1, 0.9]),
    lambda d: d["actions"]["ev_adoption"].update(effectiveness=[0.9, 1.2]),
    lambda d: d["actions"]["ev_adoption"].update(fixed_opex=[-0.1, 1.0]),
    lambda d: d["actions"]["ev_adoption"].update(capex=[float("nan"), 1.0]),
])
def test_invalid_uncertainty_rejected(mutate):
    d = load_uncertainty().to_dict()
    mutate(d)
    with pytest.raises(ContractValidationError):
        UncertaintySpec.from_dict(d)


@pytest.mark.parametrize("config", [RiskConfig(seed=-1), RiskConfig(n_simulations=0), RiskConfig(n_simulations=5001),
                                    RiskConfig(n_simulations=True), RiskConfig(n_simulations=10.0)])
def test_invalid_risk_config_rejected(config):
    with pytest.raises(ContractValidationError):
        _run(config=config)


def test_uncertainty_round_trip_and_production_default():
    spec = load_uncertainty()
    assert UncertaintySpec.from_dict(spec.to_dict()) == spec
    assert RiskConfig().n_simulations == 1000
    assert np.all(sample_multipliers(UncertaintySpec.neutral(), 0, 5) == 1.0)


def test_hybrid_discovers_real_risk_provider_and_pipeline_matches_pareto(request_ok, tmp_path):
    from dataclasses import replace

    from src.contracts import validation as val
    from src.contracts.protocols import RiskProvider
    from src.integration import create_services, run_analysis
    from src.integration.cache_keys import services_key
    from src.optimization.recommendation import risk_pool_from_frontier
    from src.risk.provider import create_risk_provider

    services = make_services({"risk": "real"})
    info = services.providers["risk"]
    spec = load_uncertainty()
    assert isinstance(services.risk, RiskProvider) and services.capabilities.risk_available
    assert (info.slot, info.kind, info.is_mock) == ("risk", "real", False)
    assert spec.content_hash()[:16] in info.version and services.risk.uncertainty_id == spec.uncertainty_id

    request = replace(request_ok, risk_enabled=True, risk_config=RiskConfig(seed=5, n_simulations=50))
    bundle = run_analysis(request, services=services)
    pareto_ids = set(bundle.optimization.pareto["strategy_id"])
    assert bundle.risk_results and set(bundle.risk_results) == set(risk_pool_from_frontier(bundle.optimization.pareto))
    assert set(bundle.risk_results) <= pareto_ids
    for sid, r in bundle.risk_results.items():
        val.validate_risk_result(r)
        assert r.strategy_id == sid and r.n_simulations == 50 and r.provenance.is_mock  # mock simulator injected
    assert ser.from_json(type(bundle), ser.to_json(bundle)).risk_results.keys() == bundle.risk_results.keys()

    # Changing the bound uncertainty changes provider version and therefore the cache key.
    (tmp_path / "u.json").write_text(json.dumps(UncertaintySpec.neutral().to_dict()))
    other = create_risk_provider(tmp_path / "u.json")
    assert other.info.version != info.version
    swapped = make_services({"risk": other})
    assert services_key(swapped) != services_key(services)


def _stub(rows):
    """Hand-authored trial metrics: (co2, profit, cost, reduction ratio or None)."""
    it = iter(rows)

    def stub(baseline, config, *, assumptions):
        co2, profit, cost, ratio = next(it)
        return SimpleNamespace(provenance=SimpleNamespace(is_mock=True), metrics={
            "total_co2e_tco2e": co2, "total_profit_gbp": profit, "total_cost_gbp": cost, "co2_reduction_ratio": ratio})

    return stub


def test_single_trial():
    s = _run(config=RiskConfig(seed=9, n_simulations=1)).summary
    assert s["co2_p05_tco2e"] == s["co2_mean_tco2e"] == s["co2_p95_tco2e"]
    assert s["profit_p05_gbp"] == s["profit_mean_gbp"] == s["profit_p95_gbp"]
    assert s["cost_mean_gbp"] == s["cost_p95_gbp"]
    assert s["target_probability"] in (0.0, 1.0) and s["target_probability_mc_standard_error"] == 0.0


def test_zero_co2_target_rules_and_losses():
    zero = ConstraintConfig(budget_gbp=100.0, min_total_profit_gbp=0.0, min_co2_reduction_ratio=0.0)
    # Undefined ratio (zero CO2) with a zero target counts as met; losses are valid outcomes.
    s = _run(config=RiskConfig(seed=0, n_simulations=2), constraints=zero,
             simulator=_stub([(0.0, -500.0, 10.0, None), (0.0, 250.0, 10.0, None)])).summary
    assert s["target_probability"] == 1.0 and s["co2_mean_tco2e"] == 0.0
    assert s["profit_mean_gbp"] == -125.0 and s["profit_p05_gbp"] < 0
    assert s["profit_floor_probability"] == 0.5 and s["joint_feasibility_probability"] == 0.5
    assert all(math.isfinite(v) for v in s.values())
    # Undefined ratio with a positive target is an invalid trial, never a silent pass or fail.
    with pytest.raises(RiskError, match="undefined"):
        _run(config=RiskConfig(seed=0, n_simulations=1), simulator=_stub([(0.0, 1.0, 0.0, None)]))


def test_compared_strategies_share_common_trials():
    seen: dict[str, list] = {"a": [], "b": []}
    mock = BehavioralMockSimulator()

    def recorder(key):
        def sim(baseline, config, *, assumptions):
            seen[key].append(ser.assumptions_to_dict(assumptions))
            return mock.simulate(baseline, config, assumptions=assumptions)
        return sim

    config = RiskConfig(seed=21, n_simulations=15)
    a = _run(fixtures.action_config(), config=config, simulator=recorder("a"))
    b = _run(ActionConfig(*([0.5] * 6)), config=config, simulator=recorder("b"))
    assert a.strategy_id != b.strategy_id
    assert seen["a"] == seen["b"]  # identical sampled assumptions trial by trial, IDs included


def test_saved_mock_simulator_sample_is_reproducible():
    from src.contracts.types import RiskResult
    from src.contracts.validation import validate_risk_result

    path = Path(__file__).resolve().parents[2] / "tests/fixtures/v1/risk_sample_mock_simulator.json"
    saved = validate_risk_result(ser.from_json(RiskResult, path.read_text()))
    assert saved.provenance.is_mock and saved.n_simulations == len(saved.samples) == 1000
    fresh = _run(config=RiskConfig(seed=42, n_simulations=1000, retain_samples=True))
    assert fresh.strategy_id == saved.strategy_id and fresh.provenance.input_hash == saved.provenance.input_hash
    assert fresh.summary == pytest.approx(saved.summary, rel=1e-12)
    pd.testing.assert_frame_equal(fresh.samples, saved.samples)
