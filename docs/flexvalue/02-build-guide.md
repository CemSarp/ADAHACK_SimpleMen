# FlexValue implementation plan

**For coding agents:** Implement one requested iteration at a time. Use the repository's applicable development instructions. Do not autonomously spawn other agents, commit, push, deploy or expand scope. The human team coordinates four lanes using the prompt pack.

**Goal:** A local Django/Plotly application that schedules a fixed compute workload using real half-hourly prices/carbon and quantifies the value of individual constraint relaxations.

**Architecture:** A Django monolith with a pure Python scheduling engine, immutable JSON snapshots and bounded SciPy MILP solves. Provider ingestion is a separate management command; page requests use saved data. Plotly displays server-computed results.

**Stack:** Existing Python 3.11 Conda environment; latest compatible Django 5.2 patch; NumPy, SciPy, Plotly, requests; standard-library unittest/Django TestCase. No React, DRF, Celery, Redis, Docker or external optimiser service is needed.

**Specification:** [01-architecture.md](01-architecture.md). Exact behaviours and numerical boundaries are defined there; [04-edge-cases.md](04-edge-cases.md) is the acceptance checklist.

## Global constraints

- Four owners; eight hours; complete end-to-end integration by hour 4, feature freeze by hour 6.
- Maximum eight jobs, eight installed workers and 52 padded slots in the application.
- Half-hour UTC slots; non-preemptive mandatory jobs; one worker per job.
- Ex-VAT GBP, kg CO2 and GBP/tCO2; no invented provider observations or savings.
- Same padded accounting window and powered installed capacity in all comparisons.
- One second per solve, 15 seconds per request/batch by default, with explicit partial/timeout states.
- Preserve the existing environment and unresolved Git state. No automatic destructive cleanup.
- Core works fully offline, including Plotly JS and CSS/fonts.
- Suggested function signatures below are the shared contract. Amend them together before diverging implementations.

## Review focus

1. Providers return different boundary intervals and reversed ordering: data task must test exact alignment.
2. Baseline infeasibility is not problem infeasibility: engine and integration tasks must test this distinction.
3. Higher carbon preference can increase cash cost: analysis/UI tasks must retain signed cash deltas.
4. Capacity relaxation must not manufacture free new hardware: analysis task must test installed-worker limits and unchanged fixed energy.
5. Time-limited incumbents and stale browser responses must not be shown as proven optima/current results: engine and HTTP/UI tasks own these tests.

## Four-person ownership

| Owner | Role | Owns after contract freeze | Main deliverable |
|---|---|---|---|
| A | Data and accounting | `data.py`, `metrics.py`, capture command, snapshots, data/metrics tests | Real aligned input data and auditable cost/carbon totals |
| B | Scheduling and flexibility | `baseline.py`, `optimizer.py`, `analysis.py`, engine/analysis tests | Correct schedules, constraints and flexibility values |
| C | Product and visualisation | `charts.py`, templates, static assets, chart tests, demo script | Legible controls, schedules, trade-offs and constraint table |
| D | Integration and reliability | Django `config`, `domain.py`, `validation.py`, `services.py`, forms/views/URLs, HTTP tests, environment manifest | Running application, stable contracts, integration and final checks |

All four agree on `domain.py`; D is its sole editor after hour 0.5. If B needs a new result field, propose it to D and C before adding it. A owns metric definitions; B uses A's independent evaluator. D owns dependencies and root settings; teammates request additions instead of editing them concurrently.

Use separate developer clones/branches if each human is working independently. If agents share one checkout, enforce exclusive file ownership and avoid branch changes or shared staging. Never have multiple agents run Git operations against the same index. Check current merge/rebase status before creating branches; do not automatically reset or abort it.

## Schedule and dependency order

| Time | A | B | C | D | Joint checkpoint |
|---|---|---|---|---|---|
| 0:00–0:30 | Validate feed shape | Agree optimiser types | Sketch one-screen flow | Inspect Git/env, publish contracts | Defaults, interfaces and ownership agreed |
| 0:30–1:30 | Snapshot loader + metrics | Tiny oracle + baseline + MILP | Templates and charts from fixture | Skeleton, forms, service stubs | All imports work against same contract |
| 1:30–2:30 | Replay snapshot + ingestion command | Real-snapshot solves | Connect real result objects | End-to-end POST integration | Editable jobs → valid cheapest schedule |
| 2:30–4:00 | Data/units edge cases | Individual relaxations | Constraint table and inspect flow | Budgets, cache, errors | Core FlexValue demo works offline |
| 4:00–5:00 | Provenance review | Trade-off sweep + pairwise thresholds | Carbon control and linked plots | End-to-end assertions | Quantities and labels agree everywhere |
| 5:00–6:00 | Optional second region | Profile/fix solver | Polish + conditional annual view | Export and final integration | Feature freeze; optional features only if green |
| 6:00–7:00 | Audit sample numbers | Review edge cases | Demo rehearsal | Offline/cold-start run | Fix blockers only |
| 7:00–8:00 | Explain data in pitch | Explain algorithm | Present product story | Drive demo and fallback | At least two full rehearsals |

