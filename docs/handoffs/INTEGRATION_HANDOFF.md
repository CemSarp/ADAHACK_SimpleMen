# Integration Handoff: WS1 + WS2 + WS3 + WS4

> **Productisation update:** the app launches one CSV-backed company path with no provider selector. Earlier milestone descriptions below are historical. See [the current README](../../README.md) for launch and configuration instructions.

Branch `feat/integration-all-workstreams`, created from `main` at `aa68f7a` (which already contained every workstream's merged code). Contract `1.0.0`. Uncommitted, unpushed, untagged.

**Status:** all six computational providers run as real implementations from the configured company CSV. The input data is **synthetic** and every screen and result says so. The all-real C4 milestone is **not** accepted: that needs the team review listed at the end. No `mvp-working` tag exists.

## 1. Final flow and wiring

```text
data/synthetic_data.csv  (synthetic, EUR, monthly 2001-01..2025-12)
  -> src/forecasting/history.py        explicit import adapter -> canonical history (GBP)
  -> ml_core/modelling.py (WS1)        5 candidates, walk-forward backtest, best model per target
     via src/forecasting/ws1_adapter.py  train once, cache under models/ws1/<model_id>/
  -> src/forecasting/baseline.py       BaselineBundle (12 months) + BacktestReport
  -> src/actions + src/optimization (WS2)  simulator, constraints, NSGA-II, Pareto
  -> src/risk (WS3)                    Monte Carlo over the bounded frontier pool (common trials)
  -> WS2 recommend_strategy            risk-aware selection AFTER risk results exist
  -> src/explainability (WS1 trees + shap), src/benchmarking (WS3)  annotations
  -> src/integration/pipeline.py       run_analysis, compare_scenarios (C6)
  -> app.py + src/dashboard (WS4)      dashboard, state, cache invalidation, chatbot tools
```

| Slot | Real mode provider | Version string pattern | Status |
|---|---|---|---|
| forecast | `src.forecasting.provider.create_forecast_provider()` -> WS1 `ml_core` | `ws1-integration-1+ws1-<identity>` | real |
| simulator | WS2 `simulate_strategy` + `config/action_assumptions_supply_chain.json` | `ws2-engine-…+supply-chain-actions-v1@1.0.0` | real |
| optimizer | WS2 `optimize_strategies`, `evaluate_constraints`, `recommend_strategy` | `ws2-nsga2-…` | real |
| risk | WS3 `create_risk_provider(config/uncertainty.json)` | `ws3-risk-1+illustrative-risk-v1@…` | real (illustrative uncertainty) |
| shap | `src.explainability.provider.create_explanation_provider()` (WS1 tree models + `shap`) | `ws1-shap-1+ws1-<identity>` | real |
| benchmark | WS3 `create_benchmark_provider(config/benchmark_supply_chain.json)` | `ws3-benchmark-1+…` | real; **result `unavailable`** (no compatible logistics peers) |
| narrative | none | — | unavailable (P2 template only) |

**Company binding.** When the forecast slot is the real CSV-backed WS1 provider, the real simulator, risk and benchmark providers load the company files named in `config/integration.json`. With a fixture forecast (hybrid preset, mock mode) they keep the demo files. A baseline is therefore never paired with another company's assumptions. This is tested.

The product runs the company-backed services by default and never substitutes test doubles. Explicit mock/hybrid construction remains for regression tests. Required service failures stop startup with a user-facing message and server diagnostics; optional failures disable only the affected capability.

## 2. Input CSV and import adapter

- **File:** `data/synthetic_data.csv`, sha256 `bce28163…a650`.
- **Provenance:** `data/synthetic_data_provenance.json`. I verified the file is the default `SupplyChainDataGenerator` output (seed 42, noisy "as reported" series) within 1.5e-8. It was used as-is, not regenerated.
- **Checks:** 300 contiguous month starts, one company, no missing or non-finite values, `total = scope1 + scope2 + scope3`, and `ebitda = revenue − operating_cost`. Scope 2 equals electricity × grid factor × (1 − renewable share) on every row (market-based). The adapter rejects gaps, duplicates, non-finite values and broken identities rather than repairing them.
- **Mapping:** `config/company_import.json` (`supply-chain-csv-import-v1`):
  - money columns: EUR → GBP at a **fixed 0.85 GBP/EUR, illustrative and not market data**;
  - `operating_profit_gbp` ← `ebitda_eur` (EBITDA, because the CSV has no depreciation);
  - `fleet_km` ← `vehicle_km`, `ev_share` ← `fleet_ev_share`, `electricity_kwh` ← `electricity_consumption_kwh`;
  - not reported, so stored as 0 with the reason recorded: `gas_kwh`, `business_travel_km`, `cloud_compute_hours`, `employees`. No scope is zero-filled.
- **Company:** `supply-chain-demo-co`, industry `logistics`.

## 3. WS1 lifecycle

- **First baseline request:** WS1's own `ForecastingPipeline` steps run in native units:
  - candidates XGBoost, LightGBM, RandomForest, Prophet and SeasonalNaive;
  - horizon 12, test 24 months, backtest 12, step 1, seed 42, WAPE selection.
- **Artifacts:** forecasts, held-out predictions, metrics and the best tree regressors go to `models/ws1/<model_id>/` with `metadata.json`. The directory is git-ignored and written atomically.
- **Model ID:** a hash of the CSV, import mapping, settings, `ml_core/modelling.py` code and library versions. A change to any of them triggers retraining, and only a matching identity is loaded.
- **Reuse:** later processes load the artifacts. Within a process they are memoized, and the Streamlit services are cached. Training never runs on reruns or slider changes.
- **Pre-train:** `python -m src.forecasting.train` (`--retrain` to force).
- **Baseline assembly:**
  - totals = WS1 best-model forecasts (EBITDA × 0.85);
  - scopes = the forecast total split by trailing-12-month scope shares;
  - activities from the driver policy `seasonal-clipped-growth-v1`: same month last year × clipped growth for flows, last value carried for states.
  These two adapters fill gaps WS1 does not cover and **need WS1 review**.
- **Backtest:** WS1's held-out 24-month walk-forward (origins × horizons 1–12) for the selected model against WS1's seasonal-naive-with-drift at the same origins. Pooled metrics; `oof_predictions` carries an additive `horizon` column.
- **SHAP:** `shap.TreeExplainer` on the WS1 RandomForest per horizon, using WS1's own feature row at the origin. Additivity is checked. Units are WS1's raw relative output (log ratio for emissions, margin deviation for profit), not tonnes or GBP, and are labelled as such.

**Leakage safety:** WS1 builds every feature at the forecast origin from data up to the origin, and refits at each walk-forward origin. A test rewrites all post-origin rows and confirms identical features and predictions. The driver projection reads history only.

## 4. Configuration

| File | Purpose | Owner review |
|---|---|---|
| `config/integration.json` | CSV, mapping, WS1 settings, driver policy, company files, dashboard defaults | WS4 (+ all) |
| `config/company_import.json` | CSV → canonical mapping, FX | WS1 + WS4 |
| `config/action_assumptions_supply_chain.json` | Illustrative company assumptions (`is_calibrated: false`), tariffs derived from the CSV | **WS2** |
| `config/benchmark_supply_chain.json` | Industry `logistics`, scope 2 `market_based`, excludes the company | WS3 |
| `config/uncertainty.json` | WS3 illustrative uncertainty (unchanged) | WS3 |
| `tests/fixtures/integration/integration_test.json` | Test-only smaller WS1 walk-forward, model dir `models/ws1-test` | WS4 |

`CARBONOPT_CONFIG` selects another integration config (repo-relative). The tests set it to the test config.

## 5. Run (repository root, Python 3.11)

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-p1.txt     # P0 + shap
.venv/bin/python -m src.forecasting.train                   # optional pre-train (about 6 min cold)
.venv/bin/python -m pytest
.venv/bin/python -m streamlit run app.py
.venv/bin/python scripts/run_integrated_analysis.py         # headless reproduction with timings
```

On macOS, XGBoost and LightGBM need the OpenMP runtime: `brew install libomp`. Without it, WS1 reports a typed `ForecastError` that names this fix.

## 6. Tested demonstration inputs (actual runs, real mode, seed 42)

Baseline 2026-01..2026-12: CO₂e 98,705.3 t, operating profit (EBITDA) £36,322,966, revenue £287,518,721 (synthetic).

Backtest (held-out 24 months, all horizons pooled):

| Target | RandomForest MAE | Seasonal-naive MAE | RMSE | Seasonal-naive RMSE |
|---|---|---|---|---|
| Emissions | 1,039.85 t | 1,637.99 t | 1,308.19 | 2,133.37 |
| EBITDA | £1,205,283 | £1,737,638 | £1,526,577 | £2,136,712 |

| Request | Result |
|---|---|
| Budget £20M, profit floor £30M, target 10%; 2,048 evaluations; risk 1,000 trials | `ok`: 110 Pareto strategies, 20-strategy risk pool. Balanced: `strategy-e701afc15b4ae383`, 85,234.5 t (−13.6%), profit £36,979,540, outlay £17,941,767, P(target) and P(joint) 1.000. Scenario comparison: conservative `…675b0ba77d0eee57` (−12.6%), balanced `…e701afc15b4ae383` (−13.6%), aggressive `…fc1fcabda62a2c51` (−18.3%). SHAP 660 rows. Benchmark `unavailable` (industry mismatch: 0 of 10 synthetic peers are logistics). |
| Budget £0, same floor and target | `infeasible`: empty frontier, no recommendation, no risk trials. |

**Runtime** (this Apple-silicon laptop, warm, single process):

| Step | Time |
|---|---|
| WS1 cold training | 355 s |
| Cached baseline and backtest load | 0.37 s |
| One simulation | 2.3 ms |
| NSGA-II, 2,048 evaluations | 10.5 s |
| Risk, 1,000 trials for one strategy | 2.35 s (the 20-strategy pool about 47 s) |
| Full feasible analysis | 59.5 s |
| SHAP | 1.3 s |
| Benchmark | 12 ms |

These are measurements, not guarantees.

## 7. Verification

- **pytest:** 535 passed, 1 skipped (the opt-in live Ollama test) in 181 s on 2026-10-03, with the test WS1 config already cached. Includes `tests/integration/test_all_workstreams.py`, covering the 16 required cross-workstream checks plus CSV rejection cases, the tolerance-follow rule and working-directory independence. Also `tests/integration/test_integrated_dashboard.py` (AppTest, real mode).
- **Browser (real mode, production config):**
  - all providers real and synthetic-data label shown;
  - Optimize with risk, SHAP and benchmark;
  - recommendation, scenario table (three distinct plans) and SHAP tab;
  - tolerance change reran only the policy;
  - Load selected strategy: identical to the stored result.
- **Fixed during integration:**
  - stale "WS1 missing" tests;
  - WS3 resolving relative paths against the working directory (the adapter now passes repo-rooted paths);
  - SHAP provider crashing startup on a broken `shap` install;
  - an artifact-directory race;
  - selection not following a tolerance-changed recommendation.

## 8. Limitations

- Synthetic data. The FX rate, the EBITDA-as-operating-profit mapping, the action assumptions and the uncertainty bounds are illustrative.
- WS1 forecasts only two targets. Activities come from a deterministic driver policy, and scopes from proportional reconciliation, so they are not causal or scope-level forecasts.
- SHAP explains relative raw outputs, not tonnes or GBP. If WS1 later selects a non-tree model for a target, that target's SHAP is reported unavailable.
- There is no compatible benchmark dataset for a logistics company, so the benchmark is correctly unavailable.
- The P2 narrative is template-only; the chatbot defaults to the mock model.
- Supported horizon is 12 months only.

## 9. Reviews required (none have occurred)

| Item | Reviewer |
|---|---|
| CSV import mapping, FX, EBITDA mapping, not-reported zeros | WS1 + WS4 |
| Driver policy, scope reconciliation, backtest mapping, SHAP units | WS1 |
| `action_assumptions_supply_chain.json` values and bucket allocations | WS2 |
| Benchmark company config; WS3 path-resolution note | WS3 |
| Additive `horizon` column in `BacktestReport.oof_predictions`; non-GBP raw SHAP units | WS1, WS4 consumers |
| C4 all-real acceptance checklist | All four |
