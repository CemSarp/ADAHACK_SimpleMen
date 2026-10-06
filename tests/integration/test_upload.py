"""Any monthly company table: column matching, import notes, its own forecast and actions."""

from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.contracts import validation as val
from src.contracts.errors import ContractValidationError
from src.contracts.types import AnalysisRequest, ConstraintConfig, OptimizerConfig
from src.forecasting.history import ImportConfig, import_history
from src.forecasting.mapping import (
    detect_currency,
    detect_date_column,
    import_mapping,
    missing_required,
    suggest_mapping,
)
from src.integration import run_analysis
from src.integration.services import create_dataset_services
from src.optimization import inactive_actions
from tests.support import REPO_ROOT

SAMPLE = REPO_ROOT / "data" / "sample_upload.csv"


def _mapping(raw: pd.DataFrame, company: str = "Acme Manufacturing") -> dict:
    date = detect_date_column(raw)
    currency = detect_currency(list(raw.columns))
    return import_mapping(suggest_mapping(list(raw.columns), date), company=company, date_column=date,
                          currency=currency, gbp_per_unit=0.79)


def test_suggestions_reproduce_the_hand_written_demo_mapping():
    demo = pd.read_csv(REPO_ROOT / "data" / "synthetic_data.csv")
    suggested = suggest_mapping(list(demo.columns), detect_date_column(demo))
    configured = json.loads((REPO_ROOT / "config" / "company_import.json").read_text())["columns"]
    assert {k: v for k, v in suggested.items() if v} == {k: spec["from"] for k, spec in configured.items()}
    assert detect_currency(list(demo.columns)) == "EUR"


def test_sample_upload_is_matched_and_imported_with_visible_notes():
    raw = pd.read_csv(SAMPLE)
    mapping = suggest_mapping(list(raw.columns), detect_date_column(raw))
    assert mapping["revenue_gbp"] == "Net Sales (USD)" and mapping["operating_cost"] == "Operating Expenses (USD)"
    assert mapping["operating_profit_gbp"] is None and missing_required(mapping) == []
    imported = import_history(raw, ImportConfig.from_dict(_mapping(raw)), source="sample", sha256="x")
    h = val.validate_history_frame(imported.history)
    assert len(h) == 96 and h["timestamp"].iloc[0] == pd.Timestamp("2018-01-01")
    assert h["renewable_energy_share"].max() <= 1.0  # "Renewable %" read as a percentage
    expected = raw["Net Sales (USD)"] - raw["Operating Expenses (USD)"]
    assert (h["operating_profit_gbp"] - expected * 0.79).abs().max() < 1e-6
    notes = " | ".join(imported.transforms)
    for fragment in ("missing values filled", "percentage", "revenue - Operating Expenses", "sum of the reported scopes"):
        assert fragment in notes


@pytest.mark.parametrize("mutate,match", [
    (lambda d: pd.concat([d, d.tail(1)]), "twice"),
    (lambda d: d.head(12), "at least 24 months"),
    (lambda d: d.assign(Month="not a date"), "readable date"),
])
def test_bad_uploads_say_what_is_wrong(mutate, match):
    raw = pd.read_csv(SAMPLE)
    with pytest.raises(ContractValidationError, match=match):
        import_history(mutate(raw), ImportConfig.from_dict(_mapping(raw)), source="bad", sha256="x")


def test_a_mapping_without_revenue_is_incomplete():
    assert "revenue" in missing_required({"operating_profit_gbp": "p", "total_co2e_tco2e": "t"})


def test_uploaded_company_gets_its_own_forecast_actions_and_goals():
    raw = pd.read_csv(SAMPLE)
    services = create_dataset_services(raw, _mapping(raw), name="sample_upload.csv",
                                       sha256=hashlib.sha256(SAMPLE.read_bytes()).hexdigest())
    baseline = services.forecast.get_baseline(company_id="acme-manufacturing", horizon_months=12)
    val.validate_baseline(baseline)
    assert baseline.data_kind == "reported" and baseline.history_end.isoformat() == "2025-12-01"
    # No fleet, travel, cloud or scope 3 data: those actions change nothing and are kept at zero.
    assert set(inactive_actions(baseline, services.assumptions, services.simulator.simulate)) == {
        "ev_adoption", "travel_reduction", "cloud_efficiency", "supplier_transition"}
    goals = services.forecast.config.dashboard_defaults
    assert 1e6 < goals["budget_gbp"] < 1e7  # sized to this company, not the demo's £20m
    request = AnalysisRequest(company_id="acme-manufacturing", horizon_months=12,
                              constraints=ConstraintConfig(goals["budget_gbp"], goals["min_total_profit_gbp"], 0.1),
                              optimizer_config=OptimizerConfig(seed=3, max_evaluations=128))
    bundle = run_analysis(request, services=services)
    assert bundle.optimization.status == "ok"
    best = bundle.optimization.strategies[bundle.recommendation.strategy_id].config
    assert best.ev_adoption == best.travel_reduction == best.cloud_efficiency == best.supplier_transition == 0.0


def test_app_runs_on_an_uploaded_dataset():
    raw = pd.read_csv(SAMPLE)
    app = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=300)
    app.session_state["co_widget_source"] = "Your data"
    app.session_state["co_dataset"] = {"name": "sample_upload.csv", "bytes": SAMPLE.read_bytes(), "mapping": _mapping(raw)}
    app.run()
    assert not app.exception, [e.message for e in app.exception]
    assert app.session_state["cos_baseline"].company_id == "acme-manufacturing"
    assert {s.key for s in app.slider} == {"co_slider_renewable_energy", "co_slider_building_efficiency", "co_widget_target"}


def test_upload_step_explains_matching_and_tidying_in_plain_words():
    app = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=300)
    app.session_state["co_widget_source"] = "Your data"
    app.run()
    assert not app.exception, [e.message for e in app.exception]
    text = " ".join(str(m.value) for m in app.markdown)
    for phrase in ("guess which column", "message says what", "example file", "rate you set", "filled in from the months",
                   "every change is listed"):
        assert phrase in text, phrase


def test_chat_flags_actions_that_change_nothing_for_this_company():
    from src.llm.context import AnalysisContext
    from src.llm.tools import execute_tool

    raw = pd.read_csv(SAMPLE)
    services = create_dataset_services(raw, _mapping(raw), name="sample_upload.csv",
                                       sha256=hashlib.sha256(SAMPLE.read_bytes()).hexdigest())
    baseline = services.forecast.get_baseline(company_id="acme-manufacturing", horizon_months=12)
    goals = services.forecast.config.dashboard_defaults
    request = AnalysisRequest(company_id="acme-manufacturing", horizon_months=12,
                              constraints=ConstraintConfig(goals["budget_gbp"], goals["min_total_profit_gbp"], 0.1),
                              optimizer_config=OptimizerConfig(seed=3, max_evaluations=64))
    ctx = AnalysisContext(services, request, baseline, None, None, history=imported_history(raw))
    r = execute_tool("simulate_strategy", {"actions": {"ev_adoption": 0.5, "renewable_energy": 0.5}},
                     context=ctx, services=services)
    assert r.status == "ok"
    assert any("EV fleet adoption has no effect for this company" in n for n in r.data["notes"])
    assert not any("Renewable" in n and "no effect" in n for n in r.data["notes"])


def imported_history(raw):
    return import_history(raw, ImportConfig.from_dict(_mapping(raw)), source="sample", sha256="x").history
