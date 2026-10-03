# WS2 Handoff — Action Engine, Constrained NSGA-II, Pareto and Recommendation

Contract `1.0.0` · branch `workstream2` (WS4's `main` merged in, pending review) · audience: WS3 (risk), WS4 (dashboard and integration), WS1 (baseline producer)

## Status

WS2's P0 backend is integrated with the WS4 dashboard. The working configuration is the `hybrid` preset **Fixture forecast + real WS2**:

- labelled fixture baseline;
- real WS2 simulator, shared constraint evaluation, NSGA-II optimizer, Pareto frontier and P0 recommendation;
- WS3 capabilities disabled with their reason.

The P1 risk-aware policy is implemented and tested on hand-authored `RiskResult`s; WS3's Monte Carlo is not available. Every result built on the fixture carries `provenance.is_mock = true`. This is **not** the all-real C4 MVP: that needs WS1's forecast provider.

## 1. Run it (repository root, Python 3.11)

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest                                         # 333 tests
CARBONOPT_PROVIDER_MODE=hybrid .venv/bin/python -m streamlit run app.py
.venv/bin/python -m src.optimization.cli simulate --constraints tests/fixtures/v1/constraints.json
.venv/bin/python -m src.optimization.cli optimize --max-evaluations 256
.venv/bin/python -m src.optimization.cli profile
```

In the sidebar the same configuration is *Provider mode → hybrid → Hybrid configuration → Fixture forecast + real WS2*. `CARBONOPT_HYBRID_PRESET=custom` restores WS4's per-slot choices.

| Provider slot | `hybrid` preset | Source |
|---|---|---|
| forecast (baseline) | fixture `baseline_12m.json` (mock) | WS1 replaces it via `src.forecasting.provider.create_forecast_provider()` |
| simulator | real | `src.actions.engine.simulate_strategy` + `config/action_assumptions.json` |
| optimizer | real | `src.optimization.optimizer.optimize_strategies`, `constraints.evaluate_constraints`, `recommendation.recommend_strategy` |
| risk, benchmark | unavailable (reason shown) | bind automatically once WS3 publishes `src.risk.provider` / `src.benchmarking.provider` |
| shap | disabled | a fixture baseline has no trained model to explain |

`real` mode fails at startup and names the missing WS1 forecast. It never substitutes a fixture.

### Demonstration configurations (actual WS2 outcomes)

| Inputs (sidebar) | Result (seed 42, population 64, 2,048 evaluations) |
|---|---|
| Budget £500,000, profit floor £1,000,000, CO₂ target 20% (the defaults; equals `constraints.json`) | `ok`: 2,025 feasible candidates, **289 Pareto strategies** (CO₂e 443.7–810.3 t; profit £1.281M–£1.314M). Recommended `strategy-168017a8da8b5449`: 487.4 t (−59.4%), profit £1,285,334, gross outlay £481,803. The no-op is infeasible (it misses the target). |
| Budget £0, same floor and target | `infeasible`: empty Pareto table, no recommendation. Each constraint is individually reachable (minimum normalized violation 0 for budget, profit and target), but no candidate meets all three (minimum total violation 0.2). |

Gross outlay across that frontier ranges from about £362k to £500k. Illustrative savings make most actions profitable, so every frontier point beats the baseline profit, and lower emissions cost some of that gain. These are illustrative, uncalibrated economics.

## 2. Public interfaces

All types come from `src.contracts` (WS4's package; WS2 adds no schema of its own). Functions validate before computing, never mutate inputs, and raise `ContractValidationError(field, reason)` for invalid input and `OptimizationError` for unexpected solver failures.

```python
# src.actions
simulate_strategy(baseline, config, *, assumptions) -> SimulationResult          # canonical SimulationFn
compute_action_breakdown(baseline, config, *, assumptions) -> pd.DataFrame       # same transform, intermediates
load_action_assumptions(path=None) -> ActionAssumptions                          # config/action_assumptions.json
canonical_config(config) -> ActionConfig                                         # validated floats, -0.0 -> 0.0
compute_strategy_id(baseline_id, config, assumptions) -> str
apply_uncertainty_sample(assumptions, *, sample_id, effectiveness_multipliers=None,
                         capex_multipliers=None, opex_multipliers=None) -> ActionAssumptions   # WS3 hook
# src.optimization (importing it never imports pymoo)
evaluate_constraints(result, constraints) -> ConstraintEvaluation
evaluate_what_if(baseline, config, *, assumptions, constraints=None, simulator=None) -> WhatIfEvaluation
optimize_strategies(baseline, constraints, *, assumptions, config, simulator) -> OptimizationResult   # lazy pymoo
compute_pareto_frontier(candidates) -> pd.DataFrame
recommend_strategy(optimization, *, risk_results=None, tolerance="balanced") -> RecommendationResult
select_risk_pool(optimization, *, max_size=20) -> tuple[str, ...]
risk_pool_from_frontier(pareto, *, max_size=20) -> tuple[str, ...]              # the one pool rule
```

`SimulationResult.metrics` is a mapping with the 13 documented keys; the two ratios are `None` for zero baselines. `ConstraintEvaluation.raw_violations` is a mapping (`budget_gbp`, `profit_gbp`, `reduction_ratio`), and `satisfied` (`budget`, `profit`, `target`) gives per-constraint pass/fail for UI badges. `RecommendationResult.diagnostics` holds the pool, coverage, threshold and shortfall details.

## 3. Behaviour consumers rely on

- **Actions.** Each value is the fraction of the *remaining* eligible opportunity, applied in month 1 and held. Out-of-range, non-finite, boolean and string values are rejected, never clamped.
- **Transform.** The order follows `ACTION_MODEL.md` §3. Scopes are computed as `baseline × (1 − reduction fraction)`, algebraically identical to the bucket equations. This keeps the all-zero config bit-exact on any baseline; re-summing the literal buckets drifts by one unit in the last place for about 6–25% of arbitrary values. EV adoption can raise scope 2 and total emissions; this is never clamped.
- **Accounting.**
  - Capex is charged once, in month 1.
  - Depreciation hits operating profit and stops at the asset life.
  - Budget is gross outlay (capex plus incremental opex); savings never reduce it.
  - Net cash is reported separately.
  - Profit may be negative.
- **Constraints.** Normalized `g ≤ 1e-8` **and** the raw boundary (0.01 GBP; 1e-8 on the ratio). A positive ratio target on a zero-CO₂e baseline is a validation error.
- **Optimizer.**
  - The no-op is evaluated first, then fixed seeds (each action alone, all at 1, all at 0.5), then a seeded Latin hypercube.
  - All search evaluations, initialization included, count against `max_evaluations`, and the last generation is truncated to fit.
  - Repair is explicit: decision vectors are clipped to [0, 1], and the count is reported.
  - Every unique candidate is kept in `strategies` and `candidates`. Each published Pareto strategy is re-simulated and must reproduce bit for bit and pass raw constraints.
  - The global NumPy RNG is untouched.
- **Pareto.**
  - Infeasible rows are filtered first, and cost does not affect dominance.
  - Tolerances are 0.01 GBP and 1e-6 t + 1e-8 × the largest feasible \|CO₂e\|. They are published in `diagnostics["dominance_tolerances"]`; use them for any independent nondominance check.
  - Strategies with equivalent objectives are kept; exact duplicate configs collapse onto the smallest ID.
  - `pareto_rank`: 0 for frontier rows, 1 for feasible but dominated, −1 for infeasible.
- **Recommendation.**
  - P0 is an equal-weight min-max score, with constant objectives contributing zero, ties broken by strategy ID, and a single point selected directly.
  - P1 policies follow `RISK_AND_BENCHMARK_SPEC.md` §2.
  - With no usable risk result, it falls back to the deterministic policy with `risk_status="unavailable"`, never claiming risk-aware selection.
  - If the threshold is unmet, it picks the highest joint probability and reports the shortfall.
  - Partial coverage is reported.
  - Mixed trial sets are rejected.

## 4. Assumptions

`config/action_assumptions.json` (`demo-actions-v1` v1.0.0, `is_calibrated: false`) is the documented illustrative example, byte-identical to the fixture. The parser is strict: unknown fields, booleans used as numbers and non-integral asset lives are rejected. Changing a coefficient requires a new ID/version because strategy identities depend on it.

The simulator rejects baselines that allocate emissions to an activity that is zero, naming the column:
- ICE-fleet scope 1 with no remaining ICE km (`fleet_km × (1 − ev_share) = 0`);
- gas scope 1 with `gas_kwh = 0`;
- scope 2 with `electricity_kwh = 0` or with renewable share 1;
- travel or cloud scope 3 with zero km or hours.

## 5. Shared contract changes requiring team review

Reconciliation kept WS4's contract package as the single schema. These changes were made in it during the merge; each is pinned by `tests/contracts/test_shared_contract_changes.py`:

| Change | File | Why | Reviewers |
|---|---|---|---|
| `ConstraintEvaluation.satisfied` (optional mapping, default `{}`) | types.py | UI badges use WS2's exact per-constraint result instead of re-deriving it from raw violations | WS4 |
| `RecommendationResult.diagnostics` (optional, default `{}`; serialized, decoder tolerates absence) | types.py, serialization.py | Pool coverage, thresholds and shortfall are visible without parsing `reason` | WS3, WS4 |
| Assumption files reject unknown fields, booleans as numbers and non-integral `asset_life_months` (6.5 was silently truncated to 6) | serialization.py | A misspelled or malformed coefficient must not be ignored | WS3, WS4 |
| `target_probability_mc_standard_error` may be null exactly when `target_probability` is null | validation.py | DATA_SCHEMAS §9: undefined ratios give null, never zero-filled errors | WS3 |
| `validate_optimizer_config` rejects negative seeds | validation.py | NumPy/pymoo seeds are nonnegative; a negative seed would surface as a solver error | WS4 |
| Strategy identity maps `-0.0` to `0.0` | identity.py | Numerically equal configs share one ID; fixture IDs unchanged | WS4 |
| `ContractValidationError` and `UnsupportedHorizon` are picklable | errors.py | Two-argument constructors broke `pickle` | WS4 |
| `requirements.txt` adds `pymoo==0.6.2` | requirements.txt | Real optimizer dependency; imported lazily so mock startup does not need it | WS4 |

WS2's stopgap contract package from commit `22cee48` was removed in the merge (not kept alongside); its compact `strategies="frontier"` serialization option was dropped because WS4's validated `OptimizationResult` requires every candidate's strategy.

## 6. Evidence

| Check | Result |
|---|---|
| Full suite (`python -m pytest`, Python 3.11.9, NumPy 2.4.6, pandas 3.0.6, pymoo 0.6.2, Streamlit 1.65.0) | **333 passed**: 63 contract, 222 unit, 48 integration |
| WS4's pre-existing tests | 99 of 102 passed unchanged after the merge; the 3 that asserted "WS2 is missing" now assert the WS1-only gap |
| Golden arithmetic | No-op bit-exact; nonzero fixture within 2.3e-13; both fixture strategy IDs reproduced |
| Cross-boundary (`tests/integration/test_ws2_ws4_hybrid.py`) | All 12 requested checks, plus a share-display parity check against the engine |
| Streamlit AppTest (`tests/integration/test_dashboard_hybrid_apptest.py`) | Hybrid startup labels; Optimize consumes inputs; load-selected equals stored; slider uses the real simulator; input change discards results; infeasible state; real-mode error |
| Same seed/budget, CLI vs dashboard | Identical recommendation (`strategy-01947d7786e4bbe6` at 256 evaluations) |

Runtime on one laptop (Apple Silicon, macOS 15.7; not a guarantee):

| Measurement | Result |
|---|---|
| `simulate_strategy` (12-month fixture) | about 2.5 ms, of which about 1.6 ms is WS4's `validate_baseline` |
| `optimize_strategies`, 64 × 32 = 2,048 evaluations | about 9.5 s |
| Full dashboard Optimize (`run_analysis`, includes re-validating all stored strategies) | about 12 s, within the 20 s team target |

Before the merge, WS2's own NumPy validators gave about 0.8 ms per simulation and about 3 s per optimization. The extra time is boundary validation, not computation.

## 7. Integration requirements

- **WS1 (replacement point).** Publish `src.forecasting.provider.create_forecast_provider()` returning a provider with `info: ProviderInfo` (non-mock) whose `get_baseline()` returns a `BaselineBundle` that passes `validate_baseline` and the §4 compatibility rules. Then use `CARBONOPT_PROVIDER_MODE=real`; no WS2 or dashboard change is needed.
- **WS3.**
  - Publish risk and benchmark factories.
  - Run Monte Carlo through the injected simulator, using `apply_uncertainty_sample` with a unique `sample_id` per trial.
  - Evaluate only `select_risk_pool(...)` strategies, all on one trial set.
  - Null probabilities are allowed only for undefined ratios.
- **WS4.**
  - Bump nothing manually: provider versions come from WS2 module `__version__`s.
  - The follow-up list includes vectorizing the shared validators.

## 8. Known limitations

- Assumptions are illustrative and uncalibrated, and the baseline is a flat synthetic fixture.
- NSGA-II results are reproducible per seed but not proven optimal; "infeasible" means none was found within the budget.
- No discounting, financing, tax or action-driven revenue. Asset lives are whole months.
- A full 2,048-candidate result serializes to about 15 MB.
- Open items are tracked in [WS2_FOLLOW_UPS.md](WS2_FOLLOW_UPS.md).
