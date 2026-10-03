# CarbonOpt architecture

Authoritative contracts and numerical rules: [CENTER.md](../carbonopt-team/CENTER.md). This replaces the earlier FlexValue architecture at the same URL.

## Product and pipeline

Help one fictional company forecast its business-as-usual carbon/profit and compare sustainability intervention strategies under budget, profit and carbon constraints.

```text
Synthetic monthly company history
  → feature engineering and temporal backtesting
  → 12-month carbon/profit forecast and reconciled activity baseline
  → simulate_strategy(baseline, config)
      → manual what-if
      → pymoo NSGA-II → feasible nondominated candidates
      → P1 Monte Carlo and recommendation selection
  → Django + Plotly dashboard
```

SHAP explains the forecasts. Optimiser explanations use actual simulated effects and constraints. Benchmarking supplies independently sourced context. Optional LLM tools call this same pipeline.

## Architecture decisions

| Decision | Reason |
|---|---|
| Django templates + Plotly | Confirmed team stack; one Python backend and modest browser code |
| Pure Python numerical modules | A/B/C can develop and test without the web server |
| One central action engine | Manual, optimiser, risk and chatbot outputs must agree |
| Shared types and integration fixture | Four people can work before the forecasting module is complete |
| One LightGBM or XGBoost family, two targets | Matches the PDF without maintaining competing model stacks |
| Temporal holdout and naive reference | Exposes leakage and whether ML improves on a simple forecast |
| pymoo NSGA-II over six continuous intensities | Matches the requested multi-objective intervention search |
| Deterministic P0 before stochastic P1 | Establishes a working product before uncertainty adds complexity |
| Local datasets/model artifacts; no product database initially | Keeps the eight-hour integration manageable |
| Twelve months first | Longer horizons require additional forecast validation |

## Ownership and boundaries

- **A:** `src/data/`, `src/forecasting/`, `src/explainability/`.
- **B:** `src/actions/`, `src/optimization/`.
- **C:** `src/risk/`, `src/benchmarking/`, independent P0 checks.
- **D:** shared contracts, Django orchestration, Plotly, dependencies and integration.

B alone owns action equations. D renders results rather than calculating separate financial/carbon logic. C injects sampled effect parameters into B's engine. A provides the activity/component breakdown that reconciles with forecast totals.

## Common semantics

Use monthly inputs, GBP and kg CO2e. Objectives and minimum profit refer to the same 12-month total. Budget applies to upfront investment; capex cash and operating profit are separate. All six intensities represent the fraction of the remaining eligible transition, so zero actions reproduce BAU.

Actions are renewables, EV adoption, building efficiency, travel reduction, cloud efficiency and supplier transition. Recompute overlapping effects rather than summing percentage reductions. Clearly label synthetic data, model assumptions and conditional simulation intervals.

NSGA-II produces an approximate feasible nondominated candidate set, not proof of a complete exact frontier. Preserve each candidate's configuration and identity through charts, recommendations and comparisons.

The old half-hour job scheduler, MILP formulation, tariff objective and deadline-value table are outside this project's scope. See CENTER for exact interfaces rather than duplicating them here.

## Detailed data and model contract

The team center defines public interfaces. Freeze their concrete field names in `src/contracts.py` before parallel implementation; use typed dataclasses and explicit JSON conversion rather than different dictionaries in every lane.

### Historical observations

Use approximately 180 consecutive month-start rows for one fictional company. The generator records `dataset_id`, seed and assumptions alongside the CSV. Required columns are timestamp; revenue, costs and operating profit in GBP; employees; electricity/gas kWh; renewable energy percentage; fleet size and kilometres; business-travel kilometres; a documented cloud-usage unit; scope 1/2/3 and total kg CO2e. Decide the cloud unit once, such as compute-hours, and store its conversion assumptions.

Generate a common business-activity driver with growth, seasonality, autocorrelation and bounded disturbances. Derive revenue, staff and operations from it; derive energy and emissions from activities. Introduce only explicitly documented structural changes. This creates useful relationships for the forecast without presenting fabricated history as observations from a real firm. Keep the generated history fixed across dashboard interactions.

Do not assume every named activity captures all company emissions. Add a documented residual component when needed. Avoid making total carbon/profit both a target and a contemporaneous input that algebraically reveals that same target.

### Forecasting procedure

