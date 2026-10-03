# FlexValue architecture and decision register

## 1. Product and scope

A small AI lab owns compatible compute workers and pays for electricity. It must finish a known batch of training, evaluation and offline inference jobs before deadlines. FlexValue proposes a schedule and asks which operational rules are worth renegotiating. It does not execute jobs, connect to GPU clusters, predict job quality, or move data between real sites.

Success means showing the same completed workload under three schedules: a transparent current-policy baseline, minimum electricity cost, and a selected cost/carbon preference. Every feasible recommendation respects all original constraints unless explicitly marked as a hypothetical relaxation.

The challenge asks for carbon quantification, alternative business strategies and a financial/environmental balance. Here the quantified boundary is the modelled compute electricity, not the business's full footprint. If completed output, revenue and other costs stay unchanged, electricity-cost reductions improve operating profit by the same amount. Do not invent revenue predictions or equate an internal carbon price with a real electricity bill.

## 2. Assessment of the proposed features

| Proposal | Decision and why |
|---|---|
| Real half-hourly tariffs | Keep. They make financial savings observable and avoid pretending a flat tariff rewards time shifting. Save original responses and metadata before building the UI. |
| Own compute | Keep. It gives the business exposure to electricity prices. A fixed-price cloud VM generally does not pass through the site's half-hourly electricity cost. |
| GPU wattage as energy input | Refine. Rated GPU power is not measured average system draw. Prefer editable average whole-worker wall power, document where it came from, and separate idle/facility overhead. |
| Cost plus a carbon-price weight | Keep after cheapest scheduling works. It gives a clear preference with units, but the carbon component is a policy valuation, not cash paid. |
| Price every constraint | Make this the central feature. Re-optimise one changed rule at a time; compare with the original optimum under the same objective. |
| Regional comparison | Stretch. Use actual tariff and carbon region mappings, identical job assumptions and timestamps. Treat it as a hypothetical site comparison, not migration advice. |
| Multiply a night by 365 | Replace with an editable repeated-night scenario, default 250 nights. 365 remains an option. The result assumes identical conditions every night and is not a forecast. |
| Add predictive ML, Monte Carlo, SHAP or NSGA-II from CarbonOpt | Defer. No outcome training dataset was supplied; the scheduling problem has a direct mathematical formulation. These features add integration cost without improving the core answer in eight hours. |

Price and carbon may align on the selected day. Do not alter real observations to manufacture a trade-off. If the same schedule is cheapest and cleanest, show that useful result. A separate synthetic teaching fixture may demonstrate a conflict, with a persistent label.

## 3. Decisions to confirm before coding

These are recommended defaults. Review them together for no more than 20 minutes. Later discoveries can revise a decision, but must also update its tests and dependent contracts.

