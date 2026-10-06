"""WS1 model lifecycle: fit WS1's forecasters on the canonical history once, then reuse them.

WS1 (`ml_core/modelling.py`) owns the forecasters and the walk-forward evaluation.
This adapter only:

* forecasts the canonical columns (`total_co2e_tco2e`, `operating_profit_gbp` in GBP),
  so any imported dataset works, using whichever activity columns it reports as drivers,
* fits one model (RandomForest from 5 years of history, seasonal-naive below that, or the
  model named in the settings) and scores it against seasonal-naive on the last 12 months.
  Other models are compared only on request (`compare_models`); running every model at
  startup took ~5 minutes per dataset,
* persists the results (and the fitted trees SHAP needs) under `models/ws1/<model_id>/`,
  reused while data, mapping, settings, WS1 code and library versions are unchanged.

Training never runs at import time, and the process-level memo below keeps it off
dashboard reruns and slider changes.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import logging
import os
import pickle
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from src.contracts.errors import ForecastError

from .history import REPO_ROOT, ImportedHistory

logger = logging.getLogger(__name__)

TARGET_KEYS = {"emissions": "total_co2e_tco2e", "profit": "operating_profit_gbp"}
WS1_MODULE_PATH = Path("ml_core") / "modelling.py"
LIBRARIES = ("numpy", "pandas", "scikit-learn")
ARTIFACT_FORMAT = "ws1-artifacts-v2"
MODEL, BENCHMARK = "RandomForest", "SeasonalNaive"
MIN_TREE_MONTHS = 60  # below this the lagged features leave too few training rows
DRIVER_CANDIDATES = ("revenue_gbp", "electricity_kwh", "fleet_km", "renewable_energy_share", "ev_share")


def _ml_core():
    """Import WS1 lazily. Library load failures become a typed, actionable error."""
    try:
        return importlib.import_module("ml_core.modelling")
    except Exception as exc:  # XGBoost/LightGBM raise non-ImportError when OpenMP is missing
        raise ForecastError(
            f"WS1 forecasting libraries failed to load ({type(exc).__name__}: {str(exc).splitlines()[0][:160]}). "
            "On macOS install the OpenMP runtime (brew install libomp)."
        ) from exc


def _library_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in LIBRARIES:  # metadata only: importing these just to read a version is slow
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def model_frame(imported: ImportedHistory) -> pd.DataFrame:
    """The canonical history in the shape WS1 expects (a `date` column, numbers only)."""
    return imported.history.drop(columns="company_id").rename(columns={"timestamp": "date"})


def target_specs(history: pd.DataFrame) -> dict[str, Any]:
    """WS1 target descriptions for any canonical history; constant columns carry no signal."""
    mc = _ml_core()
    drivers = tuple(c for c in DRIVER_CANDIDATES if history[c].nunique() > 1)
    positive = bool((history["total_co2e_tco2e"] > 0).all())
    return {
        "emissions": mc.TargetSpec(column="total_co2e_tco2e", label="Total emissions", unit="tCO2e", positive=positive,
                                   scale_column=None if positive else "revenue_gbp", drivers=drivers),
        "profit": mc.TargetSpec(column="operating_profit_gbp", label="Operating profit", unit="GBP", positive=False,
                                scale_column="revenue_gbp", drivers=drivers),
    }


# WS1's models in its own order, with the optional library each needs (None: always available).
MODEL_LIBRARIES = (("XGBoost", "xgboost"), ("LightGBM", "lightgbm"), ("RandomForest", None), ("Prophet", "prophet"),
                   ("SeasonalNaive", None))


def available_models() -> tuple[str, ...]:
    """WS1 models whose library is installed. Checked without importing, so listing them costs nothing;
    a library that is installed but fails to load shows up as a model that cannot be scored."""
    return tuple(name for name, lib in MODEL_LIBRARIES if lib is None or importlib.util.find_spec(lib) is not None)


def compare_models(imported: ImportedHistory, settings: Mapping[str, Any], horizon: int, models: tuple[str, ...],
                   *, progress: Callable[[int, int], None] | None = None) -> pd.DataFrame:
    """Score each model the way the planning forecast is scored: walk-forward over the last
    `test_months`, refitting at every origin. Nothing is kept for planning. A model that cannot
    fit this data (e.g. too few months) gets NaN errors and its reason in `note`."""
    mc = _ml_core()
    data, specs = model_frame(imported), target_specs(imported.history)
    rows, total = [], len(models) * len(specs)
    for model in models:
        config = mc.ModellingConfig(horizon=horizon, test_months=int(settings["test_months"]), step=int(settings["step"]),
                                    seed=int(settings["seed"]), models=(model,))
        for key, spec in specs.items():
            started = time.perf_counter()
            row: dict[str, Any] = {"target": key, "model": model, "note": None}
            try:
                pipe = mc.ForecastingPipeline(key, data, config, spec=spec)
                pipe.split_data()
                metrics = pipe.evaluate_on_test()
                row.update(metrics[metrics["horizon"] == "all"].iloc[0][["mae", "rmse", "wape", "bias_pct"]].to_dict())
            except Exception as exc:  # one model failing on this data must not hide the others
                row.update(mae=float("nan"), rmse=float("nan"), wape=float("nan"), bias_pct=float("nan"),
                           note=f"{type(exc).__name__}: {str(exc)[:120]}")
            row["seconds"] = time.perf_counter() - started
            rows.append(row)
            if progress is not None:
                progress(len(rows), total)
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class WS1Artifacts:
    model_id: str
    identity: Mapping[str, Any]
    best_models: Mapping[str, str]                 # target key -> WS1 model name
    forecasts: Mapping[str, pd.DataFrame]          # WS1 forecast table per target (all models)
    test_predictions: Mapping[str, pd.DataFrame]   # held-out walk-forward predictions per target
    test_metrics: Mapping[str, pd.DataFrame]
    backtest_metrics: Mapping[str, pd.DataFrame]
    tree_models: Mapping[str, Mapping[str, Any]]   # target -> {"models": {h: estimator}, "feature_names": [...]}
    training_seconds: float
    trained_now: bool
    directory: str

    def best_forecast(self, key: str) -> pd.DataFrame:
        f = self.forecasts[key]
        return f[f["is_best"]].reset_index(drop=True)


def identity_for(imported: ImportedHistory, settings: Mapping[str, Any], horizon: int) -> dict[str, Any]:
    code = (REPO_ROOT / WS1_MODULE_PATH).read_bytes()
    return {
        "format": ARTIFACT_FORMAT,
        "csv_sha256": imported.csv_sha256,
        "import_config_sha256": imported.import_config.content_hash(),
        "ws1_code_sha256": hashlib.sha256(code).hexdigest(),
        "horizon_months": horizon,
        "settings": dict(sorted(settings.items())),
        "libraries": _library_versions(),
    }


def model_id_for(identity: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
    return f"ws1-{digest[:16]}"


def _train(imported: ImportedHistory, settings: Mapping[str, Any], horizon: int, out: Path,
           identity: Mapping[str, Any]) -> WS1Artifacts:
    mc = _ml_core()
    data = model_frame(imported)
    chosen = settings.get("model") or (MODEL if len(data) >= MIN_TREE_MONTHS else BENCHMARK)
    config = mc.ModellingConfig(
        horizon=horizon, test_months=int(settings["test_months"]), step=int(settings["step"]),
        seed=int(settings["seed"]), models=tuple(dict.fromkeys((chosen, BENCHMARK))),
        output_dir=out / "ws1_outputs",  # WS1 only writes here from save_results(), which is not called
    )
    started = time.perf_counter()
    forecasts, test_preds, test_metrics, bt_metrics, best, trees = {}, {}, {}, {}, {}, {}
    for key, spec in target_specs(imported.history).items():
        pipe = mc.ForecastingPipeline(key, data, config, spec=spec)
        try:
            pipe.split_data()
            pipe.evaluate_on_test()  # one fixed model scored against seasonal-naive; no selection
            pipe.best_model_name = chosen
            pipe.backtest_metrics = pipe.test_metrics
            pipe.fit_final_and_forecast()
        except Exception as exc:
            raise ForecastError(f"WS1 pipeline failed for target {key!r}: {type(exc).__name__}: {exc}") from exc
        forecasts[key], test_preds[key] = pipe.forecast, pipe.test_predictions
        test_metrics[key], bt_metrics[key], best[key] = pipe.test_metrics, pipe.backtest_metrics, pipe.best_model_name
        model = pipe.final_models[pipe.best_model_name]
        if isinstance(model, mc.DirectTreeForecaster):
            trees[key] = {"models": dict(model.models_), "feature_names": list(model.feature_names_)}
    seconds = time.perf_counter() - started
    final = out
    out = final.with_name(f"{final.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    for key in TARGET_KEYS:
        forecasts[key].to_csv(out / f"{key}_forecast.csv", index=False)
        test_preds[key].to_csv(out / f"{key}_test_predictions.csv", index=False)
        test_metrics[key].to_csv(out / f"{key}_test_metrics.csv", index=False)
        bt_metrics[key].to_csv(out / f"{key}_backtest_metrics.csv", index=False)
    with open(out / "tree_models.pkl", "wb") as handle:
        pickle.dump(trees, handle)
    model_id = model_id_for(identity)
    meta = {"model_id": model_id, "identity": identity, "best_models": best, "training_seconds": seconds,
            "tree_model_targets": sorted(trees)}
    (out / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    try:  # atomic publish; if another process already published this identity, keep theirs
        os.replace(out, final)
    except OSError:
        shutil.rmtree(out, ignore_errors=True)
    return WS1Artifacts(model_id, identity, best, forecasts, test_preds, test_metrics, bt_metrics, trees, seconds, True,
                        final.relative_to(REPO_ROOT).as_posix())


def _load(out: Path, identity: Mapping[str, Any]) -> WS1Artifacts | None:
    meta_path = out / "metadata.json"
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text())
    if json.loads(json.dumps(meta.get("identity"), default=str)) != json.loads(json.dumps(identity, default=str)):
        return None  # stale or foreign artifact: never reused
    read = lambda name, **kw: pd.read_csv(out / name, **kw)  # noqa: E731
    with open(out / "tree_models.pkl", "rb") as handle:  # trusted: written above for this exact identity
        trees = pickle.load(handle)
    return WS1Artifacts(
        meta["model_id"], identity, meta["best_models"],
        {k: read(f"{k}_forecast.csv") for k in TARGET_KEYS},
        {k: read(f"{k}_test_predictions.csv", parse_dates=["origin", "target_date"]) for k in TARGET_KEYS},
        {k: read(f"{k}_test_metrics.csv") for k in TARGET_KEYS},
        {k: read(f"{k}_backtest_metrics.csv") for k in TARGET_KEYS},
        trees, float(meta["training_seconds"]), False, out.relative_to(REPO_ROOT).as_posix(),
    )


_MEMO: dict[str, WS1Artifacts] = {}
_LOCK = threading.Lock()


def load_or_train(imported: ImportedHistory, settings: Mapping[str, Any], horizon: int, model_dir: str,
                  *, retrain: bool = False) -> WS1Artifacts:
    """Return compatible artifacts, training with WS1's pipeline only when needed."""
    identity = identity_for(imported, settings, horizon)
    model_id = model_id_for(identity)
    with _LOCK:
        if not retrain and model_id in _MEMO:
            return _MEMO[model_id]
        out = REPO_ROOT / model_dir / model_id
        artifacts = None if retrain else _load(out, identity)
        if artifacts is None:
            logger.info("Training WS1 models for %s (no compatible artifact found).", model_id)
            artifacts = _train(imported, settings, horizon, out, identity)
        _MEMO[model_id] = artifacts
        return artifacts


def tree_features(imported: ImportedHistory, target_key: str, horizon_step: int) -> pd.DataFrame:
    """WS1's own feature row at the forecast origin for one horizon (for SHAP)."""
    X, _, _, _ = _ml_core().build_supervised(model_frame(imported), target_specs(imported.history)[target_key], horizon_step)
    return X.iloc[[-1]]
