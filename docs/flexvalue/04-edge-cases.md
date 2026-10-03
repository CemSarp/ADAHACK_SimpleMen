# FlexValue edge cases and acceptance checks

This is a required behaviour checklist, not a demand for a separate test for every cosmetic detail. Prioritise independent numerical oracles, feasibility, time alignment and truthful result states. Unit and integration tests run offline by default. Provider smoke checks are explicit and separately reported.

## Hand-calculated oracles

### E01 — cost, carbon and switching

Use four consecutive half-hour slots, one installed worker, idle 0, facility multiplier 1, concurrency 1, and one 1 kW job lasting two slots with release 0 and deadline 4. This tiny engine test has no padding; production data uses the normal padded policy.

| Slot | Price p/kWh | Carbon gCO2/kWh |
|---|---:|---:|
| 0 | 40 | 50 |
| 1 | 10 | 300 |
| 2 | 20 | 100 |
| 3 | 30 | 200 |

| Start | Occupied slots | Energy kWh | Cost GBP | Carbon kg |
|---|---|---:|---:|---:|
| 0 | 0,1 | 1 | 0.25 | 0.175 |
| 1 | 1,2 | 1 | 0.15 | 0.200 |
| 2 | 2,3 | 1 | 0.25 | 0.150 |

Required results: cheapest starts at 1, cleanest starts at 2, start 0 is dominated by start 2, and the pairwise cost/carbon break-even between starts 1 and 2 is £2,000/tCO2. At that exact weight both are optimal; do not require one specific tied assignment. At £1,000/t, start 1 has score £0.35 versus start 2 £0.40. At £3,000/t, start 2 has score £0.70 versus start 1 £0.75. Compare unrounded values with tolerances.

### E02 — an objective improvement is not necessarily a cash saving

Use E01 but set original deadline to 3, and lambda to £3,000/t. The original optimum starts at 1: cost £0.15, carbon 0.20 kg, score £0.75. A test-specific deadline relaxation to boundary 4 allows start 2: £0.25, 0.15 kg, score £0.70.

Required deltas: cash saving **-£0.10**, carbon saving **+0.05 kg**, objective improvement **+£0.05-equivalent**. This oracle uses a one-slot relaxation to fit a tiny grid; production experiments use two slots (one hour). The analysis helper may take an internal test-only delta parameter, or the test can compare constructed scenarios without changing production defaults.

### E03 — fixed idle and facility overhead

For two half-hour slots, two installed workers, concurrency 1, idle 0.1 kW per worker, facility multiplier 1.2, and one job drawing 1.1 kW for both slots:

Power before facility multiplier = `2*0.1 + (1.1-0.1) = 1.2 kW`.
Total energy = `1 hour * 1.2 * 1.2 = 1.44 kWh`.
At constant £0.20/kWh and 100 gCO2/kWh: £0.288 and 0.144 kg.

Changing only allowed concurrency to 2 does not change installed idle energy. Increasing installed workers is a different model input and must change fixed idle accordingly.

### E04 — the baseline can fail while a valid schedule exists

One worker; four slots; job A is first in input order, release 0, duration 3, deadline 4; job B release 0, duration 1, deadline 1. The baseline first schedules A and cannot place B. The optimiser can run B at 0 and A at 1. Require both facts to be represented without deleting B or declaring the overall problem infeasible.

## Data and timestamp cases