Reserve a five-minute integration check at each hour. The hour-4 criterion is a working application, not four finished but incompatible components.

## Shared Python interfaces

Define dataclasses exactly once following the architecture's type table. Suggested public functions:

```python
# data.py
load_snapshot(snapshot_id: str) -> Snapshot
normalise_snapshot(price_records: list[dict], carbon_records: list[dict],
                   provenance: dict, horizon_start_utc: datetime,
                   horizon_end_utc: datetime) -> Snapshot

# validation.py
validate_scenario(snapshot: Snapshot, scenario: Scenario) -> None
# Raise structured ValidationError with code, field and readable detail.
scenario_digest(snapshot: Snapshot, scenario: Scenario,
                options: dict) -> str
# Pure canonical hashing; services.py imports/re-exports this same helper.

# metrics.py
evaluate_schedule(snapshot: Snapshot, scenario: Scenario,
                  assignments: tuple[Assignment, ...],
                  carbon_price_gbp_per_tonne: float) -> Metrics
validate_assignments(snapshot: Snapshot, scenario: Scenario,
                     assignments: tuple[Assignment, ...]) -> None

# baseline.py
build_baseline(snapshot: Snapshot, scenario: Scenario,
               carbon_price_gbp_per_tonne: float) -> SolveResult

# optimizer.py
solve_schedule(snapshot: Snapshot, request: SolveRequest) -> SolveResult

# analysis.py
value_constraints(snapshot: Snapshot, request: SolveRequest,
                  original: SolveResult,
                  batch_budget_seconds: float = 15.0) -> tuple[ConstraintValue, ...]
evaluate_tradeoffs(snapshot: Snapshot, scenario: Scenario,
                   weights: tuple[float, ...],
                   batch_budget_seconds: float = 15.0) -> tuple[SolveResult, ...]
pairwise_break_even(a: Metrics, b: Metrics) -> float | None
annualise_savings(cash_saving_gbp: float, carbon_saving_kg: float,
                  operating_nights: int) -> dict

# services.py
analyse_scenario(snapshot_id: str, scenario: Scenario,
                 carbon_price_gbp_per_tonne: float) -> Comparison

# charts.py
build_input_charts(snapshot: Snapshot) -> dict
build_schedule_chart(snapshot: Snapshot, scenario: Scenario,
                     results: dict[str, SolveResult]) -> dict
build_tradeoff_chart(results: tuple[SolveResult, ...]) -> dict
```

Return Plotly-serialisable figure dictionaries from chart functions. HTTP is responsible for JSON encoding. The shared pure digest helper lets the engine attach `request_digest` without importing Django services. Use identical canonical option names across services and engine. For table/export references, assign a result digest from its input request and decoded assignment. Do not introduce a persistent result model just to identify a plotted point.

## Task 0 — establish a safe contract checkpoint

**Owner:** D, with 10-minute review by A/B/C.

**Files:** `config/`, `manage.py`, `scheduler/domain.py`, `scheduler/validation.py`, `scheduler/tests/test_contracts.py`, environment manifest, `docs/flexvalue/BUILD_STATUS.md`.

- [ ] Inspect `git status`, applicable AGENTS instructions and existing environment. Record the unresolved README conflict; do not overwrite it. If Git operations are blocked, continue file-level work and let the human integrator resolve the unrelated conflict.
- [ ] Validate Python 3.11 and available SciPy MILP; install only missing scoped dependencies into the project environment with the team's chosen method. Preserve existing packages; do not use `--prune`.
- [ ] Add the minimal Django project/app, URL and initial template. Keep framework configuration conventional.
- [ ] Define shared dataclasses, units and error structure. Validate NaN/infinity and boolean-as-integer cases explicitly.
- [ ] Add a four-slot in-memory oracle fixture for engine tests, and a distinct labelled UI fixture shaped like a real result. Tiny domain fixtures can have arbitrary valid slot counts; the UI's production snapshot loader enforces the 48+4 policy.
- [ ] Verify `python manage.py check` and `python manage.py test scheduler.tests.test_contracts` succeed.
- [ ] Publish a contract checkpoint to teammates using the team's normal Git workflow. Do not auto-commit if not authorised or if the index is conflicted.