| ID | Decision | Recommended default | Why and consequence |
|---|---|---|---|
| A01 | Customer and output | Small AI lab, advisory batch schedule | Fits the brief's compute framing and keeps real execution out of the critical path. |
| A02 | Framework | Django 5.2 LTS, templates, small vanilla JS, Plotly | Matches the team preference and existing Python 3.11 environment. Avoids a second application stack. Use the latest compatible 5.2 patch at implementation and record actual versions. |
| A03 | Optimisation library | `scipy.optimize.milp`, HiGHS backend | SciPy is already declared. Binary start decisions model contiguous jobs and capacity exactly; no new solver service is needed. |
| A04 | Unit of capacity | One job uses one whole homogeneous worker | Avoids GPU packing, heterogeneous runtimes and fragmented allocation. A worker can represent one identically configured multi-GPU server. |
| A05 | Execution | Non-preemptive, mandatory jobs, fixed duration and power | Prevents pausing training arbitrarily, dropping costly jobs or changing delivered work to improve results. |
| A06 | Job limits | Default six jobs; accept one to eight | Keeps repeated solves and interface validation predictable. |
| A07 | Time | UTC internally; Europe/London for display | DST cannot duplicate or remove UTC slots. Display date and offset around overnight/DST boundaries. |
| A08 | Horizon | 24 elapsed hours, 48 half-hour slots | Limits optimisation size. A local calendar day can have 46 or 50 slots; do not silently call a fixed 48-slot horizon a local day. |
| A09 | Padding | Fetch one hour before and after, 52 total slots | Supports +1-hour deadlines and -1-hour release times with real data, while original jobs stay inside the central horizon. |
| A10 | Tariff eligibility | Verified business import tariff if readily available; otherwise domestic Agile explicitly marked as proxy | The live catalogue listed `AGILE-24-10-01` as `is_business=false`, `direction=IMPORT`. A real price is not proof of a business contract. Timebox business-feed exploration to 20 minutes. |
| A11 | Money basis | Use `value_exc_vat / 100` as GBP/kWh throughout | Consistent comparison for the model; label excluding VAT. Do not add a guessed VAT rate, tax treatment or reproduce a full bill. |
| A12 | Electricity accounting | Average wall active draw, installed-worker idle draw, facility multiplier | GPU TDP alone omits the host and does not represent actual utilisation. Defaults are illustrative estimates, visibly editable. |
| A13 | Carbon | NESO regional `forecast`, gCO2/kWh | Use one field consistently. This estimates electricity-associated CO2, not lifecycle CO2e or marginal grid emissions avoided. |
| A14 | Baseline | Earliest feasible first-fit by release time then input order | Reproducible policy baseline. It is not an optimum and may fail even when an optimised schedule is feasible. |
| A15 | Objective | Cash minimum first; optional GBP + lambda × tonnes CO2 | Keeps monetary savings and chosen carbon valuation distinct. Always also calculate the pure-carbon endpoint. |
| A16 | Trade-off display | Evaluated, deduplicated schedules; label “evaluated trade-offs” | Weighted sums can miss unsupported nondominated schedules in a discrete problem. Do not claim a complete Pareto frontier. |
| A17 | Constraint value | Original optimal objective minus one-rule-relaxed optimal objective | Isolates the value of a rule. Comparing to a poor baseline confounds scheduling improvements with new flexibility. |
| A18 | Capacity experiment | Unlock one additional installed, already powered worker | A true relaxation without buying hardware or changing idle footprint. Do not imply an extra server is free. |
| A19 | Persistence | Versioned JSON snapshots and examples; no user accounts or product models | Demo data is small. Avoid schema/migration/authentication overhead. Django's default SQLite may exist but must not be required for scenario storage. |
| A20 | Execution model | Bounded synchronous requests; compute curves/rankings on explicit buttons | Avoid Celery, Redis and WebSockets. A tiny cached problem does not justify a distributed job system. |
| A21 | Caching | Process-local Django cache with canonical scenario hash | Enough for a single local server; keys include data hashes and all numerical inputs so results cannot leak between scenarios. |
| A22 | Demo reliability | Offline snapshot mode is the default; live refresh is separate | Provider availability and tomorrow's unpublished prices cannot break the presentation. Never disguise replay data as live. |
| A23 | Regional scope | London first; South Scotland second | NESO IDs and tariff letters are different identifiers. Research verified example postcode mappings, not every possible address. |
| A24 | Uncertainty | Display estimated power and forecast/replay provenance; optional simple sensitivity | A Monte Carlo band built from guessed distributions would not be a calibrated confidence interval. |
| A25 | Annualisation | Savings × selected operating nights; default 250 | A transparent assumption is defensible. Seasonal variation and forecast error make one-night scaling unsuitable as a yearly prediction. |
| A26 | Deployment | Local Django runserver for judging | Shipping a public multi-user service is outside the eight-hour MVP. Document its development-only status. |
| A27 | Dependencies | Extend existing Conda environment, preserve existing packages | Avoid breaking teammates' setup. Add Django and test tooling only as needed; do not prune or replace the environment. |
| A28 | UI output | Three linked charts and one actionable table | The schedule, inputs and decision trade-off each answer a different question. A decorative dashboard would consume time without explaining the decision. |
| A29 | Approval of experiments | What-if values do not change the original job | A deadline might be contractual and a release time might be a hard data dependency. “Apply” creates a new scenario after a deliberate click. |
| A30 | Scope of savings | Modelled electricity only | Standing charges, labour, equipment capex, networking, demand charges and delivery penalties are outside the model. Declare this near relevant output rather than in a hidden disclaimer. |

## 4. Mathematical model

### Time and jobs

Let the padded data window contain 52 contiguous UTC half-hour slots, indexed 0–51. The ordinary scheduling horizon is slots [2,50). Job release `r_j` and exclusive finish deadline `d_j` are boundary indices; a job has integer duration `L_j` in slots.

