"""Streamlit AppTest of the integrated company dashboard (test WS1 config, synthetic CSV)."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from tests.support import REPO_ROOT

APP = str(REPO_ROOT / "app.py")


def _texts(elements) -> list[str]:
    return [getattr(e, "value", "") or "" for e in elements]


@pytest.fixture
def app(monkeypatch):
    at = AppTest.from_file(APP, default_timeout=900).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _optimize(at, *, risk: bool) -> None:
    at.number_input(key="co_widget_evals").set_value(256).run()
    if risk:
        at.checkbox(key="co_widget_risk").check().run()
        at.number_input(key="co_widget_trials").set_value(200).run()
    [b for b in at.button if b.label == "Optimize"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]


def test_real_mode_uses_company_defaults(app):
    assert app.number_input(key="co_widget_budget").value == 20_000_000.0
    assert app.number_input(key="co_widget_profit").value == 30_000_000.0
    assert app.slider(key="co_widget_target").value == 10
    captions = " ".join(_texts(app.caption))
    assert "Synthetic data" in captions
    assert app.session_state["cos_baseline"].company_id == "supply-chain-demo-co"


def test_optimize_risk_tolerance_and_scenarios(app):
    _optimize(app, risk=True)
    assert not app.error
    recommended = app.selectbox(key="co_widget_select").value
    assert recommended.startswith("strategy-")
    captions = " ".join(_texts(app.caption))
    assert "Balanced approach" in captions and "All approaches use the same forecast" in captions
    # Tolerance change: selection policy reruns on the same pool (no re-optimization, no stale result)
    app.radio(key="co_widget_tolerance").set_value("conservative").run()
    assert not app.exception
    captions = " ".join(_texts(app.caption))
    assert "Conservative approach" in captions and "Inputs changed" not in " ".join(_texts(app.info))
    # The selection followed the recommendation (the user had not picked another plan).
    star = next(c for c in _texts(app.caption) if c.startswith("★ "))
    assert app.selectbox(key="co_widget_select").value != "" and "Conservative approach" in star


def test_whatif_load_and_slider_on_real_engine(app):
    _optimize(app, risk=False)
    [b for b in app.button if b.label == "Load selected strategy"][0].click().run()
    assert "Matches the selected plan." in _texts(app.caption)
    app.slider(key="co_slider_ev_adoption").set_value(0.9).run()
    assert not app.exception
    assert "Matches the selected plan." not in _texts(app.caption)


def test_infeasible_request_shows_no_recommendation(app):
    app.number_input(key="co_widget_budget").set_value(0.0).run()
    _optimize(app, risk=False)
    assert any("No feasible recommendation found" in e for e in _texts(app.error))
