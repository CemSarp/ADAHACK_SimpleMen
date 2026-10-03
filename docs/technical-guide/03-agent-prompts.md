# CarbonOpt coding-agent entry point

This replaces all previous FlexValue prompts. Read [CENTER.md](../team-execution/CENTER.md), then use exactly one owner's linked role file. Those files contain the current A1–A3, B1–B3, C1–C3 and D1–D3 iterations; do not maintain another conflicting copy here.

## Shared context to paste first

```text
We are four people building CarbonOpt in roughly eight hours using Django and
Plotly. Follow docs/team-execution/CENTER.md and my assigned role file.
Read applicable repository instructions and inspect current files/Git state.

Scope: one synthetic company's monthly history; a 12-month CO2e/profit forecast
with temporal backtesting; one central simulate_strategy engine; manual what-if;
pymoo NSGA-II over six intervention intensities; feasible Pareto candidates and
a dashboard. P1 adds Monte Carlo/risk selection, SHAP, sourced benchmarking and
scenario comparison. P2 adds grounded LLM explanations and internal tools.

Use the current center's contracts and units: GBP, kg CO2e and monthly periods.
Zero actions reproduce BAU. Keep investment cash separate from operating profit.
Prevent forecast leakage and overlapping action savings. All strategy calculations
must go through B's engine, including sampled risk runs and optional chatbot tools.
Risk evaluation receives the actual constraints explicitly. Preserve baseline and
candidate IDs, simulation assumptions, feasible/no-solution states and source labels.

Do not implement the earlier FlexValue tariff scheduler, SciPy MILP, job deadlines,
or carbon-price scheduling objective. Use the current technical-guide and team-execution directories.
Do not use stored tariff JSON as company training data or peer benchmarks.

Work only on my assigned iteration/files. Explain important choices and run
meaningful numerical/interface checks. Use the shared labelled fixture until the
upstream module is available; never present a fixture as a trained model output.
Ask the shared-file owner before changing contracts. Preserve unrelated work.
Do not automatically commit, push, deploy, reset Git, delete files or delegate.

After the iteration report: behaviour delivered, files changed, verification
actually performed, blockers/limitations and the next handoff. Stop at that gate.
```

## Choose the role and next iteration

- [A: data, forecasting, backtesting, SHAP](../team-execution/PERSON_A_DATA_ML.md).
- [B: shared action engine, constraints, NSGA-II](../team-execution/PERSON_B_DECISION_ENGINE.md).
- [C: independent checks, Monte Carlo, risk recommendation, benchmarks](../team-execution/PERSON_C_RISK_DATA.md).
- [D: shared contracts, Django, Plotly, integration](../team-execution/PERSON_D_PRODUCT_INTEGRATION.md).

D establishes the shared contract checkpoint first. Then the four initial iterations proceed in parallel against the same fixture. Integrate P0 before enabling P1; reserve the final two hours for fixes and rehearsal.

## Integration review prompt

```text
Review the implemented CarbonOpt pipeline against CENTER.md and the four role
files. Check that the forecast, manual sliders, optimiser and risk module share
one baseline/schema and one action engine. Verify temporal evaluation, zero-config
identity, constraint signs, investment/profit accounting, candidate/config identity,
and explicit uncertainty assumptions. Confirm risk targets use the active constraints.
Check that P0 works without optional features and changed inputs invalidate results.
Run available relevant checks and report evidence. Fix only in-scope integration
errors in owned files, coordinating other owners' changes. Do not add new features.
```

## Detailed iteration prompts

Use these with the corresponding role iteration, not as permission to implement every lane. Each agent receives CENTER, its role file and this guide. D owns shared contracts; another owner proposes changes instead of editing them concurrently.

### Foundation checkpoint — D

