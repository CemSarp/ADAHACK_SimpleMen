# CarbonOpt parallel build guide

Follow [CENTER.md](../team-execution/CENTER.md) and the four role files. This guide replaces the earlier scheduling implementation plan.

## Four owners

| Owner | Execution file | First deliverable |
|---|---|---|
| A — Data/ML | [Person A](../team-execution/PERSON_A_DATA_ML.md) | Synthetic monthly history and a forecast-shaped fixture |
| B — Decision science | [Person B](../team-execution/PERSON_B_DECISION_ENGINE.md) | Deterministic central action simulator |
| C — Risk/data | [Person C](../team-execution/PERSON_C_RISK_DATA.md) | Independent numerical checks and agreed uncertainty hook |
| D — Product/integration | [Person D](../team-execution/PERSON_D_PRODUCT_INTEGRATION.md) | Shared contracts and Django skeleton |

## Implementation order

1. **First 30 minutes:** freeze shared units/types and publish the labelled 12-month integration fixture. D owns shared files; all owners agree on their fields.
2. **Hours 0.5–2:** A generates/validates history and starts forecasting; B implements the engine against the fixture; C checks accounting and prepares risk contracts; D builds manual what-if and charts.
3. **Hours 2–4:** replace the fixture with A's model baseline, connect B's NSGA-II output, and inspect candidate configurations in D's dashboard. C helps validate P0 while preparing optional risk code.
4. **Hours 4–5.5:** only after P0 works, connect Monte Carlo and real risk-based selection, SHAP, sourced benchmarks and scenario comparison as time permits.
5. **By hour 6:** freeze features and preserve a reproducible working state through the team's authorised Git workflow.
6. **Hours 6–8:** clean-start checks, integration repairs, source/claim verification and demo rehearsal.

## Setup and handoffs

D inspects the actual checkout/environment before adding dependencies. Use Python 3.11 or 3.12, Django, Plotly, NumPy/Pandas, scikit-learn, pymoo and one of LightGBM/XGBoost. Add SHAP at P1. Preserve any existing environment; do not assume a Conda manifest or unresolved merge exists in every checkout.

A/B/C return plain serialisable objects. Every handoff includes an input fixture, output example, verification command and known limitations. Change CENTER's contracts before changing consumers; do not let four agents create conflicting types or edit shared settings simultaneously.

## Gates

- **Manual gate:** zero config matches BAU; sliders invoke the real shared engine.
- **P0 gate:** model forecast → shared simulation/optimisation → feasible candidate inspection and manual comparison works end to end.
- **P1 gate:** risk actually affects selection; SHAP explains predictions; benchmark source/normalization is visible.
- **Release gate:** clean start, no dead controls, correct units, no stale result identity and a rehearsed fallback.

P0 must work with risk, SHAP, benchmarks and chatbot disabled. Cut P2 before compromising P0. Use [the acceptance checklist](04-edge-cases.md); report tests actually run, not assumed success.

## Concrete tasks and handoff artifacts

### Task 0 — shared foundation (D, reviewed by all)

- Inspect actual repository state and applicable instructions. Preserve unrelated changes.
- Freeze `src/contracts.py`, result statuses, six action keys, month conventions and monetary/carbon units from CENTER.
- Publish `tests/fixtures/baseline_12m.json`: labelled synthetic, reconciled carbon components, profit anchor and activity fields.
- Establish the minimal Django app and one documented product environment. Choose a single forecasting family with A; record installed versions.
- Verify that A/B/C can import the shared contract without importing Django, and the fixture round-trips through JSON.
- Hand off exact import names, fixture location and run/check commands. Do not wait for model training to start B/C/D.

### Task 1 — data and forecast (A)

- Generate seeded monthly history with common activity drivers and documented structural changes.
- Validate month continuity, physical ranges and component accounting; save a compact diagnostic report.
- Implement shifted lag/rolling features and a seasonal-naive reference.
- Train one selected model family separately for carbon and profit; evaluate the actual 12-step deployment procedure on temporal holdout.
- Return `ForecastBundle` with reconciled future components, assumptions and independent per-target metrics.
- Provide training/inference commands and trusted model artifacts with metadata. D swaps the fixture loader for this output without changing consumers.

Meaningful checks: modifying held-out targets cannot alter an already-issued forecast; zero raw components with positive forecast total is rejected; constant-target R² is unavailable; naive/ML errors remain visible even if ML loses.

