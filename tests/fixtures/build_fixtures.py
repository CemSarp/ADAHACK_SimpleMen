"""Build the C0 fixtures that examples/ does not provide.

Run from the repository root:  python -m tests.fixtures.build_fixtures

Outputs (tests/fixtures/v1/):
  history_96m.csv, history_provenance.json  - UI shape history (2019-01..2026-12)
  backtest_report.json                      - illustrative BacktestReport shape
  shap_explanation.json                     - illustrative ExplanationResult shape

These are deterministic, synthetic, mock-labelled SHAPE fixtures. They are not a
WS1 data generator, a trained model or a forecast evaluation. Fixtures are
immutable per revision: change FIXTURE_REVISION when regenerating with new values.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.contracts.serialization import frame_to_records
from src.contracts.types import HISTORY_COLUMNS, SCHEMA_VERSION

FIXTURE_DIR = Path(__file__).resolve().parent / "v1"
FIXTURE_REVISION = "c0-fixtures-r1"
SEED = 42
COMPANY_ID = "demo-company"


def _provenance(assumptions_id: str | None = None) -> dict:
    return {
        "provider": "fixture",
        "is_mock": True,
        "seed": SEED,
        "input_hash": FIXTURE_REVISION,
        "config_id": "demo-v1",
        "assumptions_id": assumptions_id,
    }


def build_history() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    ts = pd.date_range("2019-01-01", "2026-12-01", freq="MS")
    n = len(ts)
    years_before_2027 = (2027 - ts.year) - (ts.month - 1) / 12.0
    season = np.sin(2 * np.pi * (ts.month - 1) / 12.0)
    winter = np.cos(2 * np.pi * (ts.month - 1) / 12.0)  # +1 in January
    noise = rng.normal(0.0, 0.01, size=(6, n))

    revenue = 1_000_000.0 * (1 - 0.03 * years_before_2027) * (1 + 0.04 * season + noise[0])
    profit = revenue * 0.1 * (1 + 0.05 * winter + noise[1])
    electricity = 100_000.0 * (1 + 0.08 * winter + noise[2])
    gas = 50_000.0 * (1 + 0.30 * winter + noise[3])
    renewable = np.round(np.linspace(0.10, 0.20, n), 6)
    fleet_km = 50_000.0 * (1 + 0.05 * season + noise[4])
    travel_km = 20_000.0 * (1 + 0.15 * season + noise[5])
    cloud_hours = 10_000.0 * (1 - 0.04 * years_before_2027)

    scope1 = 20.0 * (0.6 * gas / 50_000.0 + 0.4 * fleet_km / 50_000.0)
    scope2 = 30.0 * (electricity / 100_000.0) * (1 - renewable) / 0.8
    scope3 = 50.0 * (0.2 * travel_km / 20_000.0 + 0.2 * cloud_hours / 10_000.0 + 0.6 * revenue / 1_000_000.0)
    scope1, scope2, scope3 = (np.round(s, 6) for s in (scope1, scope2, scope3))

    frame = pd.DataFrame(
        {
            "company_id": COMPANY_ID,
            "timestamp": ts.astype("datetime64[ns]"),
            "revenue_gbp": np.round(revenue, 2),
            "operating_profit_gbp": np.round(profit, 2),
            "employees": np.int64(500),
            "electricity_kwh": np.round(electricity, 1),
            "gas_kwh": np.round(gas, 1),
            "renewable_energy_share": renewable,
            "ev_share": 0.0,
            "fleet_size": np.int64(20),
            "fleet_km": np.round(fleet_km, 1),
            "business_travel_km": np.round(travel_km, 1),
            "cloud_compute_hours": np.round(cloud_hours, 1),
            "scope1_tco2e": scope1,
            "scope2_tco2e": scope2,
            "scope3_tco2e": scope3,
        }
    )
    frame["total_co2e_tco2e"] = frame["scope1_tco2e"] + frame["scope2_tco2e"] + frame["scope3_tco2e"]
    return frame[list(HISTORY_COLUMNS)]


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> tuple[float, float, float | None]:
    err = predicted - actual
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    ss_tot = float(np.sum((actual - actual.mean()) ** 2))
    r2 = None if ss_tot == 0 else float(1 - np.sum(err**2) / ss_tot)
    return mae, rmse, r2


def build_backtest(history: pd.DataFrame) -> dict:
    rng = np.random.default_rng(SEED + 1)
    indexed = history.set_index("timestamp")
    folds, oof = [], []
    for fold_id, year in enumerate((2024, 2025, 2026)):
        test_dates = pd.date_range(f"{year}-01-01", f"{year}-12-01", freq="MS")
        cutoff = test_dates[0] - pd.offsets.MonthBegin(1)
        for target in ("total_co2e_tco2e", "operating_profit_gbp"):
            actual = indexed.loc[test_dates, target].to_numpy()
            naive = indexed.loc[test_dates - pd.DateOffset(years=1), target].to_numpy()
            scale = 0.02 if target == "total_co2e_tco2e" else 0.03
            predicted = np.round(actual * (1 + rng.normal(0.0, scale, len(actual))), 4)
            mae, rmse, r2 = _metrics(actual, predicted)
            nmae, nrmse, _ = _metrics(actual, naive)
            folds.append({
                "fold_id": fold_id, "train_cutoff": cutoff.date().isoformat(),
                "test_start": test_dates[0].date().isoformat(), "test_end": test_dates[-1].date().isoformat(),
                "target": target, "mae": mae, "rmse": rmse, "r2": r2, "naive_mae": nmae, "naive_rmse": nrmse,
                "effective_train_size": int((indexed.index <= cutoff).sum() - 12), "adjustment_count": 0,
            })
            for t, a, p, nv in zip(test_dates, actual, predicted, naive):
                oof.append({"fold_id": fold_id, "timestamp": t.date().isoformat(), "target": target,
                            "actual": float(a), "predicted": float(p), "naive_predicted": float(nv)})
    oof_frame = pd.DataFrame(oof)
    aggregate = {}
    for target, group in oof_frame.groupby("target", sort=True):
        mae, rmse, r2 = _metrics(group["actual"].to_numpy(), group["predicted"].to_numpy())
        nmae, nrmse, _ = _metrics(group["actual"].to_numpy(), group["naive_predicted"].to_numpy())
        aggregate[target] = {"mae": mae, "rmse": rmse, "r2": r2, "naive_mae": nmae, "naive_rmse": nrmse}
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": "fixture-backtest-run",
        "provenance": _provenance(),
        "model_family": "fixture-illustrative",
        "feature_spec_id": "fixture-features-v1",
        "driver_policy_id": "flat-demo-v1",
        "selected_models": {"total_co2e_tco2e": "fixture-illustrative", "operating_profit_gbp": "fixture-illustrative"},
        "folds": folds,
        "aggregate_metrics": aggregate,
        "oof_predictions": oof,
        "fixture_note": "Illustrative numbers for panel layout; not a model evaluation.",
    }


def build_shap(baseline: dict, history: pd.DataFrame) -> dict:
    rows = []
    last = history.iloc[-1]
    specs = {
        "total_co2e_tco2e": (95.0, [("total_co2e_lag_1", float(last["total_co2e_tco2e"]), 0.45),
                                     ("total_co2e_lag_12", None, 0.25),
                                     ("month_sin", None, 0.10),
                                     ("revenue_gbp_projected", None, 0.20)]),
        "operating_profit_gbp": (98_000.0, [("operating_profit_lag_1", float(last["operating_profit_gbp"]), 0.5),
                                            ("operating_profit_lag_12", None, 0.2),
                                            ("month_sin", None, 0.1),
                                            ("revenue_gbp_projected", None, 0.2)]),
    }
    for month in baseline["monthly"]:
        ts = month["timestamp"]
        month_index = int(ts[5:7])
        for target, (base, feats) in specs.items():
            prediction = float(month[target])
            remaining = prediction - base
            for name, value, weight in feats:
                if value is None:
                    value = (
                        float(np.sin(2 * np.pi * (month_index - 1) / 12)) if name == "month_sin"
                        else float(month["revenue_gbp"]) if name == "revenue_gbp_projected"
                        else float(history.loc[history["timestamp"].dt.month == month_index].iloc[-1][target])
                    )
                rows.append({"timestamp": ts, "target": target, "feature": name, "feature_value": value,
                             "shap_value": remaining * weight, "base_value": base, "model_prediction": prediction})
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": "fixture-shap-run",
        "provenance": _provenance(),
        "model_id": baseline["model_id"],
        "baseline_id": baseline["baseline_id"],
        "driver_policy_id": baseline["driver_policy_id"],
        "output_space": "raw_model",
        "units": {"total_co2e_tco2e": "tCO2e", "operating_profit_gbp": "GBP"},
        "explained_rows": len(baseline["monthly"]),
        "contributions": rows,
        "fixture_note": "Illustrative contributions for panel layout; not a SHAP computation.",
    }


def main() -> None:
    history = build_history()
    history_out = history.copy()
    history_out["timestamp"] = history_out["timestamp"].dt.strftime("%Y-%m-%d")
    history_out.to_csv(FIXTURE_DIR / "history_96m.csv", index=False)
    (FIXTURE_DIR / "history_provenance.json").write_text(json.dumps({
        "data_kind": "synthetic",
        "source_description": "Deterministic WS4 C0 shape fixture for dashboard history panels; not the WS1 generator.",
        "reporting_frequency": "monthly",
        "accounting_scope": "scope1_scope2_scope3",
        "scope2_method": "market_based_demo",
        "generator_config_id": FIXTURE_REVISION,
        "seed": SEED,
        "units": {"emissions": "tCO2e", "money": "GBP", "energy": "kWh"},
        "transforms": [],
        "is_mock": True,
    }, indent=2) + "\n")
    baseline = json.loads((FIXTURE_DIR / "baseline_12m.json").read_text())
    (FIXTURE_DIR / "backtest_report.json").write_text(json.dumps(build_backtest(history), indent=2) + "\n")
    (FIXTURE_DIR / "shap_explanation.json").write_text(json.dumps(build_shap(baseline, history), indent=2) + "\n")
    assert frame_to_records(history.head(1))  # serializer accepts the frame


if __name__ == "__main__":
    main()
