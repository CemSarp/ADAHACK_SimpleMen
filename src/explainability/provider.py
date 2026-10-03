"""WS1 forecast SHAP provider discovered by src.integration.real_providers.

Explains the fitted WS1 tree regressors (one per horizon) on WS1's own feature
row at the forecast origin. Contributions are in WS1's RAW model output space,
which is relative, not tonnes or GBP:
  emissions: log(y[t+h] / trailing-12-month mean emissions)
  profit:    (EBITDA[t+h] - trailing mean) / trailing-12-month mean revenue
A target whose WS1-selected model is not a tree model (e.g. SeasonalNaive or
Prophet) is reported as unavailable instead of explaining a different model.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.contracts import validation as val
from src.contracts.errors import ForecastError
from src.contracts.serialization import SHAP_SPEC
from src.contracts.types import SCHEMA_VERSION, BaselineBundle, ExplanationResult, Provenance, ProviderInfo
from src.forecasting.provider import WS1ForecastProvider, create_forecast_provider
from src.forecasting.ws1_adapter import TARGET_KEYS, tree_features

__version__ = "ws1-shap-1"
UNITS = {
    "total_co2e_tco2e": "raw model output: log ratio to trailing 12-month mean emissions (dimensionless)",
    "operating_profit_gbp": "raw model output: EBITDA deviation from trailing 12-month mean / trailing mean revenue (dimensionless)",
}


class WS1ShapProvider:
    def __init__(self, forecast: WS1ForecastProvider) -> None:
        import importlib.util

        from src.contracts.errors import ContractValidationError

        try:  # optional dependency; absence (or a broken install) disables only this capability
            found = importlib.util.find_spec("shap") is not None
        except ImportError:
            found = False
        if not found:
            raise ContractValidationError("shap", "the shap package is not installed (see requirements-p1.txt)")
        self._forecast = forecast
        self.available_targets: tuple[str, ...] = tuple(TARGET_KEYS.values())
        self.info = ProviderInfo(slot="shap", name="ws1-shap-tree", version=f"{__version__}+{forecast.model_id}",
                                 is_mock=False, kind="real")

    def explain(self, baseline: BaselineBundle) -> ExplanationResult:
        import shap

        if baseline.model_id != self._forecast.model_id:  # checked before any model is loaded or trained
            raise ForecastError(
                f"baseline model {baseline.model_id} is not the explained WS1 model {self._forecast.model_id}")
        art = self._forecast.artifacts()
        rows = []
        unavailable = []
        dates = baseline.monthly["timestamp"].tolist()
        for key, target in TARGET_KEYS.items():
            tree = art.tree_models.get(key)
            if tree is None:
                unavailable.append(f"{target} (WS1 selected {art.best_models[key]}, not a tree model)")
                continue
            for h, model in sorted(tree["models"].items()):
                X = tree_features(self._forecast.imported, key, int(h))
                if list(X.columns) != list(tree["feature_names"]):
                    raise ForecastError(f"feature order changed for {target} h={h}; retrain WS1 artifacts")
                explainer = shap.TreeExplainer(model)
                values = np.asarray(explainer.shap_values(X)).reshape(-1)
                base = float(np.asarray(explainer.expected_value).reshape(-1)[0])
                raw = float(model.predict(X)[0])
                if not np.isclose(base + values.sum(), raw, rtol=1e-4, atol=1e-6):
                    raise ForecastError(f"SHAP additivity failed for {target} h={h}")
                for name, fv, sv in zip(X.columns, X.iloc[0].to_numpy(dtype=float), values):
                    rows.append({"timestamp": dates[int(h) - 1], "target": target, "feature": name,
                                 "feature_value": float(fv) if np.isfinite(fv) else None, "shap_value": float(sv),
                                 "base_value": base, "model_prediction": raw})
        if not rows:
            raise ForecastError("SHAP unavailable: " + "; ".join(unavailable))
        frame = pd.DataFrame(rows, columns=list(SHAP_SPEC))
        frame["timestamp"] = pd.to_datetime(frame["timestamp"]).astype("datetime64[ns]")
        result = ExplanationResult(
            schema_version=SCHEMA_VERSION, run_id=f"shap-{art.model_id}",
            provenance=Provenance(provider=self.info.name, is_mock=False, seed=None, input_hash=baseline.provenance.input_hash,
                                  config_id=baseline.provenance.config_id, assumptions_id=None),
            model_id=art.model_id, baseline_id=baseline.baseline_id, driver_policy_id=baseline.driver_policy_id,
            output_space="raw_model", units={t: UNITS[t] for t in frame["target"].unique()},
            explained_rows=len(dates), contributions=frame,
        )
        return val.validate_explanation(result)


def create_explanation_provider(path: str | None = None) -> WS1ShapProvider:
    return WS1ShapProvider(create_forecast_provider(path))