Its allowed starts are `s` such that `s >= r_j` and `s + L_j <= d_j`. A job ending exactly at the deadline is valid. Job occupancy is `[s, s+L_j)`, so adjacent jobs do not overlap. Initial default jobs have `2 <= r_j < d_j <= 50`. A relaxation may use padding up to boundaries 0 and 52. The engine accepts any valid window inside the snapshot. After Apply, preserve extended job boundaries, expose the padding choices in the UI and show an extended-window banner; do not reset them to the central horizon. Further experiments outside the captured window are unavailable.

Each job is required exactly once and occupies one worker for all its slots. Tasks cannot be split, accelerated, postponed past the permitted horizon, or assigned a different amount of work.

### Power and baseline energy

Inputs are:

- `installed_workers`, integer 1–8, default 2.
- `concurrency_limit`, integer 1–installed_workers, default 1.
- `idle_kw_per_worker`, finite 0–20, default 0.15.
- `active_wall_kw` for each job, finite and strictly positive, at least idle draw, maximum 20.
- `facility_multiplier`, finite 1–3, default 1.10.

All defaults are demonstration assumptions, not hardware measurements. `active_wall_kw` is the whole worker's average wall draw while that job runs, before the facility multiplier. If the user already has facility-inclusive wall energy, use multiplier 1 rather than double-count cooling.

For a slot t, with active jobs J(t):

`energy_kwh[t] = 0.5 × facility_multiplier × (installed_workers × idle_kw_per_worker + sum(active_wall_kw[j] - idle_kw_per_worker for j in J(t)))`

This assumes all installed workers remain powered across the **same padded 26-hour accounting window** for all schedules and counterfactuals. The screen explains that the scheduled work covers 24 hours and padding supports flexibility experiments. Calculate fixed idle energy once and dynamic job increments separately. Also show work-attributable energy if helpful; do not label dynamic incremental energy as total facility energy.

The fixed idle component stays identical when concurrency is unlocked. A scenario that physically adds a server needs extra idle energy and capex and is excluded. Negative prices cannot cause additional jobs, extra runtime, or purposeful idle-power inflation because those quantities are fixed inputs.

### Cost, emissions and objective

`electricity_gbp = sum(energy_kwh[t] × price_gbp_per_kwh[t])`

`carbon_kg = sum(energy_kwh[t] × intensity_gco2_per_kwh[t]) / 1000`

`objective_gbp_equivalent = electricity_gbp + carbon_price_gbp_per_tonne × carbon_kg / 1000`

Use finite float64 values for optimisation and full precision for aggregation; round only for display. Inputs originating as decimal rates must retain their precision until converted. This is a planning estimate, not utility invoice reconciliation.

For each feasible start, introduce binary x[j,s]. Require `sum_s x[j,s] = 1` for each job and `sum(x[j,s] covering t) <= concurrency_limit` for each slot. Precompute the dynamic cost/carbon contribution for each start. Fixed idle cost/carbon does not change optimisation but must be restored in reported totals. Capacity constraints use a sparse matrix. Do not solve a continuous relaxation and round job assignments.

Run separate modes `cost`, `carbon`, and `weighted`. Set `mip_rel_gap=0.0` to seek a proof within solver numerical tolerances rather than deliberately accepting a loose relative gap; the time limit still permits a provisional incumbent. For cost/carbon endpoints, use a second solve to minimise the other metric while keeping the first within documented absolute tolerance (GBP 1e-7, kg 1e-7), with a shared time budget. This avoids displaying a dominated endpoint due merely to an objective tie. If the second solve times out, retain the valid primary optimum and disclose tie-break incompleteness. Weighted ties may produce different equally valid assignments; deterministic input ordering is required, unique assignment output is not.

`objective_gbp_equivalent` always means the reporting score at the request's lambda, not SciPy's raw objective in every mode. In `carbon` mode the solver minimises kg directly; never label that raw solver number as GBP. The UI's selected schedule always uses `weighted` (including lambda=0). Constraint valuation accepts `weighted`, or `cost` with lambda=0, and verifies the original result's request identity; it does not accept a pure-carbon endpoint as a monetary-objective optimum.