1. Use the last 12 months as an untouched temporal test block. Choose model settings on earlier data, using an earlier validation block or fixed modest settings.
2. Build shifted lag/rolling features and calendar features. For a forecast issued after month t, every input must be known at t or be an explicit future BAU assumption.
3. Select one model family, LightGBM or XGBoost, with separate estimators for carbon and profit. “One model family” does not mean omitting a target.
4. Implement one documented multi-step method, preferably recursive monthly prediction for the initial prototype. During the 12-step backtest, append predictions to lag history, not the held-out target observations.
5. Reproduce the deployed future-covariate policy inside backtesting. Actual future electricity/revenue cannot be supplied during evaluation if unavailable at prediction time.
6. Report MAE, RMSE and R² per target and a seasonal-naive reference. Report insufficient history, constant-target R² and weak performance honestly.
7. After evaluation, fit the selected configuration on all available historical months to issue the production 12-month baseline. Keep holdout evaluation artifacts separate from this final fitted artifact.

Save feature order, preprocessing, training cutoff, model/library version, seed and dataset hash with the model. Load only locally produced trusted model artifacts; never unpickle an uploaded file. Training runs through a script or management command, not on each dashboard POST.

### Reconciled future baseline

A returns forecast totals plus the activity/emission components B needs. A and B must use one reconciliation method. A practical default is proportional scaling of nonnegative raw component estimates so they sum to the nonnegative carbon forecast. Store the raw estimates, scaling factor and any clipping. If the raw sum is zero but the target is positive, reject the baseline until the team supplies a justified residual component; do not invent arbitrary shares silently.

For profit, preserve the forecast as the baseline anchor. B applies incremental operating savings/costs/depreciation to that anchor, rather than recomputing a different BAU profit from an incomplete ledger. If a full ledger is supplied, expose any reconciliation residual explicitly. Negative profit remains a valid forecast.

The initial horizon is 12 consecutive months. Each result carries the same `baseline_id`, month sequence and accounting units. Changing the model, dataset, assumptions or horizon produces a new identity and invalidates downstream results.

## Action simulation and financial semantics

Represent the six intervention keys exactly as:

```python
{
    "renewable_energy": 0.0,
    "ev_adoption": 0.0,
    "building_efficiency": 0.0,
    "travel_reduction": 0.0,
    "cloud_efficiency": 0.0,
    "supplier_transition": 0.0,
}
```

Each value is a fraction of the remaining eligible transition. If existing renewable share is r and action intensity is x, the resulting share is `r + x * (1-r)`. A value of zero preserves existing operations. A value of one means the full eligible transition, not necessarily a 100% physical emission reduction.

Action definitions specify eligible activities, achievable effects, dependencies/interactions, upfront investment, monthly running-cost changes, asset lives and effect-parameter names. They must say whether costs/effects scale linearly or use a declared nonlinear curve. Coefficients are synthetic assumptions unless evidenced; ML forecast accuracy does not validate them.

Use this evaluation order, or document an equivalent consistent one centrally:

1. Copy immutable baseline activity/components.
2. Apply demand reductions, such as building/travel/cloud efficiency, only to their eligible portions.
3. Apply technology/energy substitutions to remaining activity. EV adoption reduces fuel activity and adds electricity; renewable procurement uses the declared accounting treatment.
4. Recompute affected emissions without reapplying reductions to already-reduced totals.
5. Calculate incremental operating savings, added recurring costs and depreciation.
6. Return monthly outcomes and aggregate metrics, plus action-level explanation terms.

For month m:

`profit_after[m] = baseline_profit[m] + operating_savings[m] - added_operating_cost[m] - added_depreciation[m]`

Upfront investment is separately reported as `cost_gbp`; the budget constraint uses it. Under straight-line depreciation, an asset with cost K and useful life Y years contributes `K / (12*Y)` per active month, using the disclosed start convention. Do not deduct K again from operating profit. If cash impact is displayed, name it separately and include upfront cash once. No discounted cash-flow or tax claim is implied by this simplified model.

Zero configuration must reproduce the baseline before risk is added. Ordinary simulation is deterministic. `effect_parameters` overrides coefficient values for a sampled world; it does not change baseline/config identities or allow a second set of formulas in the risk module.

## Optimisation details

For six-dimensional x in [0,1], minimise:

`F(x) = [sum(monthly_co2e_kg), -sum(monthly_operating_profit_gbp)]`

Constraints use pymoo's nonpositive feasibility convention:

