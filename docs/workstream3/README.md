# Workstream 3: what to do now

Prepared on 2026-10-03 against `main` at `63dc29b`, after a successful fast-forward pull from `origin/main`. This is a planning handoff, not an implementation or a completed C0/P1 release.

The current authority is `carbonopt-ai-docs/`, particularly its central plan, shared contracts, canonical schemas, action model, risk/benchmark specification, tests/mocks guide, integration guide, and decision register. The root README's old Django references were stale. The current plan specifies **Python 3.11 + Streamlit + Plotly**.

“Everything decided” below means decisions visible in this conversation and in those repository documents. The original conversation referenced by the documentation was not supplied here. Proposed implementation choices are marked **proposed**; they must not be described as previously agreed team decisions.

## Read and use this pack

1. Read this guide for scope, order, dependencies, and acceptance gates.
2. Review [architectural decisions](ARCHITECTURAL_DECISIONS.md), especially the unresolved C0 boundary questions.
3. Use the [implementation plan](../superpowers/plans/2026-10-03-workstream3-risk-benchmark.md) as a task checklist.
4. Paste the bootstrap and then one numbered prompt at a time from [the coding-agent prompt pack](AGENT_PROMPTS.md).
5. Use [the edge-case matrix](EDGE_CASES.md) for tests and final review.

## Your responsibility

You own two independent P1 services:

- **Risk:** evaluate uncertainty in action effectiveness and implementation costs by repeatedly calling WS2's canonical deterministic simulator. Publish reproducible empirical summaries and constraint probabilities.
- **Benchmarking:** ingest a CSV or HTTP source, normalize and filter compatible annual peers, and publish a transparent intensity comparison or an explicit unavailable result.

You also support P0 by reviewing contracts, simulator uncertainty hooks, no-op/accounting parity, and offline fixtures. P0 must ship without your optional services if necessary.

| You own | Another workstream owns | Your boundary work |
|---|---|---|
| `src/risk/monte_carlo.py`, optional small risk helpers | WS2: `src/actions/`, optimizer, constraints, recommendation policy | Confirm effectiveness/cost hooks; publish risk joined by original strategy ID |
| `src/benchmarking/adapters.py`, `normalize.py`, `benchmark.py` | WS1: data generation, forecast, backtest, SHAP | Consume complete baseline; never load models or train on peers |
| `config/uncertainty.json`, peer snapshot and source metadata | WS4: Streamlit, provider wiring, caches, credentials, scenario comparison | Supply needs, capability behavior, typed results, sample outputs |
| WS3 unit tests and domain handoff fixtures | WS4 stewards shared types, serializers, dependency files, CI, shared tests | Propose small coordinated contract edits; avoid a private competing schema |

Public signatures are fixed in [SHARED_CONTRACTS.md](../../carbonopt-ai-docs/docs/SHARED_CONTRACTS.md). Source/config/test paths refer to the **application repository root**. This checkout currently has the documentation under `carbonopt-ai-docs/`; it has no application skeleton. Do not create application code inside that documentation folder or blindly copy/delete its contents. WS4 needs to settle the root layout and documentation links during C0.

## Current state and real blockers

Verified in this checkout:

- The pull moved `main` from `bd10ce7` to `63dc29b`. The working tree was clean before planning edits.
- There is no `src/`, `app.py`, `pyproject.toml`, `requirements*.txt`, or application test suite yet. `__init__/__init__.py` is empty and does not provide the planned `src` package.
- `environment.yml` specifies Python 3.11 and NumPy/Pandas/SciPy/Plotly/requests, among others. It does not include pytest, Streamlit, LightGBM, pymoo, or SHAP. C0 must establish a reproducible team dependency manifest; do not claim bootstrap/test commands already run.
- The fetched `origin/workstream2` tree also contains documentation rather than the promised action-engine implementation. Its existence is not evidence that the simulator is ready.
- All 11 delivered example JSON files parse. The 12-month baseline sums to 1,200 tCO₂e, GBP 12,000,000 revenue, GBP 1,200,000 operating profit.
- The nonzero simulation's stable ID matches the documented SHA-256 identity. Its monthly totals reconcile within floating-point tolerance. Its golden metrics are 843.744 tCO₂e, GBP 1,210,940.7847619047 profit, GBP 164,000 capex, GBP 186,581.12 gross outlay.
- Peer fixture intensity is 100 tCO₂e/million GBP; median 105; midpoint percentile 45; better-than 55%. These were independently recomputed.
- No uncertainty JSON, zero-uncertainty fixture, risk-sensitive test double, unavailable benchmark fixture, or multi-strategy risk selection fixture has been implemented.
- `risk_summary.json` is a labelled illustrative shape, not an output generated from a supplied sampling specification.
- Synthetic fixture dates extend beyond the preparation date: history through December 2026 and forecast in 2027. Peer reporting ends December 2026 despite an October retrieval timestamp. Preserve synthetic demonstration labels; do not infer that these are completed reported observations.