| Case | Required behaviour | Owner |
|---|---|---|
| Pence mistaken for pounds | Convert once at the adapter boundary; oracle catches 100x errors | A |
| Grams, kg and tonnes | Label units in field names; weighted objective divides kg by 1000 | A/B |
| API returns descending records | Sort by parsed UTC times; never assume order | A |
| Carbon has extra leading boundary interval | Clip by full interval coverage before exact join | A |
| Missing price or forecast | Mark capture invalid or requested experiment unavailable; no zeros/interpolation | A |
| `forecast=0` | Preserve valid zero; do not treat it as false/missing | A |
| `forecast=null`, negative intensity, NaN/Inf | Reject as unusable data for this model | A |
| Negative electricity price | Keep it; jobs still run exactly once at fixed duration | A/B |
| Duplicate identical intervals | Deduplicate only if values agree; retain evidence/count warning | A |
| Conflicting duplicate/overlapping intervals | Reject; do not arbitrarily take the latest row | A |
| Pagination | Follow bounded `next` links on the allowlisted provider host; verify coverage afterward | A |
| Partial snapshot update | Write new capture; never replace last valid snapshot until validation completes | A |
| Unpublished next-day prices | Explain the available horizon and use a labelled complete replay if needed | A/D |
| Provider schema changes | Fail with an actionable parser error; no guessed field substitution | A |
| Product closed to new customers but historical rates exist | Distinguish availability from historical data; valid dated replay remains usable with labels | A |
| Export product matches “Agile” | Reject for import scheduling; validate direction and metadata | A |
| Domestic tariff in business example | Persistent proxy label; do not claim business eligibility | A/C |
| BST clock jump forward | Construct UTC slots; display actual local times; no nonexistent wall-time acceptance | A/D |
| BST clock repeated hour | Use UTC index or explicit offset to disambiguate; date/time text alone is insufficient | A/C/D |
| Local calendar day vs 24 elapsed hours | Do not force 48 slots onto a 23/25-hour day; app uses a labelled 24-hour window | A/D |
| User enters non-grid time | Reject with nearest valid half-hour choices; do not silently round | D |
| Region rate/carbon coverage differs | Mark regional comparison unavailable; compare only identical intervals | A/D |
| Old replay shown today | Display actual data dates prominently, not today's date as the data date | C/D |
| Historical “forecast” field | No as-of backtest or realised-saving claim without contemporaneous capture evidence | A/C |
| Raw file altered after capture | Hash validation fails; do not silently refresh the hash to legitimise changed data | A/D |

## Job, hardware and feasibility cases

| Case | Required behaviour | Owner |
|---|---|---|
| Zero jobs or >8 | Form validation error; no optimisation | D |
| Duplicate job IDs | Reject; names may duplicate but IDs must remain distinct | D |
| Empty/very long name | Require trimmed 1–80 characters; escape everywhere | D/C |
| Boolean supplied as integer | Reject for slots, counts and duration | D |
| Zero/negative/fractional slot duration | Reject; production durations are integral half-hours | D |
| Deadline before release or shorter than duration | Actionable job-specific error before solver | D |
| End exactly at deadline | Accept because finish boundary is exclusive | B |
| Adjacent jobs on one worker | Accept; no overlap at the common boundary | B |
| Multiple jobs collide | Solver enforces concurrency; evaluator catches malformed output | B/A |
| Active draw below idle draw | Reject because dynamic energy would become negative | D/A |
| Active draw equals idle | Allow; dynamic job increment zero, metrics still include installed idle | D/A |
| Rated GPU draw entered as if measured wall draw | UI requests the estimate basis; label estimate, no automatic TDP-to-measurement claim | C |
| Facility-inclusive power and PUE applied twice | Explain multiplier=1 in that case; no hidden second cooling factor | C/A |
| Concurrency 0 or greater than installed | Reject | D |
| Capacity+1 beyond installed | Explicit unavailable row; no free hardware purchase | B/C |
| Same installed workers, higher concurrency | Fixed idle stays identical; work energy stays identical | A/B |
| Power would exceed building electrical limit | Outside MVP; document no electrical-safety/execution guarantee; do not claim deployment-ready schedules | C/D |
| Dependencies between jobs | Outside model; do not accept hidden DAG semantics. Users must supply independently ready jobs | C/D |
| Earlier release is a hard data dependency | Mark hypothetical, requiring earlier readiness; never auto-execute | B/C |
| Impossible aggregate workload | Infeasible result, no cost-saving metric fabricated | B/D |
| Baseline misses a deadline but solver succeeds | Baseline invalid banner, suppress baseline savings; show feasible optimised options | B/C |
| All windows fixed | Same schedule; constraint values may still identify useful extensions, or show zero | B |
| No possible earlier/later data | Unavailable experiment; do not shorten one hour silently | B |
| Apply experiment uses padding | Preserve explicit changed boundaries and show extended-window banner. New scenario may use [0,52); further out-of-data relaxations are unavailable | B/C/D |

## Optimisation and result integrity cases