Validate every decoded schedule independently: every job once, integral starts, legal windows, concurrency and recomputed totals. Solver success alone is not sufficient evidence of an intact data pipeline.

### Carbon-price switch explanations

For two complete schedules A and B where B costs more but emits less:

`lambda_break_even = 1000 × (cost_B - cost_A) / (carbon_A_kg - carbon_B_kg)`

This is the price in GBP/tCO2 at which those two schedules have equal objective value. It is not automatically a global optimum switch: a third schedule can beat both. Label it “pairwise break-even between these evaluated schedules.” To claim a globally preferred switch, solve immediately around the threshold and validate the alternatives.

For the MVP, explain whole-schedule changes. “Job 3 alone becomes worth moving at £Y” is only justified if other allocations are held fixed and feasibility is checked. Shared capacity commonly makes several job movements interdependent.

A carbon-price range 0–5,000 GBP/tCO2 is a demonstration control, with presets 0, 50, 100, 250, 500, 1,000, 2,000 and 5,000. It is not a recommendation about real carbon prices. Include both pure endpoints even if the finite weight range does not reach the cleanest solution. Solve the selected numeric value explicitly; never silently use the nearest cached preset.

### Value of a constraint

Starting from the optimum for the selected objective and unchanged data, run these independent counterfactuals:

1. Each job's finish deadline +2 slots.
2. Each job's release boundary -2 slots.
3. Concurrency limit +1 if installed capacity permits.

No experiment changes job duration, power or any other job's window. If padding is unavailable, mark the experiment unavailable rather than invent data or shorten it silently.

Report:

- `objective_improvement_gbp_equivalent = objective_original - objective_relaxed`.
- `cash_saving_gbp = electricity_original - electricity_relaxed`.
- `carbon_saving_kg = carbon_original - carbon_relaxed`.
- The changed rule, resulting schedule, solve status and any business caveat.

At lambda zero objective improvement equals cash saving. At positive lambda, cash saving may be negative while the chosen objective improves. Rank on the selected objective and label that ranking; show cash and carbon separately. Values are one-at-a-time finite changes, not LP dual prices, exact marginal derivatives or additive totals.

When both solves are optimal, relaxing a rule cannot worsen the optimum of the same objective. Material violations indicate a bug or incorrect comparison. Treat absolute differences <=1e-6 GBP-equivalent as zero; never hide a larger negative by clamping it. If either solve is only feasible under a time limit, show a provisional comparison and do not call it a proven value. If the original problem is infeasible, show which changes restore feasibility and no finite savings claim.

Earlier release assumes the data/input could actually become ready earlier; it is a negotiation scenario, not permission to start with missing input. A relaxed deadline similarly requires business agreement.

## 5. Data contract and provenance

Use Python dataclasses in `scheduler/domain.py`, not ORM models, and an explicit schema version. Domain calculations import no Django components.

| Type | Required fields |
|---|---|
| `Slot` | `start_utc`, `end_utc` aware datetimes; `price_gbp_per_kwh`; `intensity_gco2_per_kwh` |
| `Snapshot` | `schema_version=1`, `snapshot_id`, `region_key`, tuple of Slots, `horizon_start_index=2`, `horizon_end_index=50`, provenance mapping, raw-file hashes |
| `Job` | `job_id`, `name`, `release_slot`, `deadline_slot`, `duration_slots`, `active_wall_kw` |
| `Scenario` | `snapshot_id`, jobs tuple, `installed_workers`, `concurrency_limit`, `idle_kw_per_worker`, `facility_multiplier` |
| `SolveRequest` | scenario, `objective_mode` in cost/carbon/weighted, `carbon_price_gbp_per_tonne`, `time_limit_seconds` |
| `Assignment` | `job_id`, `start_slot`, `end_slot`, `worker_index` assigned by interval partitioning after solving |
| `Metrics` | `energy_kwh`, `electricity_gbp`, `carbon_kg`, `objective_gbp_equivalent` |
| `SolveResult` | `request_digest` identifying inputs/mode/lambda/data, status optimal/feasible_limit/infeasible/no_solution/error, assignments, metrics or null, gap or null, elapsed seconds, warnings, `tie_break_complete` |
| `Comparison` | baseline result, cheapest result, cleanest result, selected result, scenario digest and snapshot metadata |
| `ConstraintValue` | experiment ID/type/job ID, changed boundary or concurrency, original and alternative result references, three deltas or null, status exact/provisional/unavailable/restores_feasibility/no_feasible_solution |

