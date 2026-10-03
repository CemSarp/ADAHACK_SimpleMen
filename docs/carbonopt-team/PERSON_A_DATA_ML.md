# Person A — Data and ML

Read [CENTER.md](CENTER.md) first. It owns shared contracts and status. This role maps PDF sections 3–4 and the SHAP portion of section 8; do not introduce FlexValue scheduling models.

## Your responsibility and boundary

Deliver one synthetic company's monthly history, a 12-month BAU forecast for CO2e and operating profit, and honest temporal evaluation. Add SHAP only after P0 integration works.

Own `src/data/generate.py`, `src/data/features.py`, `src/forecasting/{train,predict,backtest}.py`, `src/explainability/shap_analysis.py`, your model/data outputs and associated tests. Do not edit B's action equations, C's risk distributions or D's views/settings. Request shared contract changes through D.

## Parallel starting point

By minute 30, give B/C/D a synthetic 12-month `ForecastBundle` fixture with activity fields, carbon components and financial assumptions. Agree reconciliation with B: forecast carbon totals and action-addressable components must sum consistently. This fixture is a handoff tool, not a trained forecast. Everyone can build against it while you train.

## Work in order

### 0:00–2:00 — history and first forecasts

1. Generate approximately 180 monthly observations with a fixed seed. Include the PDF's financial, company, energy, fleet/travel/cloud and carbon columns. Build dependencies from common activity/growth drivers, not independent random columns.
2. Document seasonality, trend, structural changes, noise and the synthetic accounting assumptions. Profit may be negative; energy/activity cannot. Reconcile scope totals and total carbon.
3. Validate missingness, ranges, correlation, autocorrelation and time plots. Keep this a concise diagnostic, not a separate analytics product.
4. Select **one** already workable LightGBM/XGBoost implementation with D. Use lag/rolling/calendar features and conservative complexity for a small dataset.
5. Add a simple seasonal-naive reference forecast. It is an evaluation baseline, not a substitute for the PDF's model deliverable.

**First handoff:** generated history, fixture schema, validation summary and runnable generation command.

### 2:00–3:30 — reliable 12-month handoff

1. Implement a temporal holdout using the final 12 months; fit preprocessing/model choices on earlier data. Shift rolling features so the target cannot leak into its own predictors.
2. Evaluate the actual deployment procedure: if the UI recursively forecasts 12 months from one origin, backtest that same process without injecting held-out target values at later horizons.
3. Mark future operational inputs as explicit BAU assumptions or separately projected inputs. Never consume unknown future actual revenue/energy as if available at prediction time.
4. Report MAE, RMSE and R² separately for profit/carbon, alongside the naive reference; constant targets make R² unavailable. Retain weak performance honestly.
5. Return `build_baseline(history, horizon_months=12)` in the shared schema. Reconcile component totals and model forecasts without B deriving its own baseline.

**Second handoff:** real model-produced `ForecastBundle`, model/version/seed metadata, metrics and inference command. D replaces the fixture loader without changing UI schemas.

### 4:00–5:30 — P1 only after the center gate

Explain the selected forecast model with SHAP. Use the actual training feature order and a small background/sample set. Return chart-ready values and feature labels; do not require D to load training internals. Explain predictive drivers, not causal intervention effects. Keep 3/5-year horizons deferred unless the 12-month path is validated and the team has surplus time.

## Acceptance checks

- Reproducible generation; scope/component totals reconcile; no impossible physical values.
- Test that changing held-out target observations does not alter training features or an already-issued multi-step prediction.
- Feature availability and train/test boundary are recorded; no shuffled splits.
- Finite forecasts with any physical clipping/reconciliation explicitly recorded; don't silently clamp negative profit.
- `ForecastBundle` loads in B/D with documented units and exact 12-month coverage.
- Metrics say “synthetic temporal holdout,” not evidence of real business prediction quality.

## Coding-agent iteration prompts

Give your agent this file and CENTER.md. Send one instruction at a time:

1. **A1:** “Implement only my generator, validation and shared fixture handoff. Read CENTER.md; preserve repository changes. Explain data dependencies and units. Verify accounting identities and reproducibility. Do not build the action engine or UI. Stop with the fixture and actual test results.”
2. **A2:** “Implement my one-model 12-month forecast and temporal evaluation against a seasonal-naive reference. Test origin-available features and recursive holdout behaviour. Return the agreed ForecastBundle with reconciled components. Report errors honestly; do not claim synthetic validation transfers to real companies.”
3. **A3, gated:** “The P0 gate is confirmed. Add SHAP outputs for the actual forecast model only. Preserve feature order and label predictive explanations correctly. Do not add a second explainer or change B's intervention logic.”

At each handoff: output the callable, fixture/example, verification command, tests actually run and limitations. Update your status through D. Final two hours are integration fixes and rehearsal, not model expansion.
