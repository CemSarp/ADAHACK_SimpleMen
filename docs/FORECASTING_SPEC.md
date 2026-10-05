# Forecasting, Backtesting and SHAP Implementation Specification

Owner: WS1. Reviewers: WS2 for baseline shape, WS4 for evaluation display. P0 predicts monthly total CO₂e and operating profit using two separate LightGBM regressors. XGBoost is a coordinated substitution behind the same interface.

## 1. Synthetic history generation

Generate a single company's continuous monthly history with trend, seasonality, autocorrelation, seeded noise and at least one disclosed structural change. Generate business activity first; derive energy, financials and emissions using consistent domain relationships.

Suggested relationships: activity/revenue growth raises energy demand; higher renewable share lowers market-based scope2; gas and remaining ICE fleet contribute to scope1; travel, cloud and supplier activity contribute to scope3. Calculate total emissions from scopes. Do not independently generate contradictory total/scopes.

`DataGenerationConfig` specifies base revenue and profit margin, activity baselines, annual growth ratios, seasonal amplitudes, autocorrelation coefficients, noise scales, structural-change dates, emission factors and baseline adoption trends. Scalars are finite and ranges validated. Store the exact config and seed.

A default 204-month synthetic sample is adequate for a demo experiment but is not evidence of real-company forecast quality. Report metrics as synthetic temporal evaluation.

## 2. Supervised indexing and leakage prevention

Use a direct one-step model where a row's target date is month `t` and every target-derived predictor is available by `t-1`.

`FeatureSpec` fields: ID, target names, lag list (default 1/3/6/12), rolling windows (3/6/12), projected driver names, date feature names, warm-up policy. `TrainingConfig` fields: model family, hyperparameters, minimum usable rows (default 48), optional target transform, and clipping policy.

Features for target `t`:

~~~text
total_co2e at t-1, t-3, t-6, t-12
operating_profit at t-1, t-3, t-6, t-12
rolling means over shifted target series, ending at t-1
projected driver values for month t from information available at t-1
calendar month t as sine/cosine; optional year index
~~~

Always shift target series before rolling. Never use actual current-month targets or realized future revenue/energy as deployment features. Feature names, order, preprocessing and driver projection policy are fixed in the model metadata.

For training projected driver predictors, build each historical feature row's driver forecast from its own prior prefix using the chosen driver policy. This avoids training on realized drivers and evaluating on a different information set. Prefix projection is small enough for the demo dataset; cache deterministic results without crossing cutoffs.

Both target models may use historical lags of both targets. Recursive prediction therefore updates both predicted series after each month. Discard lag warm-up rows and record the resulting count. Never fill initial missing target lags with future means.

## 3. Future driver policy

`DriverPolicy` fields: policy ID, lookback months (default 12), annual growth bounds, renewable/EV trend method, and explicit optional overrides. Driver projection is a deterministic baseline policy, not an action simulator.

P0 policy: use the most recent seasonal value for monthly flows/activities, apply clipped growth estimated from available history, and carry forward or bounded-trend state variables. Keep revenue positive, activities nonnegative, adoption shares [0,1], counts integer. Future driver dates must exactly match the requested horizon.

For rolling backtesting, regenerate the complete future driver path from each fold's training prefix. Test-period realized drivers are used only as actual observations, not as inputs to the forecast.

External economic or benchmark APIs never become an implicit driver dependency. If explicit future driver overrides are allowed later, mark them as user scenarios and record their provenance.

## 4. Recursive baseline prediction

1. Validate history, feature specification and trained cutoff.
2. Reject unsupported horizon before generating work.
3. Produce future drivers from available history.
4. For each future month, build the exact trained feature order from driver projections and actual/predicted prior targets.
5. Predict both targets; apply disclosed output constraints (total emissions ≥0; profit may be negative).
6. Append predictions to lag state before predicting the next month.
7. Decompose predicted total emissions into scopes using nonnegative trailing-12-month aggregate scope shares.
8. Return a complete BaselineBundle with activities, metadata, totals and adjustment counts.

If trailing total emissions are zero, use a declared fallback scope allocation (default equal thirds) for positive predictions; record it. If renewable share reaches 1 in the future, set scope2 share to zero and renormalize scope1/scope3; if both remaining shares are zero use equal scope1/scope3. This enforces the P0 scope2 assumption while preserving the predicted total. Reconciliation is an approximation, not a causal scope forecast.

Artifact metadata records training end, feature order, model family/version, data/config hashes, driver policy, scope shares and target units. Load only model binaries produced through the trusted local pipeline; model files are not public JSON interfaces.

## 5. Backtesting acceptance

`BacktestConfig` fields: `horizon_months=12`, `n_folds=3`, `step_months=12`, `min_train_months=60`, and `comparison="seasonal_naive"`. Use expanding chronological training windows and nonoverlapping test blocks when sufficient history exists. Exact dates derive from the dataset, not wall-clock year assumptions.

For a 204-month series, the last 36 months form three rolling 12-month test blocks. Each fold retrains models from scratch, constructs training rows without future information, projects drivers from the fold cutoff, and recursively forecasts the complete test block.

Seasonal naive uses the last available same-calendar-month target and recurses if needed. Compute target-specific MAE, RMSE and R². Pool residuals for aggregate MAE/RMSE; report R² only when defined. Report metrics on actual deployment outputs after the same clipping/reconciliation policy.

If either model fails to beat seasonal-naive MAE, publish that fact; do not hide the comparator. WS1 may choose seasonal naive as the production fallback for that target while preserving a trained tree model for disclosed experimentation. The selected model family for each target is explicit in metadata. Do not claim an ML uplift that tests do not show.

No validation thresholds depend on absolute magnitude of demo emissions or profit. P0 requires successful leakage-safe evaluation and honest comparison, not fabricated accuracy.

## 6. SHAP scope

P1 SHAP explains tree model predictions. Explain target-specific monthly raw outputs using the same feature rows generated during recursive forecasting; persist or reproducibly rebuild those rows. A baseline with a seasonal-naive target has an unavailable SHAP capability for that target.

Store feature values, SHAP contributions, base value and raw prediction; test approximate additivity. Top drivers summarize prediction contribution, not causal intervention effectiveness or the optimizer's reason for choosing an action. Distinguish recursive projected features from reported historical features.

If emissions clipping or scope reconciliation changes the displayed number, expose the raw/displayed difference. Do not force SHAP values to sum to a modified total.

## 7. Work products and tests

Outputs are history/provenance, model metadata/artifacts, 12-month baseline, backtest report and optional explanation. Tests cover reproducibility, monthly continuity, driver generation from prefixes, lag/rolling indexing, feature order, recursive use of predictions, scope reconciliation, negative profit handling and unsupported horizons.

A decisive leakage test changes all post-cutoff actual target/driver values and verifies that that fold's predictions do not change. Another test verifies a month-2 lag uses month-1 prediction rather than held-out actuals.
