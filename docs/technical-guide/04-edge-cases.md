# CarbonOpt edge cases and acceptance checks

Use [CENTER.md](../team-execution/CENTER.md) for the canonical definitions. These checks replace the old half-hour scheduling cases.

| Area | Case | Expected behaviour | Owner |
|---|---|---|---|
| Data | Fixed seed | Reproducible synthetic history | A |
| Data | Missing, duplicate or out-of-order months | Explicit validation; no silent temporal corruption | A |
| Data | Negative physical activity or inconsistent scope totals | Reject/fix generator with documented assumptions | A |
| Data | Negative operating profit | Retain valid losses; do not clamp automatically | A |
| Forecast | Rolling/lag leakage | Features use only information available at prediction origin | A |
| Forecast | Multi-step holdout | Same inference procedure as production; no future actual targets inserted | A |
| Forecast | Future revenue/energy features | Explicit BAU assumptions or forecasts, not unknown actuals | A |
| Forecast | Constant target | R² unavailable; retain meaningful error metrics | A |
| Forecast | ML worse than seasonal naive | Report honestly, preserve comparison | A |
| Forecast | Totals and activity components disagree | Reconcile using the shared documented method before simulation | A/B |
| Actions | All six intensities zero | Monthly and total results equal BAU | B |
| Actions | All-max or overlapping changes | Recompute eligible activities; no double-counting or impossible reductions | B |
| Actions | Intensity outside [0,1], null, NaN/Inf | Validation error before optimisation | B/D |
| Actions | Existing renewable/EV adoption | Intensities apply to remaining eligible transition | B |
| Actions | Capex and depreciation | Budget uses investment cash; profit follows declared accounting, no double subtraction | B |
| Actions | Same inputs across callers | Manual, optimiser and deterministic risk replay agree | B/C/D |
| Actions | Repeated calls | Baseline inputs remain unchanged | B |
| Optimisation | Budget/min-profit/carbon target | Correct sign, units and shared horizon | B |
| Optimisation | Zero BAU carbon | Defined reduction-target behaviour; no division by zero | B |
| Optimisation | No feasible strategy found | Empty result/status; no invented recommendation | B/D |
| Optimisation | Dominated or duplicate outputs | Filter returned set and preserve valid configs/IDs | B |
| Optimisation | Search approximation | Label approximate frontier; never promise global completeness | B/D |
| Risk | Zero variance | Matches deterministic simulation | C |
| Risk | Same seed | Reproducible worlds; shared draws for strategy comparisons | C |
| Risk | Active thresholds change | Pass constraints to risk evaluation; invalidate old probabilities | C/D |
| Risk | Missing carbon target | Evaluate profit reliability alone | C |
| Risk | No candidate meets policy | Explicit none-qualifies; never silently lower required reliability | C |
| Risk | Missing evaluation for candidate | Unavailable risk, not perfect reliability | C |
| Risk | Assumed distributions | Label conditional simulated intervals/probabilities and actual sample count | C/D |
| SHAP | Feature order/model mismatch | Reject or recompute against correct trained model | A |
| SHAP | Explanation wording | Predictive drivers, not causal intervention proof | A/D |
| Benchmark | Missing/incompatible peers | Unavailable; no invented percentile | C |
| Benchmark | Zero revenue/employees | Relevant intensity ratio unavailable | C |
| Benchmark | Different scope, currency or reporting period | Reconcile transparently or do not compare | C |
| Benchmark | Grid data used as company peers | Reject that interpretation | C |
| UI | Pareto point selected | Exact candidate ID/config drives all cards and comparisons | D |
| UI | Inputs changed while computing | Mark stale results; prevent old responses replacing current scenario | D |
| UI | Model training on slider change | Reuse trained artifacts; do not retrain every request | A/D |
| UI | Invalid input, exception, empty results | Readable error and preserved inputs, not fake zero KPIs | D |
| UI | Optional module/API unavailable | P0 continues; optional panel disabled or labelled unavailable | D |
| UI | Unsafe text/JSON or arbitrary artifact paths | Escape/validate inputs and use controlled artifact loading | D |
| Demo | Synthetic observations and assumptions | Visible labels; no real-business validation claim | All |
| Demo | Clean/offline start | Saved data/models and local Plotly available for core demo | D |

## Minimal independent arithmetic checks

