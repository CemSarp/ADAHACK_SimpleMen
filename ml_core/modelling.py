"""Multi-target forecasting: model comparison, backtesting and 3-month forecasts.

The pipeline forecasts the next three months of two monthly targets:

* ``emissions``: total GHG emissions (``total_emissions_tco2e``, tCO2e),
* ``profit``: EBITDA (``ebitda_eur``, EUR), which can be negative.

For every target it:

1. prepares the data (sorts, removes duplicate months, fills missing months
   and cells by interpolation),
2. holds out the last months as a test set,
3. backtests every candidate model with a walk-forward (expanding window)
   scheme on the training period,
4. evaluates every model on the held-out test period with the same scheme,
5. selects the best model on the backtest score,
6. refits *every* model on all data and forecasts month 1, 2 and 3 with
   empirical prediction intervals (the best model is flagged),
7. saves metrics, predictions, forecasts and plots to
   ``temp_outputs/modelling_results/<target>``, plus a combined
   ``forecast.csv`` and ``summary.json``.

Tree models (XGBoost, LightGBM, Random Forest) use a *direct* multi-horizon
strategy: one model per horizon. They predict the future value relative to the
current 12-month average level, so they can follow the trend even though trees
cannot extrapolate. For strictly positive targets (emissions) this is the
log-ratio ``log(y[t+h] / level_t)``; for targets that can be negative (profit)
it is the additive deviation ``(y[t+h] - level_t) / scale_t``, where
``scale_t`` is the 12-month average of a positive reference series (revenue),
i.e. a change in margin. Prophet models the series (log-transformed when
positive) over a recent window so that old trend regimes do not bias it. A
seasonal-naive model with drift is included as a baseline.

Example:
    >>> summary = run_all()
    >>> summary["targets"]["emissions"]["forecast"]["month1"]
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from synthetic_data_generation.synthetic_data_generator import (
    GeneratorConfig,
    SupplyChainDataGenerator,
)

try:
    from xgboost import XGBRegressor
except ImportError:
    XGBRegressor = None
try:
    from lightgbm import LGBMRegressor
except ImportError:
    LGBMRegressor = None
try:
    from prophet import Prophet
except ImportError:
    Prophet = None

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TargetSpec:
    """Description of a forecast target.

    Attributes:
        column: Column to forecast.
        label: Human-readable name used in plots and reports.
        unit: Unit of the column.
        positive: Whether the target is strictly positive. Positive targets are
            modelled multiplicatively (log-ratios), others additively.
        scale_column: Positive column whose 12-month mean normalises additive
            targets. Unused for positive targets.
        drivers: Exogenous columns whose recent values are used as features.
        display_scale: Divisor applied to values in plots.
        display_unit: Unit shown in plots after dividing by ``display_scale``.
    """

    column: str
    label: str
    unit: str
    positive: bool
    scale_column: str | None = None
    drivers: tuple[str, ...] = ()
    display_scale: float = 1.0
    display_unit: str = ""


TARGETS = {
    "emissions": TargetSpec(
        column="total_emissions_tco2e",
        label="Total emissions",
        unit="tCO2e",
        positive=True,
        drivers=("freight_volume_tkm", "air_share", "road_share", "fleet_ev_share",
                 "renewable_energy_share", "load_factor"),
        display_unit="tCO2e",
    ),
    "profit": TargetSpec(
        column="ebitda_eur",
        label="Profit (EBITDA)",
        unit="EUR",
        positive=False,
        scale_column="revenue_eur",
        drivers=("revenue_eur", "operating_cost_eur", "freight_volume_tkm",
                 "diesel_price_eur_per_l", "electricity_price_eur_per_kwh",
                 "carbon_price_eur_per_t", "air_share", "load_factor"),
        display_scale=1e6,
        display_unit="M EUR",
    ),
}

# Fixed colour per model (categorical palette, fixed order).
MODEL_COLORS = {
    "XGBoost": "#2a78d6",
    "LightGBM": "#eb6834",
    "RandomForest": "#1baf7a",
    "Prophet": "#eda100",
    "SeasonalNaive": "#e87ba4",
}
COLOR_ACTUAL = "#0b0b0b"
COLOR_GRID = "#e4e3df"
COLOR_MUTED = "#898781"

METRIC_COLUMNS = ["mae", "rmse", "wape", "mape", "bias_pct"]


# --------------------------------------------------------------------------- #
# Data preparation and features
# --------------------------------------------------------------------------- #


def prepare_data(df: pd.DataFrame) -> pd.DataFrame:
    """Makes a monthly dataset regular and gap-free.

    Rows are sorted by date, duplicate months are dropped (first kept), missing
    months are inserted, and missing numeric cells are filled by linear
    interpolation (edges by the nearest value).

    Args:
        df: Monthly data with a ``date`` column.

    Returns:
        A dataset with one row per month start and no missing numeric values.
    """
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.to_period("M").dt.to_timestamp()
    n_dup = int(out["date"].duplicated().sum())
    out = out.sort_values("date", kind="stable").drop_duplicates("date", keep="first")
    full = pd.date_range(out["date"].iloc[0], out["date"].iloc[-1], freq="MS")
    out = out.set_index("date").reindex(full)
    numeric = out.select_dtypes("number").columns
    n_missing = int(out[numeric].isna().sum().sum())
    out[numeric] = out[numeric].interpolate(method="linear", limit_direction="both")
    if n_dup or n_missing:
        logger.info("Data preparation: dropped %d duplicate months, filled %d missing cells.",
                    n_dup, n_missing)
    return out.rename_axis("date").reset_index()


def build_supervised(
    df: pd.DataFrame, spec: TargetSpec, h: int
) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """Builds scale-free features and the horizon-``h`` target.

    All target-based features are expressed relative to the trailing 12-month
    mean (``level``): as ratios for positive targets and as deviations divided
    by ``scale`` otherwise. This removes the growth trend and lets tree models
    generalise to levels they have never seen.

    Args:
        df: Monthly data with a ``date`` column, the target and the drivers.
        spec: Target description.
        h: Forecast horizon in months.

    Returns:
        A tuple ``(X, y, level, scale)``: features indexed by origin, the
        relative target (NaN where unknown), the level and the scale. Use
        :func:`from_relative` to map predictions back to target units.
    """
    y = df[spec.column]
    level = y.rolling(12).mean()
    scale = level if spec.positive else df[spec.scale_column].rolling(12).mean()

    def rel(v: pd.Series) -> pd.Series:
        return v / level if spec.positive else (v - level) / scale

    X = pd.DataFrame(index=df.index)
    for k in range(6):
        X[f"y_lag{k}_rel"] = rel(y.shift(k))
    X["seasonal_ref_rel"] = rel(y.shift(12 - h))
    X["seasonal_ref2_rel"] = rel(y.shift(24 - h))
    if spec.positive:
        X["level_growth_12m"] = level / level.shift(12) - 1
        X["level_growth_3m"] = level / level.shift(3) - 1
    else:
        X["level_margin"] = level / scale
        X["level_change_12m"] = (level - level.shift(12)) / scale
        X["level_change_3m"] = (level - level.shift(3)) / scale
    for col in spec.drivers:
        s = df[col]
        if col.endswith("_share") or col == "load_factor":
            X[col] = s
            X[f"{col}_diff_12m"] = s - s.shift(12)
        else:
            s_level = s.rolling(12).mean()
            X[f"{col}_rel"] = s / s_level
            # Drivers such as the carbon price can be exactly 0 for a stretch
            # (e.g. before a carbon tax exists), which would make this growth
            # ratio divide by 0 (-> inf) once the driver turns positive again.
            # Those rows carry no meaningful "% growth" and are set to NaN so
            # the row-level mask drops them instead of feeding inf to a model.
            X[f"{col}_growth_12m"] = s_level / s_level.shift(12).replace(0, np.nan) - 1
    target_month = (df["date"].dt.month - 1 + h) % 12
    X["target_month"] = target_month + 1
    X["target_month_sin"] = np.sin(2 * np.pi * target_month / 12)
    X["target_month_cos"] = np.cos(2 * np.pi * target_month / 12)
    y_rel = np.log(y.shift(-h) / level) if spec.positive else (y.shift(-h) - level) / scale
    return X, y_rel, level, scale


def from_relative(pred: float, level: float, scale: float, spec: TargetSpec) -> float:
    """Maps a relative prediction from :func:`build_supervised` to target units.

    Args:
        pred: Relative prediction.
        level: Trailing 12-month mean of the target at the origin.
        scale: Normalising scale at the origin.
        spec: Target description.

    Returns:
        The prediction in the target's units.
    """
    return level * np.exp(pred) if spec.positive else level + scale * pred


# --------------------------------------------------------------------------- #
# Forecasters
# --------------------------------------------------------------------------- #


class BaseForecaster:
    """Interface for multi-horizon forecasters.

    A forecaster is fitted on a history (all rows up to the forecast origin)
    and predicts the target for the ``horizon`` months after the last row.

    Attributes:
        name: Display name of the model.
        spec: Target description.
        horizon: Number of months to forecast.
    """

    name = "Base"

    def __init__(self, spec: TargetSpec, horizon: int = 3) -> None:
        """Initialises the forecaster.

        Args:
            spec: Target description.
            horizon: Number of months to forecast.
        """
        self.spec = spec
        self.horizon = horizon

    def fit(self, history: pd.DataFrame) -> BaseForecaster:
        """Fits the model on the history.

        Args:
            history: Monthly data up to and including the forecast origin.

        Returns:
            The fitted forecaster.
        """
        raise NotImplementedError

    def predict(self, history: pd.DataFrame) -> np.ndarray:
        """Forecasts the months after the last row of ``history``.

        Args:
            history: Monthly data up to and including the forecast origin.

        Returns:
            Array of length ``horizon`` with the forecasts for month 1..h.
        """
        raise NotImplementedError


class DirectTreeForecaster(BaseForecaster):
    """Direct multi-horizon forecaster built on a tree-based regressor.

    One regressor is trained per horizon ``h`` on samples
    ``(features at t) -> relative target at t+h`` (see
    :func:`build_supervised`). Predictions are mapped back with
    :func:`from_relative`.
    """

    def __init__(
        self,
        name: str,
        estimator_factory: Callable[[], object],
        spec: TargetSpec,
        horizon: int = 3,
    ) -> None:
        """Initialises the forecaster.

        Args:
            name: Display name of the model.
            estimator_factory: Callable returning a new, unfitted scikit-learn
                compatible regressor.
            spec: Target description.
            horizon: Number of months to forecast.
        """
        super().__init__(spec, horizon)
        self.name = name
        self.estimator_factory = estimator_factory
        self.models_: dict[int, object] = {}
        self.feature_names_: list[str] = []

    def fit(self, history: pd.DataFrame) -> DirectTreeForecaster:
        """Fits one regressor per horizon.

        Args:
            history: Monthly data up to and including the forecast origin.

        Returns:
            The fitted forecaster.
        """
        for h in range(1, self.horizon + 1):
            X, y, _, _ = build_supervised(history, self.spec, h)
            # np.isfinite (not just notna) so a stray inf/-inf never reaches
            # the estimator; XGBoost raises on non-finite input otherwise.
            mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
            model = self.estimator_factory()
            model.fit(X[mask], y[mask])
            self.models_[h] = model
            self.feature_names_ = list(X.columns)
        return self

    def predict(self, history: pd.DataFrame) -> np.ndarray:
        """Forecasts month 1..h from the last row of ``history``.

        Args:
            history: Monthly data up to and including the forecast origin.

        Returns:
            Forecasts in the target's units.
        """
        preds = []
        for h in range(1, self.horizon + 1):
            X, _, level, scale = build_supervised(history, self.spec, h)
            rel = self.models_[h].predict(X.iloc[[-1]])[0]
            preds.append(from_relative(rel, level.iloc[-1], scale.iloc[-1], self.spec))
        return np.array(preds)

    def feature_importance(self) -> pd.DataFrame:
        """Returns feature importances averaged over the horizon models.

        Returns:
            DataFrame with ``feature`` and normalised ``importance`` columns,
            sorted in descending order.
        """
        imp = np.mean([m.feature_importances_ for m in self.models_.values()], axis=0)
        imp = imp / imp.sum() if imp.sum() > 0 else imp
        return (pd.DataFrame({"feature": self.feature_names_, "importance": imp})
                .sort_values("importance", ascending=False, ignore_index=True))


class ProphetForecaster(BaseForecaster):
    """Univariate Prophet model fitted on a recent window.

    Positive targets are log-transformed, which makes the additive seasonality
    multiplicative and keeps forecasts positive. Fitting on the last
    ``window`` months only stops old trend regimes from biasing the trend
    extrapolation.
    """

    name = "Prophet"

    def __init__(self, spec: TargetSpec, horizon: int = 3, window: int | None = 96) -> None:
        """Initialises the forecaster.

        Args:
            spec: Target description.
            horizon: Number of months to forecast.
            window: Number of most recent months used for fitting (``None``
                for the full history).
        """
        super().__init__(spec, horizon)
        self.window = window
        self.model_ = None

    def fit(self, history: pd.DataFrame) -> ProphetForecaster:
        """Fits Prophet on the (transformed) target series.

        Args:
            history: Monthly data up to and including the forecast origin.

        Returns:
            The fitted forecaster.
        """
        recent = history.iloc[-self.window:] if self.window else history
        y = recent[self.spec.column]
        self.model_ = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=False,
            daily_seasonality=False,
            seasonality_mode="additive",
            changepoint_prior_scale=0.05,
        )
        self.model_.fit(pd.DataFrame({"ds": recent["date"],
                                      "y": np.log(y) if self.spec.positive else y}))
        return self

    def predict(self, history: pd.DataFrame) -> np.ndarray:
        """Forecasts the months after the last row of ``history``.

        Args:
            history: Monthly data up to and including the forecast origin.

        Returns:
            Forecasts in the target's units.
        """
        last = history["date"].iloc[-1]
        future = pd.DataFrame({"ds": [last + pd.DateOffset(months=h)
                                      for h in range(1, self.horizon + 1)]})
        yhat = self.model_.predict(future)["yhat"].to_numpy()
        return np.exp(yhat) if self.spec.positive else yhat


class SeasonalNaiveForecaster(BaseForecaster):
    """Baseline: same month last year, adjusted by the year-over-year change.

    Positive targets are scaled by the ratio of the last two 12-month means,
    other targets are shifted by their difference.
    """

    name = "SeasonalNaive"

    def fit(self, history: pd.DataFrame) -> SeasonalNaiveForecaster:
        """No-op; the baseline has no parameters.

        Args:
            history: Monthly data up to and including the forecast origin.

        Returns:
            The forecaster itself.
        """
        return self

    def predict(self, history: pd.DataFrame) -> np.ndarray:
        """Forecasts ``y[t+h-12]`` adjusted by the change in the 12-month level.

        Args:
            history: Monthly data up to and including the forecast origin.

        Returns:
            Forecasts in the target's units.
        """
        y = history[self.spec.column].to_numpy(dtype=float)
        level, prev_level = np.nanmean(y[-12:]), np.nanmean(y[-24:-12])
        base = np.array([y[-12 + h - 1] for h in range(1, self.horizon + 1)])
        if self.spec.positive:
            return base * level / prev_level
        return base + (level - prev_level)


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


@dataclass
class ModellingConfig:
    """Configuration for :class:`ForecastingPipeline` and :func:`run_all`.

    Attributes:
        targets: Keys of :data:`TARGETS` to forecast.
        horizon: Number of months to forecast (month1..monthN).
        test_months: Number of final months held out as the test set.
        backtest_months: Number of final training months used as backtest
            targets (walk-forward validation).
        step: Months between consecutive forecast origins.
        selection_metric: Metric (``"wape"``, ``"mae"`` or ``"rmse"``) used to
            pick the best model on the backtest. WAPE is used by default
            because MAPE is undefined for targets that cross zero.
        interval: Coverage of the empirical prediction interval.
        prophet_window: Months of recent history Prophet is fitted on.
        seed: Random seed for the models.
        output_dir: Directory where all results are saved.
        generator_config: Configuration of the synthetic data generator.
        models: Names of the models to run; ``None`` runs every available one.
    """

    targets: tuple[str, ...] = ("emissions", "profit")
    horizon: int = 3
    test_months: int = 24
    backtest_months: int = 6
    step: int = 1
    selection_metric: str = "wape"
    interval: float = 0.8
    prophet_window: int | None = 96
    seed: int = 42
    output_dir: Path = Path(__file__).resolve().parent / "temp_outputs" / "modelling_results"
    generator_config: GeneratorConfig = field(default_factory=GeneratorConfig)
    models: tuple[str, ...] | None = None


class ForecastingPipeline:
    """Compares, backtests and deploys models for one monthly target.

    Attributes:
        config: Pipeline configuration.
        spec: Target description.
        key: Target key (also the name of the output sub-directory).
        data: Full prepared dataset.
        train: Training part of the data (set by :meth:`split_data`).
        test: Held-out test part of the data.
        backtest_predictions: Walk-forward predictions on the training period.
        test_predictions: Walk-forward predictions on the test period.
        backtest_metrics: Metrics per model and horizon on the backtest.
        test_metrics: Metrics per model and horizon on the test period.
        best_model_name: Name of the selected model.
        final_models: Every model refitted on all data.
        forecast: Forecast table of every model for month1..monthN.
    """

    def __init__(self, key: str, data: pd.DataFrame,
                 config: ModellingConfig | None = None, spec: TargetSpec | None = None) -> None:
        """Initialises the pipeline and registers the available models.

        Args:
            key: Key of the target in :data:`TARGETS` (also the output sub-directory).
            data: Prepared monthly dataset (see :func:`prepare_data`).
            config: Pipeline configuration. Defaults to :class:`ModellingConfig`.
            spec: Target description for any other dataset. Defaults to ``TARGETS[key]``.
        """
        self.config = config or ModellingConfig()
        self.key = key
        self.spec = spec or TARGETS[key]
        self.data = data
        self.models = self._default_models()
        self.train: pd.DataFrame | None = None
        self.test: pd.DataFrame | None = None
        self.backtest_predictions: pd.DataFrame | None = None
        self.test_predictions: pd.DataFrame | None = None
        self.backtest_metrics: pd.DataFrame | None = None
        self.test_metrics: pd.DataFrame | None = None
        self.best_model_name: str | None = None
        self.final_models: dict[str, BaseForecaster] = {}
        self.forecast: pd.DataFrame | None = None

    @property
    def output_dir(self) -> Path:
        """Directory where this target's results are saved."""
        return Path(self.config.output_dir) / self.key

    # ------------------------------------------------------------------ #
    # Steps
    # ------------------------------------------------------------------ #

    def run(self) -> dict:
        """Runs the full pipeline for this target and saves all results.

        Returns:
            The summary dictionary that is also written to ``summary.json``.
        """
        logger.info("=== Target: %s (%s) ===", self.key, self.spec.column)
        started = time.perf_counter()
        self.split_data()
        self.backtest()
        self.evaluate_on_test()
        self.select_best_model()
        self.fit_final_and_forecast()
        summary = self.save_results()
        self.report()
        logger.info("Target %s finished in %.1fs.", self.key, time.perf_counter() - started)
        return summary

    def split_data(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Splits the data chronologically into training and test sets.

        Returns:
            A tuple ``(train, test)``.
        """
        cut = len(self.data) - self.config.test_months
        self.train, self.test = self.data.iloc[:cut], self.data.iloc[cut:]
        logger.info("Train: %d months, test: %d months (from %s).", len(self.train),
                    len(self.test), self.test["date"].iloc[0].date())
        return self.train, self.test

    def backtest(self) -> pd.DataFrame:
        """Walk-forward backtest of every model on the training period.

        At each origin the model is refitted on all training data up to that
        origin and forecasts the next ``horizon`` months. Origins are chosen so
        that every month of the last ``backtest_months`` of the training set is
        a target at horizon 1 (and at later horizons where possible); no test
        data is touched.

        Returns:
            Backtest metrics per model and horizon.
        """
        cfg = self.config
        n = len(self.train)
        origins = range(n - cfg.backtest_months - 1, n - 1, cfg.step)
        self.backtest_predictions = self._walk_forward_all(self.train, origins, "backtest")
        self.backtest_metrics = self.compute_metrics(self.backtest_predictions)
        return self.backtest_metrics

    def evaluate_on_test(self) -> pd.DataFrame:
        """Walk-forward evaluation of every model on the held-out test period.

        The first origin is the last training month; each later origin adds
        one more observed test month to the history (as would happen in
        production). Every test month is a target at horizon 1, and all
        forecast targets lie in the test period.

        Returns:
            Test metrics per model and horizon.
        """
        origins = range(len(self.train) - 1, len(self.data) - 1, self.config.step)
        self.test_predictions = self._walk_forward_all(self.data, origins, "test")
        self.test_metrics = self.compute_metrics(self.test_predictions)
        return self.test_metrics

    def select_best_model(self) -> str:
        """Selects the model with the lowest backtest error over all horizons.

        Selection uses the backtest only, so the test score of the selected
        model stays an unbiased estimate.

        Returns:
            Name of the best model.
        """
        metric = self.config.selection_metric
        overall = self.backtest_metrics[self.backtest_metrics["horizon"] == "all"]
        best = overall.sort_values(metric).iloc[0]
        self.best_model_name = best["model"]
        logger.info("Best model on backtest: %s (%s = %.3f).", self.best_model_name,
                    metric, best[metric])
        return self.best_model_name

    def fit_final_and_forecast(self) -> pd.DataFrame:
        """Refits every model on all data and forecasts the next months.

        Prediction intervals are empirical and per model: for each horizon the
        quantiles of the errors observed in that model's backtest and test
        walk-forwards are applied to its point forecast. Errors are ratios
        ``actual / prediction`` for positive targets and differences
        ``actual - prediction`` otherwise.

        Returns:
            Forecast table with one row per model and month (``month1``..).
        """
        cfg = self.config
        last = self.data["date"].iloc[-1]
        pct = int(round(cfg.interval * 100))
        alpha = (1 - cfg.interval) / 2
        past = pd.concat([self.backtest_predictions, self.test_predictions])
        rows = []
        for name, factory in self.models.items():
            model = factory().fit(self.data)
            self.final_models[name] = model
            point = model.predict(self.data)
            errors = past[past["model"] == name]
            for h in range(1, cfg.horizon + 1):
                e = errors[errors["horizon"] == h]
                if self.spec.positive:
                    lo, hi = (e["actual"] / e["prediction"]).quantile([alpha, 1 - alpha])
                    lower, upper = point[h - 1] * lo, point[h - 1] * hi
                else:
                    lo, hi = (e["actual"] - e["prediction"]).quantile([alpha, 1 - alpha])
                    lower, upper = point[h - 1] + lo, point[h - 1] + hi
                rows.append({
                    "target": self.key,
                    "column": self.spec.column,
                    "unit": self.spec.unit,
                    "model": name,
                    "is_best": name == self.best_model_name,
                    "step": f"month{h}",
                    "date": (last + pd.DateOffset(months=h)).strftime("%Y-%m"),
                    "prediction": point[h - 1],
                    f"lower_{pct}": lower,
                    f"upper_{pct}": upper,
                })
        self.forecast = pd.DataFrame(rows)
        return self.forecast

    @property
    def best_forecast(self) -> pd.DataFrame:
        """Forecast rows of the selected model."""
        return self.forecast[self.forecast["is_best"]].reset_index(drop=True)

    # ------------------------------------------------------------------ #
    # Evaluation helpers
    # ------------------------------------------------------------------ #

    def _walk_forward_all(self, data: pd.DataFrame, origins: range, phase: str) -> pd.DataFrame:
        """Runs a walk-forward evaluation for every registered model.

        Args:
            data: Dataset providing history and actuals.
            origins: Integer positions of the forecast origins in ``data``.
            phase: Label for logging (``"backtest"`` or ``"test"``).

        Returns:
            Long table of predictions for all models.
        """
        frames = []
        for name, factory in self.models.items():
            start = time.perf_counter()
            frames.append(self._walk_forward(name, factory, data, origins))
            logger.info("%s %-8s %-13s %d origins in %.1fs", phase, self.key, name,
                        len(origins), time.perf_counter() - start)
        return pd.concat(frames, ignore_index=True)

    def _walk_forward(
        self,
        name: str,
        factory: Callable[[], BaseForecaster],
        data: pd.DataFrame,
        origins: range,
    ) -> pd.DataFrame:
        """Refits a model at every origin and collects its forecasts.

        Forecasts whose target month lies beyond ``data`` are discarded.

        Args:
            name: Model name.
            factory: Callable returning a new, unfitted forecaster.
            data: Dataset providing history and actuals.
            origins: Integer positions of the forecast origins in ``data``.

        Returns:
            Table with one row per origin and horizon.
        """
        rows = []
        target = data[self.spec.column].to_numpy()
        for o in origins:
            history = data.iloc[: o + 1]
            preds = factory().fit(history).predict(history)
            for h, pred in enumerate(preds, start=1):
                if o + h >= len(data):
                    break
                rows.append({
                    "model": name,
                    "origin": data["date"].iloc[o],
                    "target_date": data["date"].iloc[o + h],
                    "horizon": h,
                    "actual": target[o + h],
                    "prediction": pred,
                })
        return pd.DataFrame(rows)

    def compute_metrics(self, predictions: pd.DataFrame) -> pd.DataFrame:
        """Computes error metrics per model and horizon, plus over all horizons.

        WAPE and bias are relative to the summed absolute actuals, so they stay
        meaningful for targets that cross zero. MAPE is only reported for
        positive targets (NaN otherwise).

        Args:
            predictions: Long table with ``model``, ``horizon``, ``actual`` and
                ``prediction`` columns.

        Returns:
            Table with MAE, RMSE, WAPE (%), MAPE (%) and bias (%) per model and
            horizon (``"all"`` for the pooled horizons).
        """
        def _metrics(g: pd.DataFrame) -> dict:
            err = g["prediction"] - g["actual"]
            denom = g["actual"].abs().sum()
            return {
                "mae": err.abs().mean(),
                "rmse": np.sqrt((err ** 2).mean()),
                "wape": err.abs().sum() / denom * 100,
                "mape": ((err.abs() / g["actual"].abs()).mean() * 100
                         if self.spec.positive else np.nan),
                "bias_pct": err.sum() / denom * 100,
                "n": len(g),
            }

        rows = [{"model": m, "horizon": str(h), **_metrics(g)}
                for (m, h), g in predictions.groupby(["model", "horizon"])]
        rows += [{"model": m, "horizon": "all", **_metrics(g)}
                 for m, g in predictions.groupby("model")]
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #

    def _metric_columns(self) -> list[str]:
        """Metric columns that are defined for this target."""
        return [c for c in METRIC_COLUMNS if self.spec.positive or c != "mape"]

    def report(self) -> None:
        """Prints backtest and test metrics, the best model and the forecasts."""
        metric = self.config.selection_metric
        cols = ["model", *self._metric_columns()]
        fmt = {"float_format": lambda v: f"{v:,.2f}", "index": False}
        bt = self.backtest_metrics[self.backtest_metrics["horizon"] == "all"]
        te = self.test_metrics[self.test_metrics["horizon"] == "all"]
        print(f"\n######## {self.spec.label} ({self.spec.column}, {self.spec.unit}) ########")
        print("\n=== Backtest (walk-forward on training period, all horizons) ===")
        print(bt[cols].sort_values(metric).to_string(**fmt))
        print("\n=== Test (held-out period, all horizons) ===")
        print(te[cols].sort_values(metric).to_string(**fmt))
        print(f"\nBest model (selected on backtest {metric}): {self.best_model_name}")
        best = self.test_metrics[self.test_metrics["model"] == self.best_model_name]
        print(best[["horizon", *self._metric_columns()]].to_string(**fmt))
        print(f"\n=== Forecast, all models ({self.spec.unit}) ===")
        table = self.forecast.pivot(index="model", columns="step", values="prediction")
        table.index = [f"{m} *" if m == self.best_model_name else m for m in table.index]
        print(table.to_string(float_format=lambda v: f"{v:,.0f}"))
        print(f"\n=== Forecast, best model: {self.best_model_name} ===")
        print(self.best_forecast.drop(columns=["target", "column", "unit", "model", "is_best"])
              .to_string(**fmt))

    def save_results(self) -> dict:
        """Saves tables, plots and a JSON summary to the target's output directory.

        Returns:
            The summary dictionary.
        """
        out = self.output_dir
        out.mkdir(parents=True, exist_ok=True)
        self.backtest_metrics.to_csv(out / "backtest_metrics.csv", index=False)
        self.test_metrics.to_csv(out / "test_metrics.csv", index=False)
        self.backtest_predictions.to_csv(out / "backtest_predictions.csv", index=False)
        self.test_predictions.to_csv(out / "test_predictions.csv", index=False)
        self.forecast.to_csv(out / "forecast.csv", index=False)
        best_model = self.final_models[self.best_model_name]
        if isinstance(best_model, DirectTreeForecaster):
            best_model.feature_importance().to_csv(
                out / "best_model_feature_importance.csv", index=False)

        for name, fig in (("metric_comparison.png", self.plot_metric_comparison()),
                          ("test_predictions.png", self.plot_test_predictions()),
                          ("forecast.png", self.plot_forecast())):
            fig.savefig(out / name, dpi=150, bbox_inches="tight")
            plt.close(fig)

        metric_cols = self._metric_columns()

        def _overall(metrics: pd.DataFrame) -> dict:
            rows = metrics[metrics["horizon"] == "all"].set_index("model")
            return rows[metric_cols].round(3).to_dict("index")

        def _forecast(rows: pd.DataFrame) -> dict:
            keep = [c for c in rows.columns
                    if c not in ("target", "column", "unit", "model", "is_best", "step")]
            return {r["step"]: {k: (round(r[k], 2) if isinstance(r[k], float) else r[k])
                                for k in keep}
                    for r in rows.to_dict("records")}

        best_test = self.test_metrics[self.test_metrics["model"] == self.best_model_name]
        summary = _json_safe({
            "target": self.spec.column,
            "label": self.spec.label,
            "unit": self.spec.unit,
            "data_range": [str(self.data["date"].iloc[0].date()),
                           str(self.data["date"].iloc[-1].date())],
            "test_start": str(self.test["date"].iloc[0].date()),
            "selection_metric": self.config.selection_metric,
            "best_model": self.best_model_name,
            "backtest_metrics": _overall(self.backtest_metrics),
            "test_metrics": _overall(self.test_metrics),
            "best_model_test_metrics_by_horizon": (
                best_test.set_index("horizon")[metric_cols].round(3).to_dict("index")),
            "forecast": _forecast(self.best_forecast),
            "forecast_all_models": {m: _forecast(g) for m, g in
                                    self.forecast.groupby("model", sort=False)},
        })
        with open(out / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        return summary

    # ------------------------------------------------------------------ #
    # Plots
    # ------------------------------------------------------------------ #

    def _display(self, values):
        """Scales values for plotting."""
        return values / self.spec.display_scale

    def plot_metric_comparison(self) -> plt.Figure:
        """Plots the pooled selection metric per model for backtest and test.

        Returns:
            The bar-chart figure.
        """
        metric = self.config.selection_metric
        bt = self.backtest_metrics.query("horizon == 'all'").set_index("model")[metric]
        te = self.test_metrics.query("horizon == 'all'").set_index("model")[metric]
        order = bt.sort_values().index
        x = np.arange(len(order))
        fig, ax = plt.subplots(figsize=(9, 4.5))
        width = 0.38
        is_pct = metric in ("wape", "mape")
        for offset, series, label, color in ((-width / 2, bt, "Backtest", "#2a78d6"),
                                             (width / 2, te, "Test", "#eb6834")):
            bars = ax.bar(x + offset, series[order], width - 0.04, label=label, color=color)
            ax.bar_label(bars, fmt="%.1f%%" if is_pct else "%.0f", fontsize=8, padding=2,
                         color=COLOR_ACTUAL)
        ax.set_xticks(x, [f"{m} (best)" if m == self.best_model_name else m for m in order])
        ax.set_ylabel(f"{metric.upper()}, months 1-{self.config.horizon} pooled"
                      + (" (%)" if is_pct else ""))
        ax.set_title(f"{self.spec.label}: forecast error by model (lower is better)", loc="left")
        ax.legend(frameon=False, ncol=2, loc="lower right", bbox_to_anchor=(1.0, 1.0))
        self._style_axis(ax)
        fig.tight_layout()
        return fig

    def plot_test_predictions(self) -> plt.Figure:
        """Plots 1-month-ahead test predictions of every model against actuals.

        Returns:
            The line-chart figure.
        """
        preds = self.test_predictions.query("horizon == 1")
        fig, ax = plt.subplots(figsize=(11, 4.5))
        history = self.data.iloc[-(self.config.test_months + 12):]
        ax.plot(history["date"], self._display(history[self.spec.column]), color=COLOR_ACTUAL,
                lw=2, label="Actual (reported)")
        for name, g in preds.groupby("model"):
            ax.plot(g["target_date"], self._display(g["prediction"]), lw=1.4,
                    color=MODEL_COLORS.get(name, COLOR_MUTED),
                    ls="-" if name == self.best_model_name else "--",
                    label=f"{name} (best)" if name == self.best_model_name else name)
        ax.axvline(self.test["date"].iloc[0], color=COLOR_MUTED, lw=1, ls=":")
        ax.text(self.test["date"].iloc[0], ax.get_ylim()[1], " test period",
                va="top", fontsize=8, color=COLOR_MUTED)
        ax.set_ylabel(f"{self.spec.label} ({self.spec.display_unit})")
        ax.set_title(f"{self.spec.label}: 1-month-ahead predictions on the test period",
                     loc="left")
        ax.legend(frameon=False, fontsize=8, ncol=3, loc="lower right",
                  bbox_to_anchor=(1.0, 1.0))
        self._style_axis(ax)
        fig.tight_layout()
        return fig

    def plot_forecast(self) -> plt.Figure:
        """Plots recent history and every model's forecast.

        The best model is drawn with its empirical prediction interval, the
        other models as thin dashed lines.

        Returns:
            The forecast figure.
        """
        cfg = self.config
        col = self.spec.column
        hist = self.data.iloc[-48:]
        best = self.best_forecast
        dates = pd.to_datetime(best["date"])
        lo_col = next(c for c in best.columns if c.startswith("lower"))
        hi_col = next(c for c in best.columns if c.startswith("upper"))
        color = MODEL_COLORS.get(self.best_model_name, "#2a78d6")
        fig, ax = plt.subplots(figsize=(11, 4.5))
        ax.plot(hist["date"], self._display(hist[col]), color=COLOR_ACTUAL, lw=2,
                label="Actual (reported)")
        anchor_date, anchor_val = hist["date"].iloc[-1], hist[col].iloc[-1]
        for name, g in self.forecast[~self.forecast["is_best"]].groupby("model", sort=False):
            ax.plot([anchor_date, *pd.to_datetime(g["date"])],
                    self._display(np.array([anchor_val, *g["prediction"]])),
                    color=MODEL_COLORS.get(name, COLOR_MUTED), lw=1, ls="--", alpha=0.8,
                    label=name)
        ax.plot([anchor_date, *dates], self._display(np.array([anchor_val, *best["prediction"]])),
                color=color, lw=2.2, marker="o", ms=7, markevery=list(range(1, len(dates) + 1)),
                label=f"{self.best_model_name} forecast (best)")
        ax.fill_between(dates, self._display(best[lo_col]), self._display(best[hi_col]),
                        color=color, alpha=0.18, lw=0,
                        label=f"{int(round(cfg.interval * 100))}% interval")
        unit = self.spec.display_unit
        decimals = 0 if self.spec.display_scale == 1 else 2
        for d, v, step in zip(dates, best["prediction"], best["step"]):
            ax.annotate(f"{step}\n{self._display(v):,.{decimals}f} {unit}",
                        (d, self._display(v)), textcoords="offset points",
                        xytext=(0, 12), ha="center", fontsize=8, color=COLOR_ACTUAL)
        ax.set_ylabel(f"{self.spec.label} ({unit})")
        ax.set_title(f"{self.spec.label}: next {cfg.horizon} months", loc="left")
        ax.legend(frameon=False, fontsize=8, ncol=4, loc="lower right",
                  bbox_to_anchor=(1.0, 1.0))
        self._style_axis(ax)
        fig.tight_layout()
        return fig

    @staticmethod
    def _style_axis(ax: plt.Axes) -> None:
        """Applies the shared recessive grid and axis styling.

        Args:
            ax: Axes to style.
        """
        ax.grid(axis="y", color=COLOR_GRID, lw=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(COLOR_GRID)
        ax.tick_params(colors=COLOR_MUTED, labelsize=8)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(
            lambda v, _: f"{v:,.1f}" if abs(v) < 100 else f"{v:,.0f}"))

    # ------------------------------------------------------------------ #
    # Model registry
    # ------------------------------------------------------------------ #

    def _default_models(self) -> dict[str, Callable[[], BaseForecaster]]:
        """Builds factories for every model whose library is installed.

        Returns:
            Mapping from model name to a callable creating a new forecaster.
        """
        cfg = self.config
        spec = self.spec
        seed = cfg.seed
        models: dict[str, Callable[[], BaseForecaster]] = {}
        if XGBRegressor is not None:
            models["XGBoost"] = lambda: DirectTreeForecaster(
                "XGBoost", lambda: XGBRegressor(
                    n_estimators=400, learning_rate=0.03, max_depth=3, subsample=0.8,
                    colsample_bytree=0.8, min_child_weight=3, random_state=seed,
                    n_jobs=1), spec, cfg.horizon)
        else:
            logger.warning("xgboost not installed; skipping XGBoost.")
        if LGBMRegressor is not None:
            models["LightGBM"] = lambda: DirectTreeForecaster(
                "LightGBM", lambda: LGBMRegressor(
                    n_estimators=400, learning_rate=0.03, num_leaves=15,
                    min_child_samples=10, subsample=0.8, subsample_freq=1,
                    colsample_bytree=0.8, random_state=seed, verbose=-1, n_jobs=1),
                spec, cfg.horizon)
        else:
            logger.warning("lightgbm not installed; skipping LightGBM.")
        # n_jobs=1 on purpose: scikit-learn's joblib threads wipe the shared warning filters and
        # flood the log with "delayed/Parallel" warnings.
        models["RandomForest"] = lambda: DirectTreeForecaster(
            "RandomForest", lambda: RandomForestRegressor(
                n_estimators=100, min_samples_leaf=2, max_features=0.6,
                random_state=seed, n_jobs=1), spec, cfg.horizon)
        if Prophet is not None:
            models["Prophet"] = lambda: ProphetForecaster(spec, cfg.horizon, cfg.prophet_window)
        else:
            logger.warning("prophet not installed; skipping Prophet.")
        models["SeasonalNaive"] = lambda: SeasonalNaiveForecaster(spec, cfg.horizon)
        if cfg.models is not None:
            models = {name: factory for name, factory in models.items() if name in cfg.models}
        return models


def _json_safe(obj):
    """Replaces NaN/inf floats by ``None`` so the object is valid JSON."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.bool_, np.integer, np.floating)):
        return _json_safe(obj.item())
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def run_all(config: ModellingConfig | None = None, data: pd.DataFrame | None = None) -> dict:
    """Runs the pipeline for every configured target.

    Args:
        config: Pipeline configuration. Defaults to :class:`ModellingConfig`.
        data: Monthly dataset to use. Defaults to the reported (noisy) output of
            the synthetic data generator.

    Returns:
        Combined summary with one entry per target; also written to
        ``summary.json``. All models' forecasts are written to ``forecast.csv``.
    """
    config = config or ModellingConfig()
    if data is None:
        data = SupplyChainDataGenerator(config.generator_config).generate()
    data = prepare_data(data)
    logger.info("Data: %d months (%s to %s).", len(data),
                data["date"].iloc[0].date(), data["date"].iloc[-1].date())

    pipelines = {key: ForecastingPipeline(key, data, config) for key in config.targets}
    summaries = {key: p.run() for key, p in pipelines.items()}

    out = Path(config.output_dir)
    pd.concat([p.forecast for p in pipelines.values()], ignore_index=True).to_csv(
        out / "forecast.csv", index=False)
    summary = {
        "horizon_months": config.horizon,
        "forecast_start": pipelines[config.targets[0]].forecast["date"].iloc[0],
        "targets": summaries,
    }
    with open(out / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n######## Next {config.horizon} months, best model per target ########")
    for key, p in pipelines.items():
        b = p.best_forecast
        values = ", ".join(f"{s} ({d}): {v:,.0f}" for s, d, v in
                           zip(b["step"], b["date"], b["prediction"]))
        print(f"{p.spec.label} [{p.spec.unit}] via {p.best_model_name}: {values}")
    print(f"\nResults saved to {out}")
    return summary


def _parse_args(argv: list[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(description="Run the multi-target forecasting pipeline.")
    parser.add_argument("--models", nargs="+", help="Models to run (default: all available).")
    parser.add_argument("--data", type=Path, help="CSV with a 'date' column (default: generate synthetic data).")
    parser.add_argument("--output-dir", type=Path, help="Where to save results.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("cmdstanpy", "prophet"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    plt.switch_backend("Agg")
    overrides = {}
    if args.models:
        overrides["models"] = tuple(args.models)
    if args.output_dir:
        overrides["output_dir"] = args.output_dir
    run_all(ModellingConfig(**overrides),
            data=pd.read_csv(args.data, parse_dates=["date"]) if args.data else None)