### Task 2 — action engine and manual flow (B + D)

- B defines effect/cost parameters, eligible activities, interactions and accounting once.
- B implements immutable `simulate_strategy` with optional sampled parameter overrides.
- Start with independent zero-config and single-action arithmetic examples, then interactions and maximum intensity.
- D connects manual controls immediately; the page displays returned metrics, not client-side reimplementations.
- A/B check forecast totals, component shares and the profit anchor reconcile.
- C independently checks investment versus operating-profit treatment and shared units.

Gate: identical baseline/config produces identical manual/backend results, no input mutation and no duplicate savings.

### Task 3 — NSGA-II and P0 completion (B + D, C verifies)

- B wraps the engine in six-variable pymoo objectives and constraints with explicit sign conventions.
- Start with the small seeded run described in architecture; record actual evaluation count and latency.
- Re-evaluate returned configurations, check feasibility in raw units, and filter duplicates/dominated candidates.
- D displays the actual candidate IDs and configurations on click, plus a clearly described P0 recommendation policy.
- Handle infeasible inputs, no feasible candidate found, computation failures and stale inputs without fake zero KPIs.
- Run the whole path against A's forecast, not only the fixture.

Gate: a judge changes a constraint, runs optimisation, inspects a real candidate and compares a manual strategy through the same engine.

### Task 4 — risk and selection (C + D, B supports)

- Agree effect-parameter names and bounded uncertainty assumptions with B.
- Pass the actual `Constraints` into risk evaluation; use shared sampled worlds across alternatives.
- Verify zero-variance equality with deterministic simulation before increasing sample count.
- Record seed, real sample count and parameter/constraint identities; disclose any candidate shortlist.
- Implement the center's conservative/balanced/aggressive policy with none-qualifies and unavailable states.
- D enables the risk control only after it affects selection; changing thresholds invalidates cached risk.

Gate: a constructed case demonstrates policy behaviour; real cases may legitimately keep the same recommendation. No calibrated-confidence or global-risk-optimum claim is made.

### Task 5 — optional explanations and context (A/C/D)

- A returns model-aligned SHAP values and labels, separately from action-selection explanations.
- C validates benchmark provenance, reporting period, normalization and comparable boundaries; missing credible peers means unavailable.
- D adds saved-config scenario comparison by reusing shared outputs; don't recalculate strategies in JavaScript.
- Attempt P2 LLM tools only after these gates are stable and rehearsal time is protected.

### Task 6 — release checks (D coordinates)

- Run numerical and contract checks, then actual Django system checks and relevant tests in the product environment.
- Cold-start with documented commands and no network; verify saved data/models and local chart assets.
- Inspect chart labels, long text, errors, missing optional panels and stale-result handling in the browser.
- Match headline totals and selected candidates against the independent evaluator.
- Save the scenario, artifact identities, tested versions, actual timings and remaining limitations.
- Rehearse two complete demonstrations. Preserve a clearly labelled fallback recording or screenshots if desired.

## Verification commands and reporting

Once the Django scaffold exists, its standard checks include `python manage.py check` and the team's documented test command, such as `python manage.py test`. Do not claim these have run before implementation. Training/generation commands are published by A rather than guessed by D.

A handoff report contains: deliverable, exact call/import, fixture or artifact ID, command actually executed, result, remaining limitation and next consumer. Update CENTER's status board at each gate; local notebook success alone is not integration evidence.

## What to cut when time is short

Cut chatbot/LLM first, then unsupported long horizons, external benchmark and additional visual polish. Preserve the complete P0 chain, numeric correctness and synthetic/source labels. Reduce risk sample count with disclosure, shortlist candidate evaluation with disclosure, and cap optimiser work with recorded settings. Do not quietly change algorithms, hide failed forecasts or manufacture feasible points to make the demo look complete.

## Three-minute demo

1. Explain the business decision and show synthetic history/current metrics.
2. Show the evaluated 12-month BAU forecast and its limits.
3. Set budget/profit/carbon constraints and optimise.
4. Click a candidate; show its exact action intensities, investment and outcomes.
5. Change a manual action and compare through the same engine.
6. If available, change risk preference and explain selection. Show SHAP/benchmark briefly with labels.
7. State that this prototype demonstrates decision support on declared synthetic assumptions; a real deployment needs calibrated data and intervention evidence.
