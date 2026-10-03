"""Streamlit AppTest of the documented hybrid dashboard (fixture forecast + real WS2).

Drives app.py the way a user does: sidebar inputs, Optimize, strategy loading, sliders.
Uses a reduced, explicit evaluation budget so the seeded search stays fast.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from src.integration.services import DEFAULT_HYBRID_PRESET  # noqa: E402
from tests.support import REPO_ROOT  # noqa: E402

APP = str(REPO_ROOT / "app.py")

EVALUATIONS = 256


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("CARBONOPT_PROVIDER_MODE", "hybrid")
    monkeypatch.delenv("CARBONOPT_HYBRID_PRESET", raising=False)
    at = AppTest.from_file(APP, default_timeout=300).run()
    assert not at.exception, [e.message for e in at.exception]
    at.number_input(key="co_widget_evals").set_value(EVALUATIONS).run()
    return at


def _optimize(at: AppTest) -> AppTest:
    [b for b in at.button if b.label == "Optimize"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _texts(elements) -> list[str]:
    return [e.value for e in elements]


def test_hybrid_startup_labels_every_provider_and_disabled_shap(app):
    assert app.selectbox(key="co_widget_preset").value == DEFAULT_HYBRID_PRESET
    assert any(w.startswith("**PARTIALLY MOCKED — hybrid mode.**") for w in _texts(app.warning))
    assert not any("All bound providers are real" in s for s in _texts(app.success))
    assert "Baseline: fixture · Simulator: WS2 · Optimizer: WS2 · Risk: WS3 · SHAP: unavailable · " \
           "Benchmark: WS3" in _texts(app.caption)
    infos = _texts(app.info)
    assert not any("Risk is unavailable:" in s or "Benchmark is unavailable:" in s for s in infos)


def test_optimize_consumes_current_inputs_and_selects_the_recommendation(app):
    app.number_input(key="co_widget_budget").set_value(450_000.0)
    app.number_input(key="co_widget_profit").set_value(950_000.0)
    app.slider(key="co_widget_target").set_value(25)
    _optimize(app.run())
    analysis = app.session_state["cos_analysis"]
    assert analysis.request.company_id == "demo-company"  # the public reference panel never feeds the optimizer
    c = analysis.request.constraints
    assert (c.budget_gbp, c.min_total_profit_gbp, c.min_co2_reduction_ratio) == (450_000.0, 950_000.0, 0.25)
    assert analysis.optimization.constraints == c
    assert analysis.optimization.diagnostics["evaluated_count"] <= EVALUATIONS
    assert analysis.optimization.status == "ok" and app.session_state["cos_status"] == "ready"
    rec = analysis.recommendation.strategy_id
    assert rec in set(analysis.optimization.pareto["strategy_id"])
    assert app.session_state["cos_selected_strategy_id"] == rec
    assert app.selectbox(key="co_widget_select").value == rec


def test_loading_the_selected_strategy_reproduces_its_stored_outcome(app):
    _optimize(app)
    [b for b in app.button if b.label == "Load selected strategy"][0].click().run()
    stored = app.session_state["cos_analysis"].optimization.strategies[app.session_state["cos_selected_strategy_id"]]
    whatif = app.session_state["cos_whatif_result"]
    assert whatif.config == stored.config and whatif.metrics == stored.metrics
    assert "✔ Identical to the stored optimizer result for the selected strategy." in _texts(app.caption)
    assert any("Meets the current budget, profit floor and CO₂ target" in s for s in _texts(app.success))


def test_slider_change_recomputes_through_the_real_simulator(app):
    app.slider(key="co_slider_renewable_energy").set_value(0.5).run()
    whatif = app.session_state["cos_whatif_result"]
    assert whatif.provenance.provider == "action-engine"
    assert whatif.config.renewable_energy == 0.5 and whatif.config.ev_adoption == 0.0
    # 30 t/month scope2 halves under the WS2 model: 12 x 15 t less than the 1,200 t baseline.
    assert whatif.metrics["total_co2e_tco2e"] == pytest.approx(1_200.0 - 12 * 15.0)


def test_input_change_discards_stale_results(app):
    _optimize(app)
    assert app.session_state["cos_analysis"] is not None
    app.number_input(key="co_widget_budget").set_value(300_000.0).run()
    assert "cos_analysis" not in app.session_state or app.session_state["cos_analysis"] is None
    assert any("Inputs changed since the last optimization" in i for i in _texts(app.info))


def test_infeasible_request_shows_no_recommendation_state(app):
    app.number_input(key="co_widget_budget").set_value(0.0)
    _optimize(app.run())
    assert app.session_state["cos_status"] == "infeasible"
    assert any("No feasible recommendation found" in e for e in _texts(app.error))
    assert not [s for s in app.selectbox if s.key == "co_widget_select"]


def test_real_mode_starts_with_all_real_providers_and_synthetic_data_label(monkeypatch):
    # Integrated: WS1 (CSV company), WS2, WS3 are all real; the data stays labelled synthetic.
    monkeypatch.setenv("CARBONOPT_PROVIDER_MODE", "real")
    at = AppTest.from_file(APP, default_timeout=600).run()
    assert not at.exception, [e.message for e in at.exception]
    assert not _texts(at.error)
    assert any("All bound computational providers are real" in s for s in _texts(at.success))
    assert any("SYNTHETIC DATA" in c for c in _texts(at.caption))
    assert not any("PARTIALLY MOCKED" in w or "MOCK OUTPUT" in w for w in _texts(at.warning))
