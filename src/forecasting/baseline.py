"""Assemble contract objects from WS1 outputs.

* BaselineBundle: WS1 best-model forecasts of total emissions and EBITDA become
  `total_co2e_tco2e` and `operating_profit_gbp`; activity fields come from an
  explicit deterministic driver policy (FORECASTING_SPEC.md s3); scopes are
  reconciled to the forecast total with trailing-12-month aggregate shares
  (s4 step 7). WS1 does not forecast activities or scopes, so these two steps are
  integration adapters pending WS1 review.
* BacktestReport: WS1's held-out walk-forward predictions (best model) against
  its seasonal-naive-with-drift model at the same origins and horizons.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.contracts import validation as val
from src.contracts.errors import ForecastError
from src.contracts.identity import canonical_hash
from src.contracts.serialization import BACKTEST_FOLD_SPEC, BACKTEST_OOF_SPEC, empty_frame
from src.contracts.types import (
    HISTORY_COLUMNS,
    HISTORY_INT_COLUMNS,
    SCHEMA_VERSION,
    SCOPE_COLUMNS,
    BacktestReport,
    BaselineBundle,
    Provenance,
)

from .history import ImportedHistory
from .ws1_adapter import TARGET_KEYS, WS1Artifacts

PROVIDER_NAME = "ws1-ml_core"
NAIVE_MODEL = "SeasonalNaive"


def project_drivers(history: pd.DataFrame, horizon: int, policy: Mapping[str, Any]) -> pd.DataFrame:
    """Deterministic future drivers from history only (no realized future values).

    Flows: same month last year x clipped growth of the last 12 months over the
    12 before. States: carried forward from the last month. Zero columns stay 0.
    """
    hist = history.sort_values("timestamp").reset_index(drop=True)
    if len(hist) < 24:
        raise ForecastError("driver projection needs at least 24 months of history")
    lo, hi = policy["annual_growth_bounds"]
    last = hist["timestamp"].iloc[-1]
    dates = pd.date_range(last + pd.offsets.MonthBegin(1), periods=horizon, freq="MS")
    out = pd.DataFrame({"company_id": hist["company_id"].iloc[0], "timestamp": dates.astype("datetime64[ns]")})
    for col in policy["flow_columns"]:
        recent, prior = hist[col].iloc[-12:].sum(), hist[col].iloc[-24:-12].sum()
        growth = 0.0 if prior <= 0 else float(np.clip(recent / prior - 1.0, lo, hi))
        same_month_last_year = hist[col].iloc[-12:].to_numpy()
        out[col] = np.resize(same_month_last_year, horizon) * (1.0 + growth)
    for col in policy["state_columns"]:
        out[col] = hist[col].iloc[-1]
    for col in policy["zero_columns"]:
        out[col] = 0.0
    return out


def reconcile_scopes(history: pd.DataFrame, totals: np.ndarray, renewable_share: np.ndarray) -> pd.DataFrame:
    """Split predicted totals into scopes with trailing-12-month aggregate shares."""
    trailing = history.sort_values("timestamp").iloc[-12:]
    sums = np.array([trailing[c].sum() for c in SCOPE_COLUMNS], dtype=float)
    shares = np.full(3, 1 / 3) if sums.sum() <= 0 else sums / sums.sum()
    rows = []
    for total, r in zip(totals, renewable_share):
        s = shares.copy()
        if r >= 1.0:  # P0 market-based assumption: no scope2 at full renewable coverage
            s[1] = 0.0
            s = s / s.sum() if s.sum() > 0 else np.array([0.5, 0.0, 0.5])
        rows.append(s * total)
    frame = pd.DataFrame(rows, columns=list(SCOPE_COLUMNS))
    frame["total_co2e_tco2e"] = frame[list(SCOPE_COLUMNS)].sum(axis=1)
    return frame


def build_baseline(imported: ImportedHistory, artifacts: WS1Artifacts, horizon: int, policy: Mapping[str, Any],
                   *, data_kind: str, config_id: str, seed: int) -> BaselineBundle:
    cfg = imported.import_config
    history = imported.history
    drivers = project_drivers(history, horizon, policy)
    em, pr = artifacts.best_forecast("emissions"), artifacts.best_forecast("profit")
    expected = drivers["timestamp"].dt.strftime("%Y-%m").tolist()
    for key, frame in (("emissions", em), ("profit", pr)):
        if frame["date"].tolist() != expected:
            raise ForecastError(f"WS1 {key} forecast dates {frame['date'].tolist()} do not match the horizon {expected}")
    totals = em["prediction"].to_numpy(dtype=float)
    if not np.all(np.isfinite(totals)) or np.any(totals < 0):
        raise ForecastError("WS1 emissions forecast must be finite and non-negative")
    monthly = drivers.copy()
    scopes = reconcile_scopes(history, totals, monthly["renewable_energy_share"].to_numpy(dtype=float))
    for col in scopes.columns:
        monthly[col] = scopes[col].to_numpy()
    monthly["operating_profit_gbp"] = pr["prediction"].to_numpy(dtype=float) * cfg.gbp_per_eur
    for col in HISTORY_INT_COLUMNS:
        monthly[col] = monthly[col].round().astype("int64")
    for col in HISTORY_COLUMNS:
        if col not in ("company_id", "timestamp", *HISTORY_INT_COLUMNS):
            monthly[col] = monthly[col].astype("float64")
    monthly = monthly[list(HISTORY_COLUMNS)]
    history_end = history["timestamp"].iloc[-1].date()
    baseline = BaselineBundle(
        schema_version=SCHEMA_VERSION,
        run_id=f"baseline-run-{artifacts.model_id}",
        provenance=Provenance(
            provider=PROVIDER_NAME, is_mock=False, seed=seed,
            input_hash=canonical_hash([imported.csv_sha256, cfg.content_hash(), dict(policy)]),
            config_id=config_id, assumptions_id=None,
        ),
        baseline_id=f"baseline-{cfg.company_id}-{artifacts.model_id}",
        company_id=cfg.company_id,
        history_end=date(history_end.year, history_end.month, 1),
        horizon_months=horizon,
        model_id=artifacts.model_id,
        driver_policy_id=str(policy["policy_id"]),
        data_kind=data_kind,
        scope2_method=cfg.scope2_method,
        currency="GBP",
        monthly=monthly,
        totals={
            "revenue_gbp": float(monthly["revenue_gbp"].sum()),
            "operating_profit_gbp": float(monthly["operating_profit_gbp"].sum()),
            "total_co2e_tco2e": float(monthly["total_co2e_tco2e"].sum()),
        },
    )
    return val.validate_baseline(baseline)


def _metrics(actual: np.ndarray, pred: np.ndarray) -> tuple[float, float, float | None]:
    err = pred - actual
    ss = float(((actual - actual.mean()) ** 2).sum())
    r2 = None if len(actual) < 2 or ss == 0 else float(1 - (err ** 2).sum() / ss)
    return float(np.abs(err).mean()), float(np.sqrt((err ** 2).mean())), r2


def build_backtest(imported: ImportedHistory, artifacts: WS1Artifacts, *, config_id: str, seed: int,
                   driver_policy_id: str) -> BacktestReport:
    fx = imported.import_config.gbp_per_eur
    folds, oof, aggregate = [], [], {}
    for key, target in TARGET_KEYS.items():
        preds = artifacts.test_predictions[key]
        best = artifacts.best_models[key]
        b = preds[preds["model"] == best].set_index(["origin", "horizon"])
        n = preds[preds["model"] == NAIVE_MODEL].set_index(["origin", "horizon"])
        joined = b.join(n[["prediction"]].rename(columns={"prediction": "naive"}), how="inner")
        if len(joined) != len(b):
            raise ForecastError(f"WS1 {key}: seasonal-naive predictions do not cover every evaluated origin/horizon")
        scale = fx if key == "profit" else 1.0
        actual = joined["actual"].to_numpy(float) * scale
        predicted = joined["prediction"].to_numpy(float) * scale
        naive = joined["naive"].to_numpy(float) * scale
        mae, rmse, r2 = _metrics(actual, predicted)
        nmae, nrmse, _ = _metrics(actual, naive)
        aggregate[target] = {"mae": mae, "rmse": rmse, "r2": r2, "naive_mae": nmae, "naive_rmse": nrmse}
        frame = joined.reset_index().assign(actual=actual, predicted=predicted, naive_predicted=naive)
        for fold_id, (origin, g) in enumerate(frame.groupby("origin", sort=True)):
            a, p, nv = g["actual"].to_numpy(), g["predicted"].to_numpy(), g["naive_predicted"].to_numpy()
            fm, fr, f2 = _metrics(a, p)
            nm, nr, _ = _metrics(a, nv)
            folds.append({
                "fold_id": fold_id, "train_cutoff": pd.Timestamp(origin), "test_start": pd.Timestamp(g["target_date"].min()),
                "test_end": pd.Timestamp(g["target_date"].max()), "target": target, "mae": fm, "rmse": fr, "r2": f2,
                "naive_mae": nm, "naive_rmse": nr,
                "effective_train_size": int((imported.raw["date"] <= pd.Timestamp(origin)).sum()),
                "adjustment_count": 0,
            })
            for row in g.itertuples(index=False):
                oof.append({"fold_id": fold_id, "timestamp": pd.Timestamp(row.target_date), "target": target,
                            "actual": row.actual, "predicted": row.predicted, "naive_predicted": row.naive_predicted,
                            "horizon": int(row.horizon)})
    fold_frame = pd.DataFrame(folds, columns=list(BACKTEST_FOLD_SPEC)) if folds else empty_frame(BACKTEST_FOLD_SPEC)
    for col in ("train_cutoff", "test_start", "test_end"):
        fold_frame[col] = pd.to_datetime(fold_frame[col]).astype("datetime64[ns]")
    fold_frame["r2"] = fold_frame["r2"].astype("float64")
    oof_frame = pd.DataFrame(oof, columns=[*BACKTEST_OOF_SPEC, "horizon"])
    oof_frame["timestamp"] = pd.to_datetime(oof_frame["timestamp"]).astype("datetime64[ns]")
    report = BacktestReport(
        schema_version=SCHEMA_VERSION,
        run_id=f"backtest-{artifacts.model_id}",
        provenance=Provenance(provider=PROVIDER_NAME, is_mock=False, seed=seed, input_hash=imported.csv_sha256,
                              config_id=config_id, assumptions_id=None),
        model_family="ws1-ml_core walk-forward (" + ", ".join(sorted(set(artifacts.best_models.values()))) + ")",
        feature_spec_id="ws1-ml_core-relative-features",
        driver_policy_id=driver_policy_id,
        folds=fold_frame,
        aggregate_metrics=aggregate,
        oof_predictions=oof_frame,
        selected_models={TARGET_KEYS[k]: v for k, v in artifacts.best_models.items()},
    )
    return val.validate_backtest_report(report)
