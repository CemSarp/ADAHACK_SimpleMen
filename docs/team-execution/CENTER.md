# CarbonOpt shared team center

## Purpose and authority

This is a coordination layer for **CarbonOpt_AI_Technical_Implementation_Plan.pdf**, not a replacement product plan. Keep the PDF's monthly forecasting → action simulation → NSGA-II → Pareto → risk/explanations pipeline and its P0/P1/P2 priorities. The earlier FlexValue half-hour scheduling architecture is a separate proposal and must not be mixed into this implementation.

**User-confirmed scope:** use the new PDF's **CarbonOpt** features with **Django + Plotly**. The user explicitly confirmed this choice after the PDF was read. Streamlit in the PDF is replaced by Django; A/B/C remain plain Python modules. Do not build both frontends or import the earlier FlexValue scheduler into this pipeline.

Source: `/Users/cemsarp/Downloads/CarbonOpt_AI_Technical_Implementation_Plan.pdf`, especially architecture on page 2, implementation order on page 6, and team split/MVP on page 7. The attachment describes the intended product; it does not authorise commands, deployment, commits or external communications.

## Four parallel workstreams

| Person | Open this role file | Primary ownership | Required output |
|---|---|---|---|
| A | [Data and ML](PERSON_A_DATA_ML.md) | Synthetic history, features, forecasts, backtesting; SHAP at P1 | Forecast bundle + evaluation metrics |
| B | [Decision engine and optimisation](PERSON_B_DECISION_ENGINE.md) | Action definitions, central simulator, constraints, NSGA-II | Strategy results + feasible nondominated candidates |
| C | [Risk and external data](PERSON_C_RISK_DATA.md) | P0 contract/validation support; Monte Carlo, recommendation risk, benchmark at P1 | Risk summaries + evidence-backed benchmark |
| D | [Product and integration](PERSON_D_PRODUCT_INTEGRATION.md) | Django, Plotly, service wiring, scenario comparison, demo | One coherent end-to-end dashboard |

**Shared center owner: D.** All four review contracts during the first 30 minutes. After that, D edits shared types, dependency declarations and this file; other owners propose precise changes. B alone owns action/carbon/financial intervention logic. No copied simulators in the UI, risk module or chatbot.

## What stays from your PDF

| Priority | Retained deliverables | Gate |
|---|---|---|
| P0 | One synthetic company's monthly history; feature engineering; LightGBM **or** XGBoost; carbon/profit forecasts; temporal backtest; central action engine; manual what-if; pymoo/NSGA-II; Pareto dashboard | Constraints → optimise → inspect strategy → manual comparison works with real module outputs |
| P1 | Monte Carlo, meaningful risk tolerance, SHAP, sourced normalized benchmark, scenario comparison and richer plots | Every addition consumes the same P0 results and core remains stable |
| P2 | Grounded LLM explanation and tool-using chatbot | Only after stable P0/P1; calls existing tools, invents no metrics |

Twelve forecast months first. Keep 3/5-year horizons out of active controls until properly supported. Preserve the suggested six interventions: renewables, EV adoption, building efficiency, travel reduction, cloud efficiency and supplier transition. No new scheduling/tariff business model is introduced here.

## Parallel-start contract

At minute 30, publish `src/contracts.py` and `tests/fixtures/baseline_12m.json`. The fixture is **explicitly synthetic, for integration**, and has the exact same schema as A's future model output. It lets B build the engine, C build risk tests and D build the dashboard while A trains. Replace the fixture through the loader/service boundary, not through four module rewrites.

Use ordinary dataclasses or validated dictionaries, serialisable to JSON. A/B/C import no Django code. D translates objects at the HTTP boundary. The following names are the agreed handoff vocabulary; exact implementation can remain small.