- A twelve-month BAU with 100 kg CO2e and £1,000 operating profit each month totals 1,200 kg and £12,000. Zero config preserves both.
- If a test action produces 90 kg and £1,010 per month, totals are 1,080 kg and £12,120: a 10% carbon reduction and £120 operating-profit increase. Any investment outlay is reported separately under the declared accounting model.
- For a £500 budget, £500 investment is feasible and £501 is not, subject to an explicitly documented numeric tolerance.
- With zero-variance effect parameters, Monte Carlo reproduces deterministic outcomes; target probabilities are 0 or 1 according to the supplied constraints.

These are test fixtures, not claimed intervention performance. Record actual test commands/results and the inspected demo scenario at the release gate.

## Deeper verification cases

### Temporal modelling

Test at least one forecast issued before a held-out structural change. It may perform poorly; that is a valid result. Confirm that no preprocessing or model selection used the held-out distribution. For rolling features, deliberately change the current/future target and verify the prediction's origin-available inputs remain unchanged.

Test missing month detection separately from ordinary missing values. A lag of 12 rows is not a seasonal lag if months have gaps. Training and future inference must share feature order and units. Loading a model with a mismatched schema must fail clearly rather than produce plausible nonsense.

If clipping negative carbon forecasts, retain raw predictions and disclose the transformation; compare evaluation consistently. Negative profit requires no such physical clipping. Unsupported horizons return validation errors instead of repeating the same 12 months to fabricate five years.

### Interaction and accounting invariants

Use an independently constructed baseline with electricity, fleet fuel and residual components. Check efficiency affects only eligible energy and EV conversion simultaneously adds electricity and removes fuel. Test renewable share with a nonzero initial value: zero action cannot undo existing renewable procurement.

Do not demand that every intervention always improves profit or carbon: costs, substitution intensity and synthetic parameters can make an action unattractive. Demand instead that results follow declared formulas, remain physically/accountingly coherent and report effects honestly.

For a £1,200 test asset with a five-year straight-line life, depreciation is £20 per month. Twelve months gives £240 depreciation; upfront cash remains £1,200. Verify a profit calculation does not also deduct the full £1,200. If a partial-year start is supported, monthly timing must determine depreciation explicitly.

### Search validity

Construct a small finite set of known configs and independently calculate feasibility/dominance as a test oracle for filtering. NSGA-II need not return the same exact floating-point configs across library versions, but every displayed result must match its own config and the shared engine.

A run returning no feasible candidate is distinguished from invalid input, engine failure and solver/runtime failure. Budget exactly at cost is feasible under stated tolerance; a materially greater cost is not. Never apply currency display rounding before this test.

### Risk and policy behaviour

Use a labelled synthetic risk fixture in which one candidate has higher expected carbon reduction but worse profit reliability. Check conservative/balanced/aggressive selection against the declared thresholds, including ties and no qualifying candidate. An unchanged choice on real scenarios is not a bug if the policy is genuinely evaluated.

If only ten of forty candidates were simulated, show evaluated coverage. Do not assign the other thirty zero uncertainty. Intervals must have ordered finite bounds, and probabilities must use the actual number of evaluated samples. If failed samples occur, report/fail the evaluation explicitly; silently dropping them can bias the probability.

Risk thresholds refer to horizon totals and to the same BAU reduction denominator. Changing the baseline, target, sample assumptions or seed must update identities and invalidate relevant caches. Preserve the distinction between action uncertainty and forecast uncertainty.

### UI and reproducibility

Open two tabs with different constraints and confirm results do not leak across them. Change the selected candidate after adjusting budget and ensure stale candidates cannot be applied/exported as current. Exported metrics must come from trusted server results, not numbers submitted by the browser.

Test long labels, escaped markup, unsupported artifact IDs and excessively large payloads. Optional external API timeouts should produce an unavailable panel while local manual/optimised computation remains usable. A clean start must find its trusted artifacts using project-relative configuration rather than a developer's private absolute paths.

## Release evidence to record

Record the environment versions, exact tests run, cold-start command, actual forecast metrics, generation/model seeds, baseline/config IDs, optimiser settings/evaluation count, risk sample count, observed latency and remaining limitations. Inspect the rendered interface as well as tests. Passing numeric tests does not prove the demo flow is legible; a polished demo does not prove the calculations.
