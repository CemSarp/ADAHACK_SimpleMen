"""WS1 model lifecycle: run WS1's own ForecastingPipeline once, then reuse it.

WS1 (`ml_core/modelling.py`) owns model candidates, walk-forward backtesting,
model selection and the final forecasts. This adapter only:

* runs the pipeline steps on the configured CSV in WS1's native units (EUR),
* persists the results (and the fitted tree regressors needed for SHAP) under
  `models/ws1/<model_id>/` with a metadata sidecar,
* reuses them when data, import mapping, settings, WS1 code and library
  versions are unchanged (the identity hash), and retrains otherwise.

Training never runs at import time, and the Streamlit services cache plus the
process-level memo below keep it off dashboard reruns and slider changes.
Only artifacts written by this pipeline with a matching identity are loaded.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import pickle
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.contracts.errors import ForecastError

from .history import REPO_ROOT, ImportedHistory

logger = logging.getLogger(__name__)

TARGET_KEYS = {"emissions": "total_co2e_tco2e", "profit": "operating_profit_gbp"}
WS1_MODULE_PATH = Path("ml_core") / "modelling.py"
LIBRARIES = ("numpy", "pandas", "sklearn", "xgboost", "lightgbm", "prophet")
ARTIFACT_FORMAT = "ws1-artifacts-v1"


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
    for name in LIBRARIES:
        try:
            versions[name] = str(importlib.import_module(name).__version__)
        except Exception:
            versions[name] = None
    return versions


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
    config = mc.ModellingConfig(
        horizon=horizon, test_months=int(settings["test_months"]), backtest_months=int(settings["backtest_months"]),
        step=int(settings["step"]), selection_metric=str(settings["selection_metric"]),
        interval=float(settings["interval"]), prophet_window=settings.get("prophet_window"), seed=int(settings["seed"]),
        output_dir=out / "ws1_outputs",  # WS1 only writes here from save_results(), which is not called
    )
    data = mc.prepare_data(imported.raw.copy())
    if len(data) != len(imported.raw):
        raise ForecastError("WS1 prepare_data changed the row count; the importer guarantees a gap-free series")
    started = time.perf_counter()
    forecasts, test_preds, test_metrics, bt_metrics, best, trees = {}, {}, {}, {}, {}, {}
    for key in TARGET_KEYS:
        pipe = mc.ForecastingPipeline(key, data, config)
        try:
            pipe.split_data()
            pipe.backtest()
            pipe.evaluate_on_test()
            pipe.select_best_model()
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
    mc = _ml_core()
    data = mc.prepare_data(imported.raw.copy())
    X, _, _, _ = mc.build_supervised(data, mc.TARGETS[target_key], horizon_step)
    return X.iloc[[-1]]
