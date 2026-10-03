# Workstream 1 — Data, ML Forecasting, Backtesting and SHAP

Developer 1 owns this workstream. Main consumers: WS2 baseline simulation, WS3 risk/benchmark, WS4 forecast and evaluation panels.

## Read first

Read [the central plan](../../IMPLEMENTATION_PLAN.md), [schemas](../DATA_SCHEMAS.md), [contracts](../SHARED_CONTRACTS.md), and [forecasting specification](../FORECASTING_SPEC.md). The baseline fixture is available before training is complete; downstream developers do not need model files.

## Ownership

Owned source paths: `src/data/generate.py`, `src/data/features.py`, `src/data/drivers.py`, `src/forecasting/train.py`, `src/forecasting/predict.py`, `src/forecasting/backtest.py`, `src/explainability/shap_analysis.py`.

Owned tests: `tests/unit/test_data.py`, `test_features.py`, `test_forecast.py`, `test_backtest.py`, `test_shap.py` within `tests/unit/`. Proposed generated artifacts: `data/company_timeseries.csv`, `data/provenance.json`, model binaries/metadata in `models/`.

Coordinate shared contract edits through WS4. Do not edit the action formula, optimizer or dashboard when baseline assumptions change; publish a reviewed contract change.

## Inputs and published contracts

Inputs: generation/feature/training/driver/backtest configs and canonical history. Outputs: history frame, SupervisedDataset, ModelBundle, BaselineBundle, BacktestReport, optional ExplanationResult.

Public signatures are authoritative in [SHARED_CONTRACTS.md](../SHARED_CONTRACTS.md). Baseline output must contain all activity fields and three scopes, not just total emissions/profit predictions. Monthly dates, unit suffixes and aggregation are fixed.

## Exact local implementation order

| Step | Priority | Task | Completion evidence |
|---:|---|---|---|
| 1 | P0 | Generator + history validator + provenance | Reproducible, continuous 204-row history |
| 2 | P0 | Prefix-safe driver projection + feature construction | Shifted lags/rolling tests; no target leakage |
| 3 | P0 | Train two target models and record metadata | Same feature order during train/predict |
| 4 | P0 | Recursive 12-month prediction + scope reconciliation | Complete schema-valid baseline |
| 5 | P0 | Three expanding-window backtests + seasonal naive | Actual/predicted rows + pooled metrics |
| 6 | P0 | C1 handoff and provider substitution | WS2/WS4 fixture parity checks pass |
| 7 | P1 | Target-specific SHAP on recursive feature rows | Raw prediction additivity; UI handoff |
| 8 | P2 | Optional 36/60-month support only after validation | Capability flags and horizon-specific tests |

Forecast implementation precedes accepted backtesting in the central sequence; feature and fold tests can be authored together. Do not postpone chronological validation until after dashboard acceptance.

## Start without waiting

Use `examples/baseline_12m.json` as the expected output shape. WS2 and WS4 build against it while you generate history. Build chart/backtest fixtures with WS4 so the evaluation panel has stable columns even before model results exist.

Choose deterministic driver projection first. A successful forecast requires future activities; no other workstream will provide hidden future revenue/electricity inputs. If model performance is poor, deliver honest metrics and a documented target-specific seasonal-naive fallback rather than delaying the entire integration.

## Tests and edge cases

Validate negative/zero activity rejection, permitted loss-making profit, no missing months, malformed dates, renewable/EV range and total/scope identities. Assert history/config hashes and seeds reproduce results.

Test supervised indexing with tiny known sequences. Modify held-out targets and realized drivers after cutoff: forecast results for that fold must not change. Month-2 lag state must use month-1 prediction. Test clipping counts and scope2 zero at full renewable share.

An insufficient history raises a typed error with required/actual usable row count. Unsupported horizons fail explicitly. SHAP failure or unavailable target does not break P0.

## Handoffs

At C1 publish schema version, history/provenance revision, model metadata, baseline JSON, backtest JSON, reproducible commands, tests, and model/driver limitations. WS2 signs off the simulator can consume the frame without preprocessing; WS4 confirms charts/metrics deserialize.

At C5b publish SHAP result rows and optional capability status. Label contributions as forecast explanations, not causal action estimates.

## Definition of done

P0: history, forecast and temporal evaluation are real; all public objects validate; downstream fixture → real provider substitution requires no UI/action code changes; metrics include naive comparison; synthetic data is labelled.

P1: SHAP uses the trained model's exact feature rows and units; explanations reconcile to raw model output; unsupported models fail gracefully.

Reference branch: `feat/ws1-forecast`. Split generator, forecast and backtest into reviewable PRs; use shared-file changes only through contract PRs.