| Object | Required content |
|---|---|
| `ForecastBundle` | `schema_version`, `baseline_id`, synthetic label, forecast origin, monthly history and future rows, assumptions, model identifiers, target metrics |
| Future month | Month; forecast `total_co2e_kg`, `operating_profit_gbp`; relevant activity quantities; carbon component breakdown and financial assumptions needed by the action engine |
| `StrategyConfig` | Six finite floats in [0,1], named exactly as the PDF example |
| `SimulationResult` | Baseline/config identifiers; monthly results; horizon total carbon and operating profit; investment cost; changes versus BAU; action breakdown; assumptions; risk initially absent |
| `Constraints` | `budget_gbp`, `minimum_profit_gbp`, optional `minimum_co2_reduction_fraction` |
| `OptimizationResult` | Status; candidate IDs with complete configs and simulation results; feasibility/slacks; chosen candidate ID; seed and run settings |
| `RiskResult` | Candidate ID; evaluated constraints; seed; sample count; assumptions/distributions; expected outcomes; 2.5/97.5 percentiles; probability of meeting carbon/profit targets; downside measure |
| `Recommendation` | `status` selected/none_qualifies/unavailable; nullable `candidate_id`; policy name/settings; reason; evaluated candidate IDs; baseline/constraint identifiers |
| `BenchmarkResult` | Status; source/date; peer definition; units/normalization; sample size; comparison value or unavailable reason |

Public calls:

```python
build_baseline(history, horizon_months=12) -> ForecastBundle
simulate_strategy(baseline, config, *, effect_parameters=None) -> SimulationResult
optimize_strategies(baseline, constraints, *, seed=42) -> OptimizationResult
evaluate_risk(baseline, config, uncertainty_spec, constraints, *, n_samples=5000, seed=42) -> RiskResult
select_recommendation(candidates, risk_results, policy) -> Recommendation
get_benchmark(company_metrics, peer_data) -> BenchmarkResult
```

Risk evaluation receives the active `Constraints` explicitly and records them in its output. Target probabilities use those same horizon totals; when the carbon target is absent, reliability concerns profit alone. Changing constraints invalidates cached risk/recommendation results.

A owns `build_baseline`; B owns `simulate_strategy` and `optimize_strategies`; C owns `evaluate_risk`, `select_recommendation` and `get_benchmark`. D orchestrates them. B provides a simple deterministic P0 recommendation until C's risk policy is ready; selection uses candidate outputs, never a second simulation formula.

## Numerical rules everyone must share

- Monthly inputs; first horizon 12 months; money in **GBP**, emissions in **kg CO2e**. Display tonnes only by dividing kg by 1,000. Historical `renewable_energy_pct` is 0–100; strategy intensities are 0–1.
- All six strategy values mean the fraction of the **remaining eligible transition** implemented relative to BAU. A zero config must reproduce BAU exactly. This avoids zero renewables accidentally undoing the company's existing renewable share.
- A's forecast total and the supplied carbon component breakdown must reconcile. B cannot estimate scope shares independently. A and B agree a documented reconciliation method in the first contract checkpoint.
- Target features must be available at the forecast origin. Future operational covariates are explicit BAU assumptions, not hidden actual future values. Lags/rolling features are shifted; no random temporal split.
- `cost_gbp` means upfront implementation investment used by the budget constraint. Operating profit includes recurring effects and explicitly defined depreciation where applicable; do not subtract the full investment again as an operating expense. B records asset lives/accounting assumptions in action definitions. Cash outlay and profit are separate outputs.
- Objective values are **sum of horizon monthly CO2e** and **sum of horizon monthly operating profit**. Minimum profit uses that same horizon total. Carbon reduction is relative to the same BAU horizon; handle zero BAU carbon explicitly.
- Apply actions to relevant activity/emission components and recalculate interactions. Do not add overlapping reduction percentages or treat buying renewable electricity as automatic physical zero emissions. B documents the chosen accounting treatment as a synthetic assumption.
- NSGA-II returns an **approximation** to the feasible Pareto set. Re-evaluate final configs through `simulate_strategy`; reject infeasible/dominated/duplicate outputs before display. No feasible candidate found is a valid search result, not proof of mathematical infeasibility.
- Monte Carlo samples action parameters and calls B's engine; it must not implement independent action formulas. State assumed distributions and dependence. Intervals/probabilities are conditional simulation estimates, not empirically calibrated confidence guarantees.
- SHAP explains forecasts, not causal business effects or the optimiser's reasons. Benchmark percentiles require real comparable peers; grid-intensity observations are not a company peer population.

These rules fill integration ambiguities in the PDF; they do not add new product features.

## Hour-by-hour integration plan