- `g_budget = cost_gbp - budget_gbp`
- `g_profit = minimum_profit_gbp - horizon_profit_gbp`
- Optional `g_carbon = reduction_target - (baseline_carbon - strategy_carbon)/baseline_carbon`

Omit the optional carbon constraint when no target is supplied. For zero BAU carbon, percentage reduction is undefined: mark it unavailable and reject a positive percentage-reduction requirement with a clear reason. Do not divide by a tiny invented denominator.

Scale objective/constraint values for numerical conditioning only using recorded nonzero scales. Preserve raw units in returned outputs and independently recheck feasibility in those units with documented absolute tolerances. Do not round results before checking constraints.

Start with seed 42, population 40 and 40 generations as a measured prototype configuration, not a performance guarantee. Evaluate known zero/manual candidates as useful comparators. Every objective call uses `simulate_strategy`; keep errors actionable. Return status, evaluation count and run settings. If the search finds no feasible candidate, say “no feasible strategy found in this run”; this alone is not mathematical proof that no feasible strategy exists.

Filter duplicate and dominated feasible outputs within the evaluated set. Give each candidate an ID tied to baseline, config and assumptions. A plotted point references that exact candidate. P0 recommendation uses the center's transparent deterministic policy; it is not a unique global “AI optimum.”

## Risk, recommendation and explanations

Risk evaluation receives baseline, configuration, uncertainty specification and the active constraints. Sample plausible bounded action parameters with explicit dependence assumptions; use the same sampled worlds to compare alternatives. Forecast uncertainty is included only if the team implements and documents a baseline-uncertainty model. Otherwise clearly state that the simulation covers action-effect uncertainty alone.

Start with a small sample batch for correctness and profile before attempting 5,000 samples per strategy. Evaluate a disclosed candidate shortlist if necessary. Store actual sample count, seed, evaluated thresholds and parameter-specification hash. Report means, percentile intervals, downside and target-hit probabilities as conditional simulation outputs.

`Recommendation` reports selected/none_qualifies/unavailable, nullable candidate ID, policy, reason and candidate/baseline/constraint identities. Conservative/balanced thresholds are configurable assumptions. Missing risk is not perfect reliability. If no strategy qualifies, surface that result; do not silently lower the user's requirements.

SHAP explains the fitted forecast using matching feature order and background data. Explain action selection separately through investment, simulated effects and constraint slacks. Optional LLM prose receives those facts and may call the shared tools; it does not invent quantities or bypass the engine.

## Django boundaries, UI and reproducibility

```text
config/                          Django settings and root routes
src/contracts.py                 Shared domain types and serialization
src/data/                        Generation, validation and features
src/forecasting/                 Train, backtest, predict
src/actions/                     Definitions and single simulation engine
src/optimization/                NSGA-II and constraints
src/risk/                        Sampling and recommendation policy
src/explainability/              SHAP outputs
src/benchmarking/                Optional sourced comparisons
web/                             Forms, views, services, charts, templates/static
artifacts/                       Trusted local datasets/models/results
tests/                          Unit, contract and integration checks
```

The application folder name may follow an existing scaffold; keep ownership boundaries stable rather than rename working code for this diagram. Pure numerical modules cannot import Django request/session objects. `web/services.py` coordinates their outputs.

Use a single dashboard with server-validated POST actions for manual simulation and optimisation; separate risk evaluation if it is expensive. Conventional Django templates work first, with small fetch enhancements only if useful. Preserve CSRF, escape labels, validate finite values and bound input sizes. Only allow known artifact IDs; never accept arbitrary server paths or provider URLs from users.

Cache by baseline/model hash, complete config, constraints, algorithm/seed settings and uncertainty/policy settings where relevant. Include schema version. Editing any relevant input makes displayed results stale. If requests overlap, only a response matching the current request/scenario identity can update the screen. No process-global mutable “current company.”

Bundle Plotly and essential styling locally. Core pages load saved artifacts without live API calls. Exported JSON includes inputs, units, identities, assumptions, selected configurations, outcomes and run statuses. A fixture-only screen remains visibly labelled until connected.

P0 shows historical/forecast KPIs, manual sliders, constraints, a Pareto plot and candidate details. P1 adds operative risk controls, scenario comparison, SHAP and sourced benchmarks. Hide unavailable controls. Future 3/5-year choices, a generic chatbot and databases are not prerequisites for the 12-month MVP.