**Gate:** One authoritative input/output shape; all team members can run Django and import domain objects.

## Task 1 — prove accounting and snapshot alignment

**Owner:** A. **Files:** `data.py`, `metrics.py`, management command, `data/snapshots/`, tests `test_data.py`, `test_metrics.py`.

**Consumes:** domain types. **Produces:** `load_snapshot`, `normalise_snapshot`, `evaluate_schedule`, `validate_assignments`.

- [ ] Write the unit test for one 1 kW worker, zero idle, PUE 1, two half-hours at 10 and 20 p/kWh and 100 and 200 gCO2/kWh. Expected: 1 kWh, £0.15, 0.15 kg CO2. At £100/t the weighted score is £0.165.
- [ ] Run the test, observe failure, then implement the independent evaluator and rerun.
- [ ] Test shuffled rates, the extra NESO leading interval, pagination, conflicting duplicates, a missing half-hour, null forecast versus valid zero forecast, and invalid UTC boundaries.
- [ ] Implement normalisation by exact interval timestamps. Preserve original raw files and hashes; never overwrite the research evidence.
- [ ] Import the saved London replay from `docs/flexvalue/research/` into an application snapshot. Confirm 52 aligned slots, with main horizon indices 2 and 50.
- [ ] Implement the separate capture command with bounded network access and atomic publication. Discover product metadata, reject export tariffs, record domestic/business eligibility.
- [ ] Provide capture/refresh documentation with a verified product and tariff from discovery, not a copied historic documentation example.
- [ ] Run `python manage.py test scheduler.tests.test_data scheduler.tests.test_metrics`.

**Gate:** B can load a real immutable snapshot; cash/carbon values are independently testable; offline mode performs no network calls.

## Task 2 — solve the same workload correctly

**Owner:** B. **Files:** `baseline.py`, `optimizer.py`, `test_optimizer.py`, `test_baseline.py`.

**Consumes:** domain types and A's evaluator; use the shared tiny fixture while A works. **Produces:** `build_baseline`, `solve_schedule`.

- [ ] Write the four-slot oracle tests in edge-case document E01. Assert cheapest and cleanest start indices and exact metrics.
- [ ] Write a separate brute-force enumerator inside tests for up to three jobs and six slots; compare its optimum with the MILP on at least five deterministic small cases. This test oracle must not call the solver's candidate/objective-building functions.
- [ ] Implement first-fit baseline using release time then original input order, checking deadline and capacity without dropping jobs.
- [ ] Implement sparse binary start choices, exactly-once and capacity constraints. Use all physically compatible starts rather than forcing the input order in the optimiser.
- [ ] Add independent assignment validation and interval partitioning to produce worker rows.
- [ ] Implement bounded cost/carbon endpoint tie-breaks and status mapping. Mock a valid incumbent at time limit, a missing incumbent and a corrupt incumbent.
- [ ] Test true infeasibility and a case where baseline misses a deadline but the optimiser is feasible.
- [ ] Run `python manage.py test scheduler.tests.test_optimizer scheduler.tests.test_baseline` and run one saved-data scenario.

**Gate:** Job count, duration, energy and constraints remain valid for every result; failures are represented honestly.

## Task 3 — integrate a useful vertical slice

**Owners:** D for orchestration; C for UI; each edits only owned files.

**Files:** `services.py`, forms/views/URLs and `test_views.py` for D; `charts.py`, templates/static and `test_charts.py` for C.

**Consumes:** real snapshot and engine. **Produces:** working `/` and `/analyse/` flow.

- [ ] D tests valid POST, malformed input, unknown snapshot ID and unsupported objective values using Django's test client.
- [ ] D implements one service orchestrating baseline, cheapest, cleanest and selected results under an overall budget. Reuse identical solves when selected lambda is zero.
- [ ] C renders source/time/proxy badges, an editable job form, metric comparison and Gantt/input charts using a labelled fixture initially.
- [ ] D and C replace the fixture at the service boundary with real results. Charts read returned metrics instead of recalculate them.
- [ ] Bundle Plotly JS locally from the installed package or another reviewed local distribution. Load it once; no font/chart CDN may be essential.
- [ ] Mark stale results when inputs change. Keep input values and readable errors after failed submissions.
- [ ] Verify the browser with network disabled: initial page and charts still render and optimisation still works.

**Gate:** Before adding more analysis, a judge can edit a deadline and obtain a valid schedule from real saved data.

## Task 4 — implement the central constraint table