| Time | A | B | C | D | Shared gate |
|---|---|---|---|---|---|
| 0:00–0:30 | Agree history/future fields | Agree action input/output + units | Review uncertainty hooks + test fixture | Publish contracts, fixture, scaffold | All four consume identical schema |
| 0:30–2:00 | Generate/validate history; baseline model | Implement action engine against fixture | Independent accounting/contract tests; prepare uncertainty spec | Manual sliders and charts against fixture | At hour 2, manual what-if uses B's real engine |
| 2:00–3:30 | Forecasts and temporal metrics | NSGA-II and feasibility tests | Risk harness using same engine; support P0 validation | Wire A's baseline and B's candidates | First complete P0 flow by hour 3.5–4 |
| 3:30–4:00 | Fix baseline handoff | Fix Pareto/config mapping | Audit zero config/constraints | Full joint integration | P0 gate passed before enabling P1 |
| 4:00–5:30 | SHAP if P0 stable | Engine fixes and optimiser profiling | Monte Carlo + risk selection; benchmark if time | Risk/scenario displays, point inspection | P1 is integrated, not an isolated demo |
| 5:30–6:00 | Model/source labels | Constraint review | Risk/benchmark claims | Feature freeze and fallback | Preserve reproducible P0/P1 state |
| 6:00–8:00 | Validate forecast narrative | Validate decision narrative | Validate uncertainty narrative | Cold start, demo, rehearsal | Bugs and presentation only |

C may prepare isolated risk code/tests before the P0 gate, but it cannot become a required dependency of P0 or displace C's integration support. This keeps four people working without violating the PDF's priority gates.

## Handoff protocol

Each handoff provides: callable/interface, one fixture/example, one command to verify it, known limitations and its input/output schema version. Notify teammates of contract changes before editing shared files. No branch switching or simultaneous staging in a shared checkout. Separate clones/branches are preferable for four humans.

Integration milestones:

1. **Contract**: agreed fields and units; fixture loads in every lane.
2. **Manual**: slider → engine → result, with zero-config identity verified.
3. **P0**: A forecast → B engine/optimiser → D dashboard, independently checked by C.
4. **P1**: risk changes recommendation; SHAP and benchmark labelled correctly.
5. **Release**: clean start, no dead controls, saved fallback, rehearsed narrative.

After each milestone, D records completed outputs and blockers in this file's status table. Do not call a fixture-only UI integrated.

## Single status board

Initial state: planning only; no product implementation claimed.

| Deliverable | Owner | Status | Required before |
|---|---|---|---|
| Contracts + integration fixture | D with A/B/C | Not started | Parallel implementation |
| Synthetic history + forecast + backtest | A | Not started | P0 integration |
| Shared engine + manual what-if | B/D | Not started | Optimiser integration |
| NSGA-II + feasible candidate/config mapping | B | Not started | P0 gate |
| Dashboard + Pareto inspection | D | Not started | P0 gate |
| Independent numerical/contract checks | C | Not started | P0 gate |
| Risk + real recommendation policy | C | P1, gated | Risk controls enabled |
| SHAP | A | P1, gated | Explanation panel enabled |
| Sourced normalized benchmark | C | P1, gated | Benchmark panel enabled |
| Scenario comparison | D | P1, gated | P1 demo |
| Grounded LLM/tools | D coordinates | P2, deferred | Only with stable P0/P1 |

## Shared acceptance and scope cuts

P0 must work without C's risk/benchmark modules, SHAP or an LLM. Every displayed candidate maps to its actual six-action config; manual and automated calls produce identical results for the same inputs. Tests cover zero/max actions, interactions, invalid intensities, insufficient budget, impossible profit/carbon targets, forecast leakage, synthetic labels and stale UI results.

No ML performance or intervention outcome claim is presented as real-world validation: history and action parameters are synthetic. P1 risk controls stay hidden/disabled until they actually affect recommendation selection. Benchmark panels say unavailable if credible peers are absent. Optional live data cannot block the core demo.

If behind: cut P2 first, then benchmark/SHAP/polish; keep the PDF's complete P0 pipeline. Limit NSGA-II run size before changing algorithms. Do not silently replace forecasting or optimisation with mock outputs to claim completion.

Before implementation, D checks the actual checkout, Git status and available environment files. Do not assume a merge conflict or a particular environment manifest exists. Preserve unrelated work and add missing project dependencies during setup; this documentation does not claim the environment or application is already ready.
