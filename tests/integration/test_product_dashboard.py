"""The dashboard has one company-backed path, including on legacy deployments."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from src.integration import create_services
from tests.support import REPO_ROOT


def start() -> AppTest:
    app = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=300).run()
    assert not app.exception, [e.message for e in app.exception]
    return app


@pytest.mark.parametrize("legacy_mode", [None, "mock", "hybrid", "real", "invalid"])
def test_default_and_legacy_launches_use_the_configured_company(monkeypatch, legacy_mode):
    monkeypatch.setenv("CARBONOPT_HYBRID_PRESET", "custom")
    monkeypatch.setenv("CARBONOPT_COMPANY_ID", "legacy-company")
    if legacy_mode is None:
        monkeypatch.delenv("CARBONOPT_PROVIDER_MODE", raising=False)
    else:
        monkeypatch.setenv("CARBONOPT_PROVIDER_MODE", legacy_mode)
    app = start()
    baseline = app.session_state["cos_baseline"]
    assert baseline.company_id == "supply-chain-demo-co" and not baseline.provenance.is_mock
    assert baseline.data_kind == "synthetic"
    assert app.number_input(key="co_widget_budget").value == 20_000_000
    assert not any(w.key in ("co_widget_mode", "co_widget_preset", "co_widget_horizon") for w in app.selectbox)
    assert not any(w.key == "co_widget_seed" for w in app.number_input)
    visible = " ".join(str(e.value) for group in (app.caption, app.info, app.warning, app.error, app.markdown)
                       for e in group)
    assert all(word not in visible for word in ("MOCK", "WS1", "WS2", "WS3", "Provider mode", "input hash", "tests/"))
    # Only the actions this company's data supports get a slider.
    assert {s.key for s in app.slider} >= {"co_slider_renewable_energy", "co_slider_ev_adoption"}
    assert "co_slider_travel_reduction" not in {s.key for s in app.slider}
    assert "Not available for this data" in visible


def test_factory_defaults_to_domain_services():
    services = create_services()
    assert not services.is_mock
    assert services.assumptions.assumptions_id == "supply-chain-actions-v1"
    assert services.capabilities.risk_available and services.capabilities.benchmark_available


def _all_text(app: AppTest) -> str:
    return " ".join(str(e.value) for group in (app.caption, app.info, app.warning, app.error, app.markdown, app.success)
                    for e in group)


def test_sidebar_shows_what_the_budget_and_profit_floor_accept():
    app = start()
    sidebar = " ".join(str(c.value) for c in app.sidebar.caption)
    assert "£0 or more" in sidebar and "makes no difference" in sidebar  # budget: lower bound and useful top
    assert "Any amount, can be negative" in sidebar and "without new actions" in sidebar


def test_history_timeline_can_be_narrowed():
    app = start()
    timeline = app.select_slider(key="co_widget_timeline")
    months = timeline.options
    timeline.set_value((months[12], months[-1])).run()
    assert not app.exception, [e.message for e in app.exception]
    assert app.select_slider(key="co_widget_timeline").value == (months[12], months[-1])


def test_models_are_compared_only_on_request_and_one_can_drive_the_forecast():
    app = start()
    assert app.session_state["cos_backtest"].selected_models["total_co2e_tco2e"] == "RandomForest"
    assert not any(getattr(d, "key", None) == "co_model_table" for d in app.dataframe)  # nothing ran at load
    app.pills(key="co_widget_models").set_value(["RandomForest", "SeasonalNaive"]).run()
    [b for b in app.button if b.label == "Compare models"][0].click().run()
    assert not app.exception, [e.message for e in app.exception]
    assert any("Lowest error" in t for t in (str(c.value) for c in app.caption))
    app.selectbox(key="co_widget_forecast_model").set_value("SeasonalNaive").run()
    assert not app.exception, [e.message for e in app.exception]
    assert app.session_state["cos_backtest"].selected_models["total_co2e_tco2e"] == "SeasonalNaive"


def test_grid_timing_and_uncertainty_method_are_explained():
    app = start()
    text = _all_text(app)
    assert "Cleanest hour in the saved forecast" in text  # offline: the recorded GB grid example
    assert "Monte Carlo" in text