```text
Implement only the shared CarbonOpt foundation. Inspect the current checkout,
repository instructions and actual Python environment; preserve unrelated work.
Use Django + Plotly and establish one reproducible dependency manifest. Coordinate
one LightGBM/XGBoost family with A and pymoo with B; do not install both model
families merely because the source document lists alternatives.

Freeze src/contracts.py from CENTER: ForecastBundle, StrategyConfig,
SimulationResult, Constraints, OptimizationResult, RiskResult, Recommendation,
and BenchmarkResult. Include baseline/candidate identities and explicit statuses.
Create a labelled 12-month integration fixture with reconciled carbon components,
activity fields and profit anchor. Publish exact six action keys and units.

Build a minimal Django page and loader boundary. Do not implement forecasting,
action equations or the optimiser. Verify contract imports without Django,
fixture serialization and the framework system check. Report actual commands,
files and the handoff to A/B/C, then stop at the contract checkpoint.
```

### Forecast implementation — A

```text
Implement my data/forecast lane using CENTER and the architecture guide.
Generate roughly 180 monthly observations for one fictional company with common
activity drivers, trend, seasonality, autocorrelation and documented structural
changes. Reconcile scope totals, physical quantities and financial fields.
Record the seed and mark the history synthetic throughout.

Build shifted lag/rolling/calendar features. Use one selected model family with
separate CO2e/profit estimators. Reserve the final 12 months for temporal testing;
choose settings without using that test block. Implement a seasonal-naive
comparison and report MAE/RMSE/R² separately for both targets.

Backtest the actual multi-step deployment procedure: no held-out actual targets
or unavailable future covariates may enter recursive prediction. Document the
BAU assumptions for future operations. Save feature order and cutoff metadata.
Refit the selected configuration on complete history only after evaluation.

Return the agreed ForecastBundle, including activity/component reconciliation
and assumptions, so B does not create a competing baseline. Test that altering
held-out targets cannot alter an already-issued forecast. Handle constant
outputs, missing months, negative profit and invalid component reconciliation.
Do not implement interventions or imply synthetic accuracy validates real firms.
Stop after a model-produced bundle and reproducible evaluation handoff.
```

### Central engine — B

```text
Implement only the deterministic action engine against the shared baseline
fixture. Keep all action equations and parameters in src/actions. Use the six
remaining-transition intensities in [0,1]; zero configuration preserves BAU.

Document eligible components, investment costs, recurring savings/costs and asset
lives. Apply efficiency reductions before substitution effects where appropriate;
EV adoption adds electricity as it removes fuel. Recalculate affected components
instead of adding overlapping percentage reductions. Preserve the forecast profit
anchor and apply incremental effects. Separate upfront cash from depreciation
and operating profit.

Expose effect_parameters for C's sampled worlds without duplicating simulation
logic. Validate finite values and bounds, return monthly and horizon totals,
explanations and identities, and never mutate the baseline.

Start with hand-calculated zero/single-action fixtures, then test overlapping
interventions, all-max settings and invalid inputs. Demonstrate that direct and
manual calls return the same result. Stop before NSGA-II so D can integrate
manual what-if immediately.
```

### Multi-objective search — B

```text
Add pymoo NSGA-II over six intensities, calling the central simulator for every
objective and constraint evaluation. Minimise horizon carbon and negative
horizon profit. Match budget, profit and optional reduction constraints to
CENTER's units and horizon, and test pymoo's inequality sign convention.

Start with a measured seed/population/generation configuration. Record run
settings, evaluation count and latency. Rescale for conditioning only with
recorded factors; validate final outputs in raw units using explicit tolerances.

Re-evaluate candidate configurations, filter infeasible/duplicate/dominated
results, and retain stable IDs plus exact configs and slacks. Return an honest
no-feasible-candidate-found state; search failure is not a proof of mathematical
infeasibility. Provide the documented deterministic P0 selection policy.

Check zero budget, impossible minimum profit, zero BAU carbon, target boundaries
and identical manual/optimiser outcomes. Do not claim an exact complete Pareto
frontier or add Monte Carlo inside every search evaluation. Stop at the candidate
handoff with actual test and runtime evidence.
```

### Risk and recommendation — C

