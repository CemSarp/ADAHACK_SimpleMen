"""The dashboard has one company-backed path, including on legacy deployments."""

from __future__ import annotations

import time

import pytest
from streamlit.testing.v1 import AppTest

from src.dashboard import trainer
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
    assert app.number_input(key="co_widget_budget").value == 20_000_000
    assert not any(w.key in ("co_widget_mode", "co_widget_preset", "co_widget_horizon") for w in app.selectbox)
    assert not any(w.key == "co_widget_seed" for w in app.number_input)
    visible = " ".join(str(e.value) for group in (app.caption, app.info, app.warning, app.error, app.markdown)
                       for e in group)
    assert all(word not in visible for word in ("MOCK", "WS1", "WS2", "WS3", "Provider mode", "input hash", "tests/"))
    assert "Synthetic data" in visible


def test_factory_defaults_to_domain_services():
    services = create_services()
    assert services.mode == "real" and not services.is_mock
    assert services.assumptions.assumptions_id == "supply-chain-actions-v1"
    assert services.capabilities.risk_available and services.capabilities.benchmark_available


def test_data_explorer_changes_feature_and_window():
    app = start()
    app.selectbox(key="eda_feature").set_value("revenue_eur")
    app.selectbox(key="eda_range").set_value("1 year").run()
    assert not app.exception
    assert app.selectbox(key="eda_feature").value == "revenue_eur"
    assert app.selectbox(key="eda_range").value == "1 year"
    assert app.session_state["cos_baseline"] is not None


def test_model_comparison_completes_without_replacing_planning_forecast(monkeypatch, tmp_path):
    monkeypatch.setattr(trainer, "OUTPUT_DIR", tmp_path / "comparison")
    app = start()
    baseline = app.session_state["cos_baseline"]
    app.pills(key="trainer_models").set_value(["SeasonalNaive"]).run()
    app.button(key="trainer_start").click().run()
    job = app.session_state[trainer.JOB_KEY]
    deadline = time.monotonic() + 120
    while job.running and time.monotonic() < deadline:
        time.sleep(0.1)
    if job.running:
        job.abort()
        pytest.fail("Model comparison timed out")
    assert job.returncode == 0, "\n".join(job.lines[-20:])
    app.run()
    assert not app.exception
    assert any("Comparison complete" in e.value for e in app.success)
    assert (trainer.OUTPUT_DIR / "emissions" / "summary.json").exists()
    assert (trainer.OUTPUT_DIR / "profit" / "summary.json").exists()
    assert app.session_state["cos_baseline"].model_id == baseline.model_id
    assert app.session_state["cos_baseline"].totals == baseline.totals