The critical dependency is C0: importable shared types/validators/serializers plus an agreed simulator callable. You can work on test cases, proposed uncertainty schema, peer mappings and planning before C0, then develop against a test-only behavioral simulator. Do not independently implement a replacement production action engine.

## First session: concrete steps

1. **Use your selected WS3 branch when implementing.** The latest observed branch is `workspace3`; this planning turn did not create it. Preserve it unless you request a switch. For new branches use the repository's agreed `feat/ws3-risk` / `feat/ws3-benchmark` convention; if no team convention has been adopted, the Codex default is `codex/ws3-risk` / `codex/ws3-benchmark`. Check status first; never reset someone else's work. This planning turn has not committed changes.
2. **Read the contracts in dependency order:** `IMPLEMENTATION_PLAN.md`, `SHARED_CONTRACTS.md`, `DATA_SCHEMAS.md`, `ACTION_MODEL.md`, `RISK_AND_BENCHMARK_SPEC.md`, `TESTING_AND_MOCKS.md`, `INTEGRATION_GUIDE.md`, `DECISIONS.md`, then WS3's role file and examples.
3. **Prepare the C0 boundary note.** Resolve the exact uncertainty type/JSON; cost sampling scope; zero-uncertainty semantics; risk raw-boundary rules; result provenance; benchmark config/source/dataset types; same-company identity; loader failure handling. Use decision IDs A01–A24.
4. **Have WS2 confirm the simulator inputs.** It accepts sampled copies of `ActionAssumptions`, including renewable/EV/travel effectiveness, nested per-action costs, supplier reduction and savings. All-zero actions remain exact no-op even with sampled assumptions.
5. **Have WS4 confirm integration needs.** The root package/layout, serializers, optional provider flags, failure conversion, credential wiring, cache inputs, fixture paths, and dependency ownership must match C0.
6. **Once C0 exists, run the shared contract suite.** Load baseline, assumptions, action config, constraints and simulation fixtures through shared serializers. Establish a risk-sensitive affine test double in `tests/mocks/`; it must respond to sampled effectiveness and capex.
7. **Implement seeded sampling before summaries.** Prove bounds, immutability, reproducibility, degenerate parity and common trial alignment. Only then add the Monte Carlo runner.

You do not need a live API, trained model, completed optimizer, web server, database, or chatbot to start WS3.

## Build in this order

| Order | Deliverable | Dependencies | Exit evidence |
|---:|---|---|---|
| 0 | Contract readiness and documented decisions | WS2 + WS4 C0 | Types import, examples round-trip, ownership clear |
| 1 | Behavioral simulator double and exact test cases | C0 types/serialization | Valid outputs respond to both config and sampled assumptions |
| 2 | Uncertainty validation + seeded trial matrix | Agreed uncertainty schema | All channels bounded; same seed/hash reproduces; no global RNG mutation |
| 3 | Sampled assumption copies + Monte Carlo | Injected simulator | Exact call count, original strategy ID, no-op/zero-uncertainty parity |
| 4 | Empirical summaries + probabilities | Valid trial outcomes | Hand-authored samples match quantiles/flags/MCSE; strict boundary tests |
| 5 | Real simulator integration | WS2 C2 | Golden deterministic parity, no alternate accounting, runtime measured |
| 6 | Risk-pool handoff + C5a | WS2 C3, WS4 wiring | ≤20 deterministic feasible frontier plans, common trials, real recommendations |
| 7 | Offline benchmark normalization + comparison | Baseline + compatible synthetic fixture | Intensity 100, median 105, percentile 45, count 10 |
| 8 | Real source qualification | Verifiable provider fields and licence | Source mapping, scope/method/period/FX provenance, enough peers |
| 9 | CSV/HTTP adapter and failure handling | Agreed source/failure types | Bounded mocked transport, snapshot/offline behavior, no secrets/network at import |
| 10 | Benchmark integration + C5c | C5a then WS1 C5b acceptance | Valid/unavailable outputs, optional failure isolation, consumer review |
| 11 | Final handoffs and demo freeze | Accepted components | Offline commands, dependency/config revisions, limitations and saved results |

