"""Forecasting models on demand: compare them on the loaded data, then forecast with the chosen one."""

from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from src.forecasting.history import ImportConfig, import_history
from src.forecasting.mapping import detect_currency, detect_date_column, import_mapping, suggest_mapping
from src.forecasting.ws1_adapter import available_models, compare_models
from src.integration import create_services
from src.integration.services import create_dataset_services
from tests.support import REPO_ROOT

SAMPLE = REPO_ROOT / "data" / "sample_upload.csv"
SHA = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
FAST = ("RandomForest", "SeasonalNaive")


@pytest.fixture(scope="module")
def upload():
    raw = pd.read_csv(SAMPLE)
    date = detect_date_column(raw)
    mapping = import_mapping(suggest_mapping(list(raw.columns), date), company="Acme Manufacturing",
                             date_column=date, currency=detect_currency(list(raw.columns)), gbp_per_unit=0.79)
    return raw, mapping


def test_installed_models_are_listed():
    assert set(FAST) <= set(available_models())


def test_comparison_scores_each_model_on_the_held_out_months(upload):
    raw, mapping = upload
    imported = import_history(raw, ImportConfig.from_dict(mapping), source="sample", sha256=SHA)
    table = compare_models(imported, {"test_months": 12, "step": 3, "seed": 42}, 12, FAST)
    assert set(zip(table["target"], table["model"])) == {(t, m) for t in ("emissions", "profit") for m in FAST}
    assert {"wape", "mae", "seconds"} <= set(table.columns)
    assert (table["wape"] >= 0).all() and (table["seconds"] >= 0).all()


def test_a_chosen_model_drives_the_forecast_and_its_cache_identity(upload):
    raw, mapping = upload
    auto = create_dataset_services(raw, mapping, name="sample_upload.csv", sha256=SHA)
    naive = create_dataset_services(raw, mapping, name="sample_upload.csv", sha256=SHA, model="SeasonalNaive")
    assert auto.forecast.model_id != naive.forecast.model_id
    company = naive.forecast.company_id
    naive.forecast.get_baseline(company_id=company, horizon_months=12)
    assert naive.forecast.get_backtest(company_id=company).selected_models["total_co2e_tco2e"] == "SeasonalNaive"


def test_forecast_drivers_explain_the_uploaded_company(upload):
    raw, mapping = upload
    services = create_dataset_services(raw, mapping, name="sample_upload.csv", sha256=SHA)
    baseline = services.forecast.get_baseline(company_id=services.forecast.company_id, horizon_months=12)
    explanation = services.shap.explain(baseline)
    assert explanation.model_id == services.forecast.model_id


def test_demo_company_accepts_a_model_choice():
    services = create_services(model="SeasonalNaive")
    report = services.forecast.get_backtest(company_id=services.forecast.company_id)
    assert report.selected_models["total_co2e_tco2e"] == "SeasonalNaive"
