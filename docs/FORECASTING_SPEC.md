# Forecasting, Backtesting and SHAP

Owner: WS1. The forecast predicts 12 months of total CO₂e and operating profit for one company from its
canonical monthly history (DATA_SCHEMAS.md §2): the demo company's CSV or an uploaded table. Code:
`ml_core/modelling.py` (models, features, walk-forward evaluation) and `src/forecasting/` (adapter, caching,
baseline and backtest assembly).

## 1. Targets and inputs

`ws1_adapter.target_specs(history)` describes the two targets for any company:

| Target | Column | Scale-free form the models learn |
| --- | --- | --- |
| Emissions | `total_co2e_tco2e` | `log(y[t+h] / trailing 12-month mean)` when every month is positive; otherwise the deviation from that mean divided by trailing revenue |
| Operating profit | `operating_profit_gbp` | `(y[t+h] − trailing 12-month mean) / trailing 12-month mean revenue` (profit may be negative) |

Drivers are whichever of `revenue_gbp`, `electricity_kwh`, `fleet_km`, `renewable_energy_share` and
`ev_share` vary in the history; constant or unreported columns carry no signal and are left out.

`build_supervised(data, spec, h)` builds, for every month `t`, features that use only data up to `t`:

- the target's last six months relative to its trailing mean (`y_lag0_rel` … `y_lag5_rel`);
- the same calendar month one and two years before the target month (`seasonal_ref_rel`, `seasonal_ref2_rel`);
- growth of the trailing level over 12 and 3 months (emissions), or margin and level changes (profit);
- each driver relative to its 12-month mean and its 12-month growth (shares: level and 12-month change);
- the target month as a number and as sine/cosine.

## 2. Models

| Model | How it forecasts | Library |
| --- | --- | --- |
| Random forest | One regressor per horizon `h = 1…12` (`DirectTreeForecaster`), 100 trees | scikit-learn |
| XGBoost, LightGBM | The same direct scheme, 400 boosted trees | optional |
| Prophet | Trend and yearly seasonality on the last 96 months | optional |
| Seasonal repeat | Same month last year, scaled (or shifted) by the change in the 12-month level | none |

Tree predictions are mapped back to tonnes or GBP with `from_relative`. **Automatic choice:** Random forest when
there are at least 60 months, the seasonal repeat below that (the lagged features leave too few training
rows). The user can choose another model (`ws1_modelling.model` in the settings; on the page,
**Forecast with**); the choice is part of the cache identity, so each model is fitted once.

## 3. Evaluation

Settings come from `config/integration.json` (`ws1_modelling`: `test_months = 12`, `step = 3`, `seed = 42`).

1. The last 12 months are held out.
2. Walk-forward: from the last training month and then every 3 months, the chosen model and the seasonal repeat
   are refitted on everything up to that origin and forecast the following months inside the held-out year.
3. MAE, RMSE, WAPE and bias are pooled over those forecasts. The backtest report pairs every prediction with the
   seasonal repeat at the same origin and horizon, so the page can show "forecast error vs a simple repeat" and
   the assistant can quote both misses.
4. The chosen model is refitted on all months and forecasts the 12 months after the last one.

Nothing from the held-out year enters a forecast made before it. If the model does not beat the seasonal
repeat, the page shows that (a positive error difference); nothing is hidden or switched silently.

**On-demand comparison.** `compare_models(imported, settings, horizon, models)` runs step 2 for each model the
user picks and returns per target: MAE, RMSE, WAPE, bias and seconds. A model that cannot fit the data gets
empty errors and a note. Nothing is stored or used for planning unless the user then picks the model.
`available_models()` lists the models whose library is installed without importing them, so the panel adds
nothing to page load. The full research comparison (backtest, test, selection, plots) remains
`python -m ml_core.modelling`.

## 4. Caching

`load_or_train` fits once per identity: data checksum, import mapping, `ml_core/modelling.py` checksum, horizon,
settings (including a chosen model) and library versions. Artifacts (forecasts, test predictions, metrics and the
fitted trees) live in `models/ws1/<model_id>/`, are written atomically and are only reused for the exact
identity; an in-process memo keeps reruns free. First fit: about 8 s for the 25-year demo company, about 4 s for
an 8-year upload. Changing the modelling code retrains once.

## 5. Baseline assembly (`src/forecasting/baseline.py`)

The models forecast only the two totals. The baseline also needs activities and scopes for the simulator:

- **Drivers** (`project_drivers`): reported flows repeat the same month last year scaled by last year's growth,
  clipped to the configured annual bounds; states (employees, shares, fleet size) carry the last month forward;
  flows the company does not report stay 0. At least 24 months are required.
- **Scopes** (`reconcile_scopes`): the forecast total is split by the last 12 months' scope shares; in a month
  with 100% renewable supply Scope 2 is 0 and the other shares are renormalised (market-based assumption).

The result is a validated `BaselineBundle` (12 contiguous months after the history, totals equal to sums).

## 6. SHAP (`src/explainability/provider.py`)

`WS1ShapProvider` explains the bound forecast (the demo or the upload, with whichever model drives it). For
each horizon model it runs `shap.TreeExplainer` on the feature row at the forecast origin, checks that the
contributions add up to the model's raw output, and returns one row per month, target and input. Values are in
the models' relative output space (§1), not tonnes or GBP. A target forecast by a non-tree model (seasonal
repeat, Prophet) has no explanation and is reported as unavailable.

Presentation (`src/dashboard/presentation.py`): an input's importance is its mean |SHAP| over the 12 months as a
share of the total; the page shows the top *k* inputs (colour = whether the input raises or lowers the forecast
on average) and groups the rest; `feature_label` gives plain names ("Same month last year", "EV share, change
over 12 months"). The assistant's `get_forecast_drivers` tool uses the same functions. Drivers explain the
forecast, not why a plan was chosen, and are not causal effects.

## 7. Tests

`tests/integration/test_all_workstreams.py` (import, leakage, provider and backtest behaviour),
`tests/integration/test_model_choice.py` (installed models, on-demand comparison, a chosen model driving the
forecast and its cache identity, SHAP on an upload), `tests/integration/test_upload.py` (uploads end to end) and
`tests/unit/test_presentation_and_charts.py` (top-*k*, plain names).