Offline benchmark preparation can happen before real risk integration. Production acceptance follows **Risk → SHAP → Benchmark → Scenario Compare**; SHAP and scenario comparison remain other owners' work.

## Risk: exact requirements

Keep the forecast baseline and action config fixed. Sample illustrative independent bounded uniforms: action effectiveness [0.85, 1.0], per-action capex/fixed-opex coefficients [0.9, 1.1]. These are assumption ranges, not calibrated confidence limits.

Canonical action order: `renewable_energy`, `ev_adoption`, `building_efficiency`, `travel_reduction`, `cloud_efficiency`, `supplier_transition`.

- Renewable/EV/travel sampled effectiveness replaces their deterministic default 1.0 fields.
- Building/cloud sampled effectiveness multiplies their deterministic maximum reduction.
- Supplier sampled effectiveness multiplies **both** maximum reduction and monthly savings at full implementation.
- Sample capex and fixed monthly opex separately for each action. Fixed costs remain tied to implementation fraction even when effectiveness is poor. Tariffs, grid factors and avoided-cost rates remain fixed under the proposed initial scope; see A03.
- Create new immutable assumption IDs for trials, derived from parent/uncertainty identities, seed and trial index. The top-level risk strategy ID must identify the original deterministic strategy.
- Use `numpy.random.default_rng(seed)` and pre-generate identical trial matrices for all compared strategies. Never seed by strategy ID or consume randomness conditionally on nonzero actions.
- Default 1,000 trials; positive integer count, proposed maximum 5,000. Boolean counts are invalid. Detailed 5,000-trial reports are explicitly triggered; retain samples only when requested.
- Call the injected canonical simulator once per trial. Obtain CO₂/profit/cost from its metrics. Do not recalculate depreciation, cash flow, action effects, scope interactions or savings in risk code.
- Report all 13 documented summary fields, empirical p05/p95, p95 cost, individual and joint success probabilities, and target-probability MCSE `sqrt(p*(1-p)/n)`.
- Empirical p05–p95 is a 90% trial outcome interval, not a confidence interval for the mean. The mean need not fall between p05 and p95.
- No-op matches baseline in every trial. Neutral multipliers (effectiveness 1, costs 1), rather than literal zero effectiveness, must match deterministic simulation.
- Zero baseline CO₂ + positive ratio target is invalid. For zero baseline + zero target, proposed target flag is true and reduction ratio remains null. Zero baseline profit permits a null relative change while profit-floor evaluation remains valid.

WS2 selects recommendations; WS3 supplies summaries. Conservative prefers joint probability ≥0.90 and ranks normalized CO₂ p95 / negative profit p05 equally. Balanced prefers ≥0.75 and ranks means equally. Aggressive ranks all evaluated plans with weights 0.75 CO₂ / 0.25 negative profit. WS2's existing contract governs ties, threshold shortfalls and deterministic fallback. WS3 must provide data that makes those policies testable.

## Benchmark: exact requirements

Use only a complete 12-month baseline initially. Compute `baseline_total_co2e / (baseline_revenue_gbp / 1_000_000)`. Never use operating profit as the revenue denominator or divide a 36/60-month total by one year's peer revenue.

The initial config requires canonical industry, `scope1_scope2_scope3`, the same scope2 method, `min_peers=10`, `max_period_end_gap_months=24`, and `comparison_basis="forecast_vs_historical_peers"`.