JSON mirrors these names; tuples become lists and UTC times use ISO strings ending in Z. An infeasible result has no fabricated assignments or zero metrics. All externally submitted fields are validated on the server, even when form widgets constrain the inputs. Job names are trimmed 1–80 characters; IDs are unique and 1–64 characters. Production job duration is 1–48 slots; finite lambda is 0–5,000 GBP/tCO2; operating nights is integer 1–365. Limit incoming scenario payloads to 32 KiB before parsing/solving. Small internal test fixtures need not use the production slot count.

Snapshot provenance contains provider, full request URLs, retrieved-at timestamp, interval coverage, product/tariff code, import/export direction, business/proxy label, tax basis, carbon field used, region mappings and raw hashes. Provider issue time is nullable; retrieval time must not be relabelled as forecast issue time.

Follow tariff pagination; sort responses by UTC; clip exact interval coverage; reject conflicting duplicates, gaps, overlaps, nonfinite data and unexpected slot lengths. NESO can return an extra boundary interval: our sampled response had 53 rows for a window in which Octopus had 52. Exact timestamp alignment is mandatory; zipping arrays by position is wrong.

Use a dedicated `capture_snapshot` management command. Fetch both sources into a new directory, validate and normalise, then publish the manifest atomically. A partial capture must not replace the last known-good snapshot. Live requests should use timeouts and bounded retries; demo requests must never fetch providers.

Historical regional responses contain a field named `forecast`; the field name alone does not establish what was known at an earlier decision time. Saved snapshots are replay data unless captured prospectively before scheduling. Do not replace missing regional forecasts with national actual values without creating and labelling a different dataset.

## 6. Application boundaries

```text
manage.py
config/                         Django settings and root URLs
scheduler/
  domain.py                     Shared dataclasses and units
  validation.py                 Numerical and scenario invariants
  data.py                       Provider access, normalisation, snapshot loading
  baseline.py                   Reproducible current-policy schedule
  metrics.py                    Independent energy/cost/carbon calculations
  optimizer.py                  Binary start formulation and solve decoding
  analysis.py                   Trade-offs, relaxations, break-even, annual scenario
  services.py                   Orchestration, budgets and cache keys
  forms.py, views.py, urls.py    HTTP boundary and user validation
  charts.py                     Plotly figure construction only
  templates/scheduler/          Dashboard and reusable partials
  static/scheduler/             CSS, JS and local Plotly asset
  management/commands/capture_snapshot.py
  tests/                        Domain, adapter, solver, HTTP and integration tests
data/snapshots/                  Validated application snapshots and raw data
data/examples/                  Explicitly illustrative job configurations
docs/flexvalue/                 This pack and build handoff
```

Pure engine modules accept domain objects and return domain objects; they do not access HTTP, global scenario state or the filesystem. `services.py` loads an immutable snapshot and supplies it to the engine. Charts consume computed results and never recompute financial totals in JavaScript.

Use one dashboard with GET `/`, POST `/analyse/`, POST `/constraints/`, POST `/tradeoffs/`, optional POST `/regions/`, and POST `/export/` for the posted scenario/results regenerated or loaded by verified digest. Server-rendered POST pages are sufficient first. Partial JSON responses for explicit fetch calls may be added after the vertical slice; preserve one service layer. POSTs include CSRF. Avoid an API framework unless the team already has a compelling need.

Exports contain inputs, snapshot IDs/hashes, assumptions, assignments, metrics and statuses. Do not write arbitrary paths supplied by the browser. No arbitrary provider URLs or pickle uploads. Only known snapshot IDs can resolve to files. Escape job names in templates and chart labels; render plot data through safe JSON encoding.

## 7. Interaction design