```text
Implement the risk lane only after the shared engine contract is available;
keep it optional for P0. Early work should also verify independent accounting
and contract cases for the team.

Call evaluate_risk with explicit baseline, config, uncertainty_spec and active
constraints. Sample bounded effect parameters and pass them into B's engine.
Document distributions, dependence assumptions and whether forecast uncertainty
is included. Reuse sampled worlds across candidate comparisons. Start small,
profile, and disclose actual sample counts and any candidate shortlist.

Test that zero variance reproduces deterministic results and seeds reproduce
worlds. Calculate outcome means, percentile intervals, downside and joint target
probability using the supplied horizon thresholds. If no carbon target exists,
evaluate profit reliability alone. Changing thresholds must invalidate risk.

Implement Recommendation exactly as CENTER specifies. Conservative/balanced
policies use their declared reliability requirements; aggressive prioritises
expected carbon reduction among deterministic-feasible candidates. Missing
risk is unavailable, and none qualifying is a valid outcome. Preserve policy,
candidate and constraint identities. Do not label these assumptions calibrated
confidence or a global risk optimum. Stop with tested outputs ready for D.
```

### Dashboard and P0 integration — D

```text
Integrate A/B/C's published interfaces without reproducing their numeric logic.
First connect manual sliders to B's real simulator, then A's trained baseline,
then B's optimiser. Fixture-only outputs remain visibly labelled until replaced.

Build one Django/Plotly dashboard: synthetic/history/forecast context; 12-month
horizon; budget/profit/carbon controls; manual actions; Pareto plot; exact selected
config and outcome details. Point selection uses candidate IDs. Compare manual
outcomes with a concrete returned strategy, not an invented universal optimum.

Validate inputs server-side, preserve CSRF and safely serialize chart data.
Load trusted artifact IDs only. Cache by baseline/model/config/constraints and
algorithm settings, plus uncertainty/policy settings where relevant. Changed
inputs stale prior outputs; overlapping requests cannot replace a newer result.
Training must not run on every slider change. Bundle essential chart assets locally.

Handle invalid/no-solution/error states with readable messages, not zero metrics.
Keep unsupported risk/horizon/benchmark/chat controls hidden or disabled.
Run a real baseline -> engine -> optimiser -> click/inspect -> manual comparison
walkthrough. Verify exact metrics and configs match the backend. Record the P0
gate and only then integrate operative P1 modules. Stop before optional expansion.
```

### P1 explanation and benchmark integration — respective owners

```text
P0 has passed its shared gate. Implement only my owner's P1 portion and keep
P0 usable without it. A: SHAP must use the actual model and feature order and
explain predictions rather than intervention causality. C: benchmark results
require compatible peer boundaries, units, normalization, period and source;
grid observations are not companies, and missing peers mean unavailable.
D: scenario comparison reuses baseline/config/result identities and the same
engine. Risk controls must alter the actual recommendation policy.

Validate missing optional artifacts and external data failure. Do not add an
LLM until the P1 gate is stable and rehearsal time is protected. If P2 proceeds,
feed structured results and expose existing tools; never invent metrics or
implement a disconnected chatbot. Report the integrated behaviour and limitations.
```

### Final review and demo — D coordinates

```text
Audit the actual implementation against CENTER, the four role files and the
CarbonOpt architecture/edge-case guides. Work on confirmed defects, not new
features. Do not delegate unless explicitly requested.

Verify temporal leakage tests, naive comparison, baseline reconciliation,
zero-config identity, action interactions, capex/profit treatment, constraint
signs, final candidate feasibility and config mapping. Confirm explicit risk
thresholds, zero-variance identity, policy selection and source/assumption labels.

Run relevant tests and Django checks in the product environment; report exact
commands/results. Cold-start offline and inspect forms/charts/errors/stale states.
Make sure P0 runs without risk, SHAP, benchmarks or LLM. Compare headline numbers
with independent calculations. Test a feasible case, impossible target and
missing optional data. Do not claim tests that were not run.

Prepare a three-minute demo using actual outputs and a labelled fallback.
Explain what is synthetic, what the model predicts, what actions assume, and
why a chosen feasible strategy is preferred. Give every teammate a contribution.
Record measured timings and remaining limitations, then stop at release readiness.
```

## Recovery prompt

```text
The current iteration fails with: [paste the real error and reproduction].
Inspect the smallest failing path, identify the cause with evidence and repair
only in-scope owned files. Coordinate contract changes through D. Do not rewrite
the application, alter data to fake a successful result, disable constraints or
replace the agreed stack. Re-run the reproduction and affected checks; report
what passed, what remains uncertain and the next handoff. Stop after the repair.
```