1. Normalize reported annual rows to GBP and tonnes with disclosed mapping and FX provenance.
2. Validate annual period, finite positive revenue, finite nonnegative CO₂, required scope/method, unique IDs and intensity reconciliation.
3. Exclude incompatible industries/periods/scopes/methods; never replace missing scopes with zero.
4. Keep synthetic and reported comparisons separate. Preserve exclusion reasons/counts and source lineage.
5. Exclude target company and avoid overweighting one peer through multiple annual records; establish an entity-identity mapping first.
6. If fewer than 10 compatible peers remain, return unavailable with a reason and actual count.
7. For target intensity `c`, use midpoint rank: `100*(count(peer<c)+0.5*count(ties))/N`; `better_than_pct=100-percentile`; lower is better. Ties must not be double-counted as lower; A11 defines the proposed tolerance.
8. Label the baseline forecast period separately from peer reporting periods. A synthetic convenience sample does not represent an entire global industry.

No source has been selected or verified. Timebox provider qualification; publish clearly labelled synthetic demonstration or unavailable external capability if a legitimate compatible source is not available. The demo's `market_based_demo` method may prevent direct use of reported peers. Changing its accounting basis requires WS1/WS2/WS3/WS4 coordination, not relabelling external rows.

HTTP is optional and explicit. Use finite connect/read timeouts, at most two retries after the initial attempt, bounded delays, validated responses, injected transport tests and environment-based credentials. Offline must never issue a request. Network failure can use only an approved compatible snapshot, visibly marked cache with retrieval age; otherwise the benchmark is unavailable. P0 remains usable.

## Handoffs to prepare

**WS2:** original strategy IDs, baseline/assumption/uncertainty identities and hashes, two real risk results, common-trial policy, actual constraints, sample counts/seeds, hand-authored selection fixtures, strict raw-boundary behavior, runtime and limitations. Coordinate recommendation policy; do not rewrite the optimizer.

**WS4:** exact public signatures, versioned valid/unavailable payloads, capabilities and typed failure mapping, dependency groups, credential variable names without values, complete cache-key inputs, benchmark source kind/age/periods/count/units, and UI copy for conditional probabilities and synthetic peers.

**WS1:** baseline scope/method/date/revenue compatibility questions. Forecast uncertainty and calibration are excluded from initial WS3 risk; ask for a separate future proposal if needed.

Handoff evidence includes contract/fixture revisions, exact repository-root commands, dependency versions, seed/trials, assumption IDs, input/config hashes, test output, runtime machine/profile and known limitations. Request consumer review through a PR or review note; do not send external messages without explicit authorization.

## Working with an iterative coding agent

Use [AGENT_PROMPTS.md](AGENT_PROMPTS.md) bootstrap once per session, then exactly one task prompt. Each task states files, preconditions, behavior, tests and a stopping point. If you switch agents or lose context, paste the bootstrap plus the latest handoff and decision log again.

After each task, require: changed files; implemented public behavior; actual commands/results; unresolved decisions; limitations; next dependency. Review those before the next prompt. Update decisions when the team resolves them; do not let later prompts silently promote a proposed default to a frozen contract.

For a short hackathon, finish the risk sampling/runner/parity path first. Then ship offline benchmark logic; attempt a real provider only within a bounded qualification timebox. Cut live HTTP, sample retention, correlations and extra analysis before weakening deterministic parity, units, provenance or failure isolation.

## Definition of done

- [ ] C0 contracts and reviewed uncertainty/benchmark policies are in place.
- [ ] Same public risk interface works against both the behavioral test double and real simulator.
- [ ] Neutral uncertainty and no-op identities pass; original inputs remain unchanged.
- [ ] Hand-authored sample tests prove quantiles, raw flags, individual/joint probabilities and MCSE.
- [ ] Compared plans use common random numbers; recommendation IDs join exactly.
- [ ] Real-simulator runtime is recorded for 1,000 trials; 5,000 only enabled after measurement.
- [ ] Benchmark filtering, units, FX, ties, identity exclusion and small-peer failures pass.
- [ ] CSV/offline behavior is available; HTTP, if enabled, is bounded and tested without credentials/network.
- [ ] Synthetic/reported/cached provenance and forecast-vs-peer periods are visible.
- [ ] Missing optional providers do not break P0; unexpected programming errors are not disguised as business results.
- [ ] WS2 and WS4 have reviewed the boundary and received reproducible handoffs.
- [ ] The applicable shared/offline regression suites pass; no implementation is claimed from this planning-only turn.