| Case | Required behaviour | Owner |
|---|---|---|
| Tied objective | Valid equal optima accepted; deterministic input order; endpoint tie-break if budget allows | B |
| Flat rates | No scheduling cash saving at unchanged energy; carbon can still differ | B |
| Flat carbon | Carbon timing gain zero; choose on cash where possible | B |
| Cheapest also cleanest | Show a joint win/single trade-off option, not an invented conflict | B/C |
| Zero-carbon denominator | No infinite/nonsensical threshold; return a reason | B |
| Negative price totals | Show credit/negative energy charge; percentage savings may be undefined or misleading | B/C |
| Zero or negative comparison cost | Show absolute savings; percent saving N/A unless denominator is strictly positive | B/C |
| Weighted value positive, cash saving negative | Keep both signs and label £-equivalent versus cash | B/C |
| Relaxed exact optimum worse | Flag modelling/comparison error above tolerance | B |
| Independent values overlap | No summed opportunity total; joint relaxation requires a new solve | B/C |
| Original infeasible | Show restores-feasibility instead of finite original-optimum deltas | B |
| One-hour relaxation restores feasibility | No business penalty/value invented for the formerly infeasible plan | B/C |
| Only feasible incumbent at time limit | Validate then mark provisional; retain solver gap | B/D |
| No incumbent at time limit | No solution available; no zero metrics | B/D |
| Integral variables slightly noisy | Decode only within tolerance (1e-6); validate constraints and objective independently | B/A |
| Missing/duplicated decoded assignment | Reject solver output; never fill jobs arbitrarily | B/A |
| Unbounded/error status | Treat as model/solver failure; binary bounded formulation should not be unbounded | B |
| Per-solve/batch budget exhausted | Stop further work and mark unavailable rows; reuse validated cached optima where appropriate | B/D |
| Weighted sweep misses a nondominated schedule | Label evaluated trade-offs; no “complete frontier” claim | B/C |
| Pairwise threshold beaten by third schedule | Keep pairwise label or verify globally around threshold | B/C |
| Lambda changed | Recompute exact objective; don't use nearest preset as though exact | B/D |
| Different job allocation gives same totals | Deduplicate carefully while preserving a concrete inspectable schedule | B/C |
| Comparing regions | Both original and alternative results belong to the same site for each value calculation | B/D |

## UI, reliability and interpretation cases

| Case | Required behaviour | Owner |
|---|---|---|
| User edits during request | Old response cannot become current; validate request ID/digest | C/D |
| Snapshot/lambda/power changes | Invalidate affected cache/result identity | D |
| Two browser tabs | No mutable global scenario; each request contains its own inputs | D |
| Server restarts | Reload saved snapshot; cache loss changes speed, not correctness | D |
| Offline presentation | Local Plotly/CSS plus saved data; no critical CDN or API request | C/D |
| Job name contains HTML/script | Escape in template and safe chart serialisation; no execution | C/D |
| Unknown snapshot/path traversal | Reject allowlist lookup; no arbitrary filesystem access | D |
| Huge payload or out-of-range values | Reject before calling solver | D |
| Missing CSRF or bad POST | Conventional Django handling; no disabling CSRF for convenience | D |
| Stale export | Recompute or reject; include digest/provenance/status | D |
| Currency rounded differently across plots | Round only at presentation with consistent formatting | C |
| Solver warnings hidden behind chart | Status visible on results and export | C |
| Annual multiplier 0, negative, fractional or >365 | Reject; supported range integer 1–365 | B/D |
| £4 repeated for 365 nights | £1,460; explicitly conditional, not predicted | B/C |
| 5 kg repeated for 250 nights | 1,250 kg = 1.25 tonnes; no confusion with money | B/C |
| Negative nightly saving | Preserve negative annual result | B/C |
| Energy reduction claim | Scheduling same workload generally shifts timing, not total job energy under this model | C/all |
| CO2 vs CO2e | NESO-based output labelled estimated electricity CO2, not full lifecycle CO2e | C/all |
| Average vs marginal grid intensity | No claim of causally avoided grid emissions from this model alone | C/all |
| Profit claim | Conditional on unchanged completed output, revenue and other costs | C/all |
| Different-region result | Hypothetical site comparison; no migration, latency, hardware capex or relocation conclusion | C/all |

## Minimal release evidence

Record in BUILD_STATUS: environment versions; tests actually run; cold-start command; offline browser result; example snapshot hashes; example job configuration; verified schedules and totals; measured solve/batch latency; all remaining limitations. Passing unit tests alone does not verify the visible demo. A polished visible demo alone does not verify the maths.