1. Data banner: “Historical replay”, dates/time zone, tariff/proxy status and estimated power.
2. Editable jobs: name, duration, release, deadline and active worker power. Show local date/time while storing indices.
3. Settings: installed workers, concurrency, idle draw, facility factor and carbon-price preference.
4. Analyse button: baseline/cheapest/selected metrics, all with the same completed workload.
5. Price and carbon small-multiple charts sharing the time axis; avoid a misleading unlabelled dual axis.
6. Gantt schedule: colour by job consistently, rows by worker and schedule. Plotly uses explicit offset-labelled local tick text; browser timezone must not change meaning.
7. Evaluated trade-offs: x=kg CO2, y=electricity GBP. Points are complete schedules; clicking displays the matching schedule. Do not interpolate to imply fractional jobs.
8. “Price my constraints”: show one-rule experiments with cash, carbon and weighted improvement columns. Let a user inspect an experiment before applying it as a new scenario.
9. Conditional annual scenario: selected saving times operating nights, with formula and assumptions visible. If an underlying saving is negative, retain the negative sign.
10. Sources/assumptions and JSON export.

Use an explicit recompute action after edits. Mark old results stale immediately, disable their export/apply actions and retain the submitted input on errors. If asynchronous fetch is added, a response must match the latest request ID and scenario digest before updating the screen.

## 8. Performance and failure policy

Recommended caps: 8 jobs, 8 installed workers, 52 slots, one second per solve including endpoint tie-break, 15 seconds per analysis request and 15 seconds per constraint batch. These are safety limits, not measured performance claims; profile on the team's machine. Check the remaining batch budget before each solve and mark unrun experiments unavailable. Do not wait for all slots of a worst-case batch after the deadline.

Cache complete successful results by canonical JSON digest including schema/engine version, snapshot raw hashes, ordered jobs, all hardware settings, objective mode, lambda, requested experiment and numerical policy. Changing any relevant input invalidates the result. Do not indefinitely cache timeouts as optima. Cache directory/file structure is not a second database.

SciPy status 0 means optimum within solver tolerances; status 1 can have a valid incumbent or no incumbent. Decode only a present, finite incumbent; independently validate it before presenting `feasible_limit`. Preserve gap when supplied. Status 2 is infeasible; status 3 is a modelling error here because all assignment variables are bounded; status 4 is a solver error. Never turn any failure into a fabricated green result.

If baseline first-fit misses a deadline but the optimiser succeeds, show “baseline policy misses a deadline” and suppress baseline savings. Continue comparing feasible optimised alternatives. Do not silently drop the late job.

## 9. Illustrative starting workload

Use the saved replay's local horizon 1 October 2026 16:00 BST to 2 October 16:00 BST. The table uses local clock times; convert from explicit offsets, not today's date. Dataset padding covers 15:00 before and 17:00 after.

| Job | Ready | Finish by | Duration | Average active wall kW |
|---|---|---|---|---|
| Training A | Day 1 16:00 | Day 1 22:00 | 2 hours | 1.40 |
| Evaluation | Day 1 17:00 | Day 1 23:00 | 1 hour | 0.80 |
| Batch inference | Day 1 18:00 | Day 2 04:00 | 3 hours | 1.20 |
| Embeddings | Day 1 20:00 | Day 2 06:00 | 2 hours | 1.00 |
| Training B | Day 1 22:00 | Day 2 10:00 | 4 hours | 1.60 |
| Regression suite | Day 2 06:00 | Day 2 12:00 | 1 hour | 0.70 |

These are plausible-format illustrative inputs, not measurements or a promise of a particular saving. Validate baseline feasibility and observe actual results before deciding the final demonstration sequence. Include a separate tight-window fixture to exercise infeasibility and zero flexibility, rather than secretly changing real observations.

## 10. Deferred features and revisit triggers

Defer actual execution, authentication, multi-tenant persistence, cloud integrations, job preemption, heterogeneous GPUs, job dependency DAGs, renewable procurement accounting, hardware manufacturing emissions, batteries, demand charges, forecast training and probabilistic duration. Revisit only when the MVP is complete or the customer requirement changes.

Add regional comparison only when all core acceptance checks pass by hour 5. Use verified tariff `_C`/NESO 13 for the London example and `_N`/NESO 2 for the Edinburgh/South Scotland example. Re-resolve mappings for different sites. Show each site's own tariff and carbon series. A switch in carbon region alone is a controlled carbon-only experiment, which must be labelled as such.

The same absolute forecast level says little about flexibility value: variation over a feasible job window and competition for workers determine the value. Do not promise that Scotland always has lower or less valuable flexibility. A one-night replay cannot justify buying or relocating hardware.