**Owner:** B for analysis; C table; D endpoint/cache. **Files:** `analysis.py`, `test_analysis.py`, `/constraints/`, constraint partial.

- [ ] Write the E02 weighted-value example and tests that each experiment changes exactly one field.
- [ ] Enumerate deadline +2, release -2 and eligible concurrency +1 experiments. Create new immutable scenarios, leaving the original untouched.
- [ ] Re-optimise under the same objective and lambda. Compute original-optimum deltas, not baseline deltas.
- [ ] Separate objective improvement, cash saving and carbon saving. Mark exact/provisional/unavailable/restores-feasibility correctly.
- [ ] Test unchanged work and fixed idle energy for concurrency relaxation, plus the installed-capacity upper bound.
- [ ] Respect the batch wall-clock budget. Report unrun rows rather than blocking indefinitely or omitting them silently.
- [ ] C displays all candidate rules including zero-value ones and a readable reason where unavailable. Inspect a candidate's schedule; Apply makes a new scenario and invalidates previous results.
- [ ] Run relevant analysis/view tests and time the six-job replay batch. Record actual latency and solver statuses.

**Gate:** A deadline with value, a zero-value rule and an unavailable rule are all understandable. No additive “total value of all rules” is shown.

## Task 5 — add trade-offs and interpretable explanations

**Owners:** B/C/D in their own modules.

- [ ] Test `pairwise_break_even` with E01: £2,000/t, not £2/t or £2,000,000/t.
- [ ] Evaluate prescribed weights and pure endpoints, deduplicate identical schedules, remove clearly dominated evaluated points with documented numeric tolerance.
- [ ] Compute the selected exact lambda separately when it is not a preset. Cache by complete scenario/options.
- [ ] Build the Plotly scatter with direct schedule lookup. Show cash, carbon, weight and solve status in hover labels.
- [ ] Add whole-schedule pairwise threshold explanations with clear limited scope. Do not fabricate job-level causal thresholds.
- [ ] Test that increasing lambda does not increase optimal carbon among proven optima beyond tolerance; ties may have multiple valid assignments.
- [ ] Test zero-carbon and flat-price cases and a case with no trade-off.

**Gate:** The UI visibly distinguishes actual electricity cost from the internal carbon valuation.

## Task 6 — optional region and annual scenario

**Start only if Tasks 1–5 are integrated and passing by hour 5.**

- [ ] A loads the saved South Scotland data with confirmed metadata and matching intervals; D adds a two-region service with explicit identical assumptions.
- [ ] Compare each region using its own tariff and carbon input. Preserve the site-specific baseline and original optimum for its own constraint analysis.
- [ ] C labels the comparison hypothetical. Avoid claims about relocation or general annual superiority.
- [ ] B implements multiplication by operating nights, integer 1–365, default 250; C labels “If this same saving repeated for N nights”. £4 × 365 = £1,460 is arithmetic, not a forecast.
- [ ] Test signed savings and kg-to-tonne display. Annualise the savings difference, not the 26-hour absolute energy total.

**Cut first:** regions, annual panel, elaborate switch thresholds. **Never cut:** correct units, status handling, source labels, offline operation or independent constraint checks.

## Task 7 — validate, export and rehearse

**Owner:** D coordinates; all four inspect their own claims.

- [ ] Add JSON export with inputs, assumptions, raw hashes, schedules, metrics, solver statuses and source metadata. Reject stale scenario/result combinations.
- [ ] Run `python manage.py check` and `python manage.py test scheduler.tests` in the actual project environment. Record results, versions and elapsed times in BUILD_STATUS; do not report a command as passing if it was not run.
- [ ] Cold-start the local server from documented setup and run with external network disabled.
- [ ] Inspect charts at presentation size, long job names, narrow screen and errors. Check labels against evaluator values, including negative cash savings.
- [ ] Run six demonstrations: normal replay, lambda change, valuable deadline, zero-value rule, infeasible jobs and missing/invalid snapshot.
- [ ] Read the snapshot manifest aloud in rehearsal: dates, proxy tariff and forecast/replay status must be unambiguous.
- [ ] Prepare a recorded or screenshot backup clearly labelled as such, not a fake interactive run.
- [ ] Final demo order: business question → workload → schedule improvement → price one deadline → carbon preference → honest limitations. Each teammate presents their contribution.

## Definition of done

The app starts from documented instructions, works offline, completes the same jobs, displays valid schedules, calculates verified units, values individual constraints against a consistent optimum, preserves infeasibility/time-limit states, exposes assumptions and has a rehearsed demo. Stretch features do not compensate for a failing core criterion.
