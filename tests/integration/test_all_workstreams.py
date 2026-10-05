"""Cross-workstream integration: CSV -> WS1 -> WS2 -> WS3 -> WS4, all real providers.

Uses tests/fixtures/integration/integration_test.json (same CSV, mapping and company
files as production; smaller WS1 walk-forward so the first run trains in under a
minute and later runs reuse models/ws1-test). Numbers here describe synthetic data.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.contracts import validation as val
from src.contracts.errors import ContractValidationError, RiskError
from src.contracts.identity import config_from_row
from src.contracts.types import ActionConfig, AnalysisRequest, ConstraintConfig, OptimizerConfig, RiskConfig
from src.dashboard.state import DashboardState
from src.forecasting.baseline import project_drivers
from src.forecasting.history import REPO_ROOT, load_company_history
from src.forecasting.ws1_adapter import identity_for, model_id_for
from src.integration import cache_keys, create_services, run_analysis
from src.integration.config import IntegrationConfig
from src.integration.pipeline import compare_scenarios
from src.optimization.recommendation import risk_pool_from_frontier
from src.risk.monte_carlo import UncertaintySpec, evaluate_strategy_risk
from tests.mocks import make_services

CSV = "data/synthetic_data.csv"
IMPORT = "config/company_import.json"


@pytest.fixture(scope="module")
def services():
    return create_services()


@pytest.fixture(scope="module")
def request_real(services):
    d = services.forecast.config.dashboard_defaults
    return AnalysisRequest(
        company_id=services.forecast.company_id, horizon_months=12,
        constraints=ConstraintConfig(d["budget_gbp"], d["min_total_profit_gbp"], d["min_co2_reduction_ratio"]),
        optimizer_config=OptimizerConfig(seed=7, max_evaluations=512),
        risk_enabled=True, risk_config=RiskConfig(seed=7, n_simulations=200),
        benchmark_enabled=True, explanation_enabled=True,
    )


@pytest.fixture(scope="module")
def bundle(services, request_real):
    return run_analysis(request_real, services=services)


# 1. CSV ------------------------------------------------------------------------ #

def test_existing_csv_loads_and_validates():
    imported = load_company_history(CSV, IMPORT)
    h = imported.history
    assert len(h) == 300 and h["company_id"].nunique() == 1
    assert h["timestamp"].iloc[0] == pd.Timestamp("2001-01-01") and h["timestamp"].iloc[-1] == pd.Timestamp("2025-12-01")
    val.validate_history_frame(h)
    raw = imported.raw
    assert np.allclose(h["revenue_gbp"], raw["revenue_eur"] * 0.85)
    assert np.allclose(h["operating_profit_gbp"], raw["ebitda_eur"] * 0.85)
    assert (h[["gas_kwh", "business_travel_km", "cloud_compute_hours"]] == 0).all().all()
    assert any("not reported" in t for t in imported.transforms)
    assert imported.csv_sha256 == "bce28163c1e917363786448101b87032dcc478bd7556e3a8cfc5bbf69ba3a650"


@pytest.mark.parametrize("mutate,match", [
    (lambda d: d.drop(index=10), "contiguous"),
    (lambda d: pd.concat([d, d.tail(1)]), "duplicate"),
    (lambda d: d.assign(scope1_tco2e=d["scope1_tco2e"].where(d.index != 5, np.nan)), "non-finite"),
    (lambda d: d.assign(scope1_tco2e=d["scope1_tco2e"] + 1.0), "scope1 \\+ scope2"),
    (lambda d: d.iloc[::-1], "ascending"),
    (lambda d: d.drop(columns=["scope3_tco2e"]), "missing columns"),
])
def test_csv_problems_are_rejected_not_repaired(tmp_path, mutate, match):
    bad = tmp_path / "bad.csv"
    mutate(pd.read_csv(REPO_ROOT / CSV)).to_csv(bad, index=False)
    with pytest.raises(ContractValidationError, match=match):
        load_company_history(bad, IMPORT)


# 2-3. WS1 ---------------------------------------------------------------------- #

def test_ws1_baseline_is_complete_and_accepted_by_ws2_and_ws3(services, request_real):
    b = services.forecast.get_baseline(company_id=request_real.company_id, horizon_months=12)
    val.validate_baseline(b)
    assert b.provenance.is_mock is False and b.data_kind == "synthetic" and b.currency == "GBP"
    assert b.history_end.isoformat() == "2025-12-01" and b.monthly["timestamp"].iloc[0] == pd.Timestamp("2026-01-01")
    assert b.model_id == services.forecast.model_id
    sim = services.simulate(b, ActionConfig(0.5, 0.2, 0.3, 0.0, 0.0, 0.4))
    val.validate_simulation_result(sim, b)
    risk = services.risk.evaluate(b, sim.config, constraints=request_real.constraints, assumptions=services.assumptions,
                                  config=RiskConfig(seed=1, n_simulations=20), simulator=services.simulator.simulate)
    assert risk.baseline_id == b.baseline_id and risk.strategy_id == sim.strategy_id


def test_ws1_forecast_values_come_from_ws1_best_model(services):
    art = services.forecast.artifacts()
    b = services.forecast.get_baseline(company_id=services.forecast.company_id, horizon_months=12)
    em = art.best_forecast("emissions")["prediction"].to_numpy()
    pr = art.best_forecast("profit")["prediction"].to_numpy() * 0.85
    assert np.allclose(b.monthly["total_co2e_tco2e"], em) and np.allclose(b.monthly["operating_profit_gbp"], pr)
    trailing = b.monthly  # scopes reconcile to the WS1 total
    assert np.allclose(trailing[["scope1_tco2e", "scope2_tco2e", "scope3_tco2e"]].sum(axis=1), em)


def test_backtest_is_leakage_safe_at_the_origin():
    from ml_core.modelling import TARGETS, DirectTreeForecaster, build_supervised, prepare_data
    from sklearn.ensemble import RandomForestRegressor

    data = prepare_data(load_company_history(CSV, IMPORT).raw)
    origin = 250
    history = data.iloc[: origin + 1]
    changed = data.copy()
    numeric = changed.select_dtypes("number").columns
    changed.loc[origin + 1:, numeric] = changed.loc[origin + 1:, numeric] * 3.0  # rewrite the future
    spec = TARGETS["emissions"]
    for h in (1, 12):
        X1, _, _, _ = build_supervised(history, spec, h)
        X2, _, _, _ = build_supervised(changed.iloc[: origin + 1], spec, h)
        pd.testing.assert_frame_equal(X1, X2)
    f = lambda: DirectTreeForecaster("RF", lambda: RandomForestRegressor(n_estimators=20, random_state=0), spec, 12)  # noqa: E731
    p1 = f().fit(history).predict(history)
    p2 = f().fit(changed.iloc[: origin + 1]).predict(changed.iloc[: origin + 1])
    assert np.array_equal(p1, p2)


def test_driver_projection_uses_only_history():
    h = load_company_history(CSV, IMPORT).history
    policy = IntegrationConfig.load().driver_policy
    a = project_drivers(h, 12, policy)
    b = project_drivers(pd.concat([h, h.tail(0)]), 12, policy)
    pd.testing.assert_frame_equal(a, b)
    assert a["timestamp"].iloc[0] == pd.Timestamp("2026-01-01")
    assert (a[["gas_kwh", "business_travel_km", "cloud_compute_hours"]] == 0).all().all()


# 4-8. WS2 + WS3 on the real baseline ------------------------------------------ #

def test_noop_preserves_baseline_and_costs_nothing(services, bundle):
    b = bundle.baseline
    noop = services.simulate(b, ActionConfig.noop())
    assert np.array_equal(noop.monthly["total_co2e_tco2e"].to_numpy(), b.monthly["total_co2e_tco2e"].to_numpy())
    assert np.array_equal(noop.monthly["operating_profit_gbp"].to_numpy(), b.monthly["operating_profit_gbp"].to_numpy())
    assert noop.metrics["total_cost_gbp"] == 0.0 and noop.metrics["total_capex_gbp"] == 0.0


def test_stored_optimizer_points_match_direct_simulation(services, bundle):
    assert bundle.optimization.status == "ok" and len(bundle.optimization.pareto) > 0
    for _, row in bundle.optimization.pareto.head(15).iterrows():
        direct = services.simulate(bundle.baseline, config_from_row(row))
        stored = bundle.optimization.strategies[row["strategy_id"]]
        assert direct.strategy_id == stored.strategy_id and direct.metrics == stored.metrics


def test_published_pareto_is_feasible_and_nondominated(services, bundle, request_real):
    p = bundle.optimization.pareto
    for sid in p["strategy_id"]:
        assert services.optimizer.evaluate_constraints(bundle.optimization.strategies[sid], request_real.constraints).feasible
    co2, profit = p["total_co2e_tco2e"].to_numpy(), p["total_profit_gbp"].to_numpy()
    for i in range(len(p)):
        dominated = (co2 <= co2[i] + 1e-9) & (profit >= profit[i] - 1e-9) & ((co2 < co2[i] - 1e-9) | (profit > profit[i] + 1e-9))
        assert not dominated.any()


def test_dashboard_whatif_matches_direct_simulation(services, request_real):
    state = DashboardState({})
    state.sync_services(services)
    state.ensure_baseline(request_real, services)
    state.run_optimize(replace(request_real, risk_enabled=False, explanation_enabled=False, benchmark_enabled=False), services)
    stored = state.selected_strategy()
    state.load_whatif(stored.config)
    whatif = state.ensure_whatif(services)
    assert whatif.metrics == stored.metrics
    state.set_whatif_action("ev_adoption", 0.37)
    moved = state.ensure_whatif(services)
    assert moved.metrics == services.simulate(state.baseline, replace(stored.config, ev_adoption=0.37)).metrics


def test_zero_uncertainty_risk_equals_deterministic_simulation(services, bundle, request_real):
    sid = bundle.recommendation.strategy_id
    det = bundle.optimization.strategies[sid]
    r = evaluate_strategy_risk(bundle.baseline, det.config, constraints=request_real.constraints,
                               assumptions=services.assumptions, uncertainty=UncertaintySpec.neutral(),
                               config=RiskConfig(seed=3, n_simulations=10), simulator=services.simulator.simulate)
    assert r.summary["co2_mean_tco2e"] == pytest.approx(det.metrics["total_co2e_tco2e"], rel=1e-12)
    assert r.summary["co2_p05_tco2e"] == pytest.approx(r.summary["co2_p95_tco2e"], rel=1e-12)
    assert r.summary["profit_mean_gbp"] == pytest.approx(det.metrics["total_profit_gbp"], rel=1e-12)


def test_risk_results_join_baseline_and_pool(bundle):
    pool = risk_pool_from_frontier(bundle.optimization.pareto)
    assert set(bundle.risk_results) == set(pool) and len(pool) <= 20
    for sid, r in bundle.risk_results.items():
        assert r.strategy_id == sid and r.baseline_id == bundle.baseline.baseline_id
        assert r.n_simulations == 200 and r.provenance.seed == 7
    assert len({r.uncertainty_id for r in bundle.risk_results.values()}) == 1


def test_tolerance_selection_consumes_actual_risk_results(services, bundle):
    rec = bundle.recommendation
    assert rec.risk_status in ("evaluated", "threshold_unmet", "partial") and rec.policy.startswith("risk_")
    assert rec.strategy_id in bundle.risk_results
    deterministic = services.optimizer.recommend(bundle.optimization, risk_results=None, tolerance="balanced")
    assert deterministic.risk_status == "not_requested"


def test_scenario_comparison_uses_one_analysis_and_policy(services, bundle):
    result = compare_scenarios(bundle, services=services)
    assert set(result) == {"conservative", "balanced", "aggressive"}
    assert result["balanced"].strategy_id == bundle.recommendation.strategy_id
    for tol, rec in result.items():
        assert rec.tolerance == tol and rec.strategy_id in set(bundle.optimization.pareto["strategy_id"])
        assert rec.strategy_id in bundle.risk_results
    with pytest.raises(ContractValidationError, match="risk enabled"):
        compare_scenarios(replace(bundle, request=replace(bundle.request, risk_enabled=False)), services=services)


# 11-12. SHAP and benchmark ----------------------------------------------------- #

def test_shap_explains_the_trained_ws1_model(bundle, services):
    e = bundle.explanation
    assert e is not None and e.model_id == bundle.baseline.model_id == services.forecast.model_id
    assert e.output_space == "raw_model" and e.provenance.is_mock is False
    assert all("raw model output" in u for u in e.units.values())
    g = e.contributions.groupby(["timestamp", "target"])
    sums = g["shap_value"].sum() + g["base_value"].first()
    assert np.allclose(sums.to_numpy(), g["model_prediction"].first().to_numpy(), rtol=1e-4, atol=1e-6)
    assert set(e.contributions["timestamp"]) == set(bundle.baseline.monthly["timestamp"])


def test_benchmark_without_compatible_peers_is_explicitly_unavailable(bundle):
    b = bundle.benchmark
    assert b is not None and b.status == "unavailable" and "industry_mismatch" in b.reason
    assert b.is_synthetic is True and b.source_id == "synthetic-peers-v1" and b.percentile is None


# 14-16. Cache keys, optional failures, real-mode purity ------------------------- #

def test_model_identity_changes_with_data_settings_and_mapping(tmp_path):
    imported = load_company_history(CSV, IMPORT)
    settings = dict(IntegrationConfig.load().ws1_modelling)
    base = model_id_for(identity_for(imported, settings, 12))
    assert model_id_for(identity_for(imported, {**settings, "seed": 43}, 12)) != base
    changed_csv = tmp_path / "copy.csv"
    df = pd.read_csv(REPO_ROOT / CSV)
    df.loc[len(df) - 1, "revenue_eur"] += 1.0
    df["operating_cost_eur"] = df["revenue_eur"] - df["ebitda_eur"]
    df.to_csv(changed_csv, index=False)
    assert model_id_for(identity_for(load_company_history(changed_csv, IMPORT), settings, 12)) != base


def test_cache_keys_cover_assumptions_uncertainty_and_providers(services, request_real):
    key = cache_keys.analysis_key(request_real, services)
    hybrid = make_services({"forecast": "real", "simulator": "real",
                                                                "optimizer": "real", "risk": "disabled"})
    assert cache_keys.analysis_key(request_real, hybrid) != key
    fixture_bound = make_services({"forecast": "fixture", "simulator": "real",
                                                                       "optimizer": "real"})
    # The demo fixture baseline gets the demo assumptions, never the CSV company's.
    assert fixture_bound.assumptions.assumptions_id == "demo-actions-v1"
    assert services.assumptions.assumptions_id == "supply-chain-actions-v1"
    assert cache_keys.services_key(fixture_bound) != cache_keys.services_key(services)
    assert cache_keys.analysis_key(replace(request_real, risk_config=RiskConfig(seed=8, n_simulations=200)), services) != key


def test_state_drops_stale_analysis_when_inputs_change(services, request_real):
    state = DashboardState({})
    state.sync_services(services)
    state.ensure_baseline(request_real, services)
    quick = replace(request_real, risk_enabled=False, explanation_enabled=False, benchmark_enabled=False)
    state.run_optimize(quick, services)
    assert state.analysis is not None
    state.sync_inputs(replace(quick, constraints=replace(quick.constraints, budget_gbp=1.0)), services)
    assert state.analysis is None and state.invalidated


def test_optional_failures_leave_core_analysis_usable(services, request_real, monkeypatch):
    def broken(*args, **kwargs):
        raise RiskError("trial failure injected by test")

    monkeypatch.setattr(type(services.risk), "evaluate", broken)
    b = run_analysis(replace(request_real, optimizer_config=OptimizerConfig(seed=7, max_evaluations=256)), services=services)
    assert b.optimization.status == "ok" and b.recommendation.strategy_id is not None
    assert b.risk_results == {} and b.recommendation.risk_status == "unavailable"
    assert any("trial failure injected" in w for w in b.warnings)


def test_real_mode_has_no_mocked_computational_provider(services, bundle):
    assert not services.is_mock
    assert all(info.kind == "real" and not info.is_mock for info in services.providers.values())
    assert bundle.provenance.is_mock is False
    assert all(not s.provenance.is_mock for s in list(bundle.optimization.strategies.values())[:20])
    assert bundle.baseline.data_kind == "synthetic"  # data provenance is reported separately


def test_infeasible_request_gives_empty_frontier(services, request_real):
    b = run_analysis(replace(request_real, constraints=replace(request_real.constraints, budget_gbp=0.0),
                             optimizer_config=OptimizerConfig(seed=7, max_evaluations=256)), services=services)
    assert b.optimization.status == "infeasible" and len(b.optimization.pareto) == 0
    assert b.recommendation.strategy_id is None and b.risk_results == {}


def test_chat_tools_use_the_integrated_services(services, bundle):
    from src.llm.context import AnalysisContext
    from src.llm.tools import execute_tool

    sel = bundle.optimization.strategies[bundle.recommendation.strategy_id]
    ctx = AnalysisContext(services, bundle.request, bundle.baseline, bundle, sel)
    r = execute_tool("simulate_strategy", {"final_shares": {"ev_adoption": 0.5}}, context=ctx, services=services)
    direct = services.simulate(bundle.baseline, ActionConfig.from_mapping(r.data["config"]))
    assert r.status == "ok" and r.data["metrics"]["total_co2e_tco2e"] == direct.metrics["total_co2e_tco2e"]
    assert r.data["is_mock"] is False


def test_tolerance_change_follows_recommendation_but_keeps_a_user_pick(services, request_real):
    quick = replace(request_real, explanation_enabled=False, benchmark_enabled=False)
    state = DashboardState({})
    state.sync_services(services)
    state.ensure_baseline(quick, services)
    state.run_optimize(quick, services)
    picks = {}
    for tol in ("conservative", "aggressive"):
        state.sync_inputs(replace(quick, tolerance=tol), services)
        assert state.selected_strategy_id == state.analysis.recommendation.strategy_id
        picks[tol] = state.selected_strategy_id
    assert picks["conservative"] != picks["aggressive"]  # policies differ on this analysis
    other = next(s for s in state.analysis.optimization.pareto["strategy_id"] if s not in picks.values())
    state.select_strategy(other)
    state.sync_inputs(replace(quick, tolerance="balanced"), services)
    assert state.selected_strategy_id == other  # an explicit user selection is never overwritten


def test_real_services_bind_from_any_working_directory(tmp_path):
    import subprocess
    import sys

    code = ("import sys; sys.path.insert(0, %r)\n"
            "from src.integration import create_services\n"
            "s = create_services()\n"
            "assert s.capabilities.risk_available and s.capabilities.benchmark_available, s.unavailable\n"
            "print('ok')\n") % str(REPO_ROOT)
    proc = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0 and proc.stdout.strip() == "ok", proc.stderr
