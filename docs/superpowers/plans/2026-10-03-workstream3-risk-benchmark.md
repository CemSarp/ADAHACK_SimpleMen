# Workstream 3 Risk and Benchmark Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` where available, or the iterative task workflow in `docs/workstream3/AGENT_PROMPTS.md`, to implement this plan one task at a time. User authorization for implementation is separate from this planning handoff. Do not dispatch parallel agents unless explicitly authorized or required by an applicable execution skill.

**Goal:** Deliver reproducible action-uncertainty risk and compatible annual-peer benchmarking behind the project's fixed Python interfaces, without blocking P0.

**Architecture:** Risk samples copied `ActionAssumptions` and calls an injected canonical simulator; it never implements action accounting. Benchmark adapters normalize source rows into shared peer datasets, then a pure comparison function filters/ranks peers. WS4 wires optional services and failures; WS2 owns risk-aware recommendation.

**Tech Stack:** Python 3.11, NumPy, Pandas, requests when HTTP is enabled, pytest; exact pins coordinated through WS4. No initial SciPy requirement, web server, database or UI dependency in domain modules.

**Spec:** `carbonopt-ai-docs/docs/SHARED_CONTRACTS.md`, `DATA_SCHEMAS.md`, `ACTION_MODEL.md`, `RISK_AND_BENCHMARK_SPEC.md`, `TESTING_AND_MOCKS.md`, `INTEGRATION_GUIDE.md`, `DECISIONS.md`, and `docs/workstream3/ARCHITECTURAL_DECISIONS.md` for explicitly proposed details.

## Global constraints

- Contract version `1.0.0`; public signatures are copied exactly from the shared contracts.
- Python 3.11 reference runtime; P0 supports only 12-month forecast baselines.
- All six actions are fractions in [0,1], in the canonical ActionConfig order.
- Emissions in tonnes CO₂e; currency GBP; no implicit percentage/unit conversion.
- No input mutation, UI/global RNG access, import-time network, or model/optimizer-internal imports.
- The deterministic simulator is the only production action/emissions/cost engine.
- Initial risk uses illustrative independent bounded uniforms, effectiveness [0.85,1.0], capex/fixed-opex [0.9,1.1]; fixed baseline and config.
- Default 1,000 trials; application limit proposed 5,000; retained samples disabled by default.
- Every serialized result has schema/run/provenance; trial sample identities differ from original deterministic strategy identity.
- Benchmark min peers 10, scope coverage `scope1_scope2_scope3`, same scope2 method, max period-end gap 24 months, forecast-vs-historical label.
- Initial P0/P1 order remains unchanged: Data → Forecast → Backtest → Action Engine → What-if → Optimizer → Pareto → Dashboard → Risk → SHAP → Benchmark → Scenario Compare → LLM Explanation → Chatbot.
- Shared-contract edits require producer/consumer review, matching validators/serializers/fixtures and documented version treatment.
- Synthetic/mock/conditional/cached provenance stays visible; no real-source claim without evidence.

## Review focus

- Neutral multipliers, zero baselines and exact constraint equality: deterministic parity and defined zero-ratio behavior; Tasks 2–4/6 test them.
- Strategy-order-dependent randomness or parent mutation: common random numbers and immutable copied assumptions; Tasks 2–3 test them.
- One failed/nonfinite trial: no silent dropping, bias or apparently valid summary; Tasks 3–4/6 test it.
- Duplicate entities, partial fiscal years and incompatible scope2 methods: honest peer counts and unavailable outputs; Tasks 7–8 test them.
- Network/snapshot failure with stale or synthetic fallback: provenance-preserving optional failure without P0 regression; Tasks 9–11 test it.

## File structure and ownership

| Path | Responsibility / status |
|---|---|
| `src/contracts/{types,protocols,validation,serialization}.py` | C0 shared prerequisite, WS4 steward; approve additions rather than duplicate types |
| `src/risk/monte_carlo.py` | Fixed public risk API, simulator calls, result assembly |
| `src/risk/sampling.py` | Proposed small internal helper for matrix generation and assumption copying; add only if needed for clarity |
| `src/risk/statistics.py` | Proposed small internal helper for strict flags and summary; can remain in monte_carlo if concise |
| `config/uncertainty.json` | Accepted illustrative policy with ID/version/provenance |
| `tests/mocks/risk_simulator.py` | Test-only affine simulator; never production-bound |
| `tests/unit/test_risk.py` | Sampling, mapping, runner, independent statistical oracles |
| `src/benchmarking/normalize.py` | Source mapping, unit/FX/date/identity validation and exclusion diagnostics |
| `src/benchmarking/benchmark.py` | Fixed pure baseline-comparison API |
| `src/benchmarking/adapters.py` | Explicit CSV/HTTP/snapshot loading; internal injected transport |
| `tests/unit/test_benchmark.py` | Pure normalization/comparison numeric and compatibility tests |
| `tests/unit/test_benchmark_adapters.py` | Mocked loader/network/snapshot tests |
| `tests/fixtures/v1/` | Reviewed copied shape fixtures, neutral risk, actual real risk, unavailable benchmark and selection examples |
| `data/benchmark.csv`, source-specific JSON metadata | Versioned normalized offline peer snapshot and licence/FX/source lineage |
| `tests/integration/test_risk_simulator.py` | Proposed WS3 real boundary tests; coordinate shared pipeline tests with WS4 |
| `docs/workstream3/handoffs/` | Proposed boundary notes, measured evidence, relative commands and known limitations |

Application paths are Git-root targets after C0; do not place runtime code under `carbonopt-ai-docs/`. No application or test modules exist at the audited commit.

## Task 0: establish reviewed C0 readiness

**Files:** Read authoritative specs; create `docs/workstream3/handoffs/c0-boundary.md`; coordinate shared contracts, project/dependencies and fixture copies with WS4.

**Interfaces:** Produces importable agreed `BaselineBundle`, `ActionConfig`, `ActionAssumptions`, `ConstraintConfig`, `UncertaintySpec`, `RiskConfig`, `RiskResult`, `SimulationFn`, `BenchmarkSource`, `BenchmarkConfig`, `BenchmarkDataset`, `BenchmarkResult`; shared validators/serializers and failure mapping.

- [ ] Record current repo state, available modules, ownership and C0 blockers without changing another workstream's files.
- [ ] Resolve A01–A08 and A10–A12/A16–A20/A22; proposals that affect shared serialized shape need WS4 review.
- [ ] Contract tests reject bad versions/nonfinite fields and round-trip each delivered fixture; label risk shape fixture as illustrative.
- [ ] Run the implemented C0 contract suite from root; record actual command/output. If C0 is absent, stop dependent implementation and deliver the concrete boundary note, not private replacement contracts.
- [ ] Commit only the owned boundary note after review; shared foundation merges through its own coordinated change.

## Task 1: test-only behavioral simulator and fixtures

**Files:** Create `tests/mocks/risk_simulator.py`; add owned cases in `tests/unit/test_risk.py`; copy reviewed fixtures through C0 stewardship.

**Interfaces:** Consumes C0 types; produces `affine_simulator(baseline, config, *, assumptions) -> SimulationResult`, implementing the exact `SimulationFn` contract in tests only.

- [ ] Test hand-computed affine CO₂/cost/profit from the tests/mocks spec; changing effectiveness or capex must change totals.
- [ ] Run the specific sensitivity test and verify expected missing-double failure before implementation.
- [ ] Implement the test double with schema-valid monthly allocations/metrics and `is_mock=true`; it uses no production action helpers.
- [ ] Test no-op, input immutability, schema validation and typed output against known fixture inputs.
- [ ] Run `python -m pytest tests/unit/test_risk.py -q`; commit the focused test-support slice after passing.

## Task 2: seeded sampler and assumption copies

**Files:** Create accepted `config/uncertainty.json`; implement sampling helpers in `src/risk/sampling.py` or `monte_carlo.py`; add `test_risk.py` cases.

**Interfaces (proposed internal, settle at Task 0):** `generate_trial_matrix(uncertainty: UncertaintySpec, config: RiskConfig) -> np.ndarray`; `sample_assumptions(parent: ActionAssumptions, trial: np.ndarray, *, uncertainty: UncertaintySpec, seed: int, trial_index: int) -> ActionAssumptions`. Matrix is n×18, action-major effect/capex/fixed-opex.

- [ ] Test reversed/nonfinite bounds, unsupported distribution/correlation, bool/float/over-limit n, and nondefault adoption mapping rejection.
- [ ] Test multiplier bounds, all channels drawn, neutral [1,1] matrix, fixed prefix and same-seed/strategy-order independence.
- [ ] Test building parent .3 × effect .9 = .27; supplier .3/1000 × .9 = .27/900; per-action unequal cost multipliers and unchanged tariff/life fields.
- [ ] Run targeted cases to see expected missing-helper failure; implement local RNG generation, copying and full identity/hash rules.
- [ ] Test parent/nested-input immutability and unique trial identity; record sampler version.
- [ ] Run owned risk unit cases; commit sampler/config/mapping slice.

## Task 3: Monte Carlo runner

**Files:** Implement `src/risk/monte_carlo.py`; extend `tests/unit/test_risk.py`.

**Interfaces:** `evaluate_strategy_risk(baseline: BaselineBundle, action_config: ActionConfig, *, constraints: ConstraintConfig, assumptions: ActionAssumptions, uncertainty: UncertaintySpec, config: RiskConfig, simulator: SimulationFn) -> RiskResult` exactly. Consumes sampler and canonical simulator; outputs original deterministic strategy identity and valid trial arrays.

- [ ] Tests capture sampled assumptions and n trial calls, original baseline/config, and original top-level strategy ID.
- [ ] Tests require no-op baseline identity and neutral-uncertainty affine parity for every trial.
- [ ] Test simulator exception/nonfinite output aborts instead of dropping/retrying a trial or returning a summary.
- [ ] Run failing targeted tests; implement validation, deterministic identity resolution through shared code, sampled calls and CO₂/profit/cost array extraction.
- [ ] Keep parent/config/constraints unmutated and every sampled assumption ID auditable; no action accounting formula in risk.
- [ ] Run owned unit tests and import smoke; commit runner slice after passing.

## Task 4: exact flags, summaries and JSON

**Files:** Implement summary helpers in `src/risk/statistics.py` or `monte_carlo.py`; extend shared serializer only through review; add risk unit/fixture tests.

**Interfaces (proposed internal):** `summarize_trials(samples: pd.DataFrame) -> dict[str, float | None]`, given validated exact canonical sample columns and agreed raw-boundary flags. Public output remains shared `RiskResult`.

- [ ] Tests: [10,20,30,40] mean25/p05=11.5/p95=38.5; skewed mean need not lie between quantiles.
- [ ] Tests: four flags yield target.5/profit.5/budget.75/joint.25 and MCSE.25; p=0/1,n=1; strict equality/near-violation raw boundaries.
- [ ] Tests: zero CO₂ + positive target error; zero/zero agreed flag; negative and zero profit cases; no NaN/Infinity in wire payload.
- [ ] Implement all 13 exact summary fields; optional sample fields exactly match schema, summary invariant under retain flag.
- [ ] JSON round-trip numeric/ID/null/bool meanings; freeze independent test expectations instead of copying arbitrary illustrative risk numbers.
- [ ] Run risk + implemented shared serialization tests; commit statistics/output slice.

## Task 5: offline benchmark normalization

**Files:** Implement `src/benchmarking/normalize.py`; add `tests/unit/test_benchmark.py`; source mapping/metadata fixtures under reviewed paths.

**Interfaces:** Consumes agreed `BenchmarkSource` mapping/raw rows; produces `BenchmarkDataset` with canonical peer frame and metadata. Proposed internal `normalize_peer_data(raw: pd.DataFrame, *, source: BenchmarkSource) -> BenchmarkDataset`; only adopt after exact mapping fields are approved.

- [ ] Tests kg→tonnes, scaled revenue units, FX direction/method/date, finite positive denominator and zero emissions validity.
- [ ] Tests annual fiscal/calendar/leap periods, missing scopes, scope2/industry mappings, duplicate entity periods, synthetic separation and exclusion diagnostics.
- [ ] Run failing targeted cases; implement explicit transformations, no magnitude guessing, no hidden missing-data fills.
- [ ] Verify original raw frame unchanged; preserve entity mapping, source/licence/retrieval/hash and reported period evidence.
- [ ] Validate the delivered synthetic peer fixture as 10 compatible unique peers; commit normalization slice.

## Task 6: real simulator risk parity and C5a handoff

**Files:** Add `tests/integration/test_risk_simulator.py`; reviewed neutral and actual risk fixtures; `docs/workstream3/handoffs/risk.md`.

**Interfaces:** Consumes WS2's accepted `simulate_strategy` and C2 golden fixtures. Publishes RiskResult for two original strategies, common trial metadata and runtime to WS2/WS4. Recommendation edits belong to WS2.

- [ ] Test all-neutral risk matches golden no-op and nonzero results (1200/1200000/0 and 843.744/1210940.7847619047/186581.12).
- [ ] Test nonneutral no-op parity, input immutability, actual effect/cost response and adverse EV behavior with WS2-reviewed inputs.
- [ ] Test two strategies share multipliers by trial; exclude malformed trials; round-trip actual risk outputs.
- [ ] Measure 1,000 trials on declared fixture/hardware; record runtime/versions, do not add brittle absolute timing assertions.
- [ ] Publish WS2 recommendation fixture obligations (≤20 endpoints-preserving pool, common trials, thresholds, missing/partial/fallback), and WS4 keys/copy/capabilities.
- [ ] Run targeted boundary and applicable P0 regressions; commit reviewed risk handoff slice. Claim C5a only with real provider and consumer approval.

## Task 7: pure benchmark calculation

**Files:** Implement `src/benchmarking/benchmark.py`; extend `tests/unit/test_benchmark.py`; valid/unavailable fixtures.

**Interfaces:** `benchmark_company(baseline: BaselineBundle, peers: BenchmarkDataset, *, config: BenchmarkConfig) -> BenchmarkResult` exactly; no network, models, simulator, optimizer or Streamlit.

- [ ] Test fixture arithmetic: intensity100, median105, percentile45, better55, count10.
- [ ] Test all-equal50, all-higher0, all-lower100 and disjoint tolerance-based ties.
- [ ] Test min-count after all filters, same-company entity exclusion, latest entity period, method/scope/industry/gap compatibility, zero revenue and unsupported benchmark horizon.
- [ ] Run failing cases; implement validated filters, baseline totals, rank and unavailable reasons/counts with full metadata.
- [ ] Confirm result baseline period and peer reporting span are distinct; no rank passed as global industry truth.
- [ ] Run benchmark unit/contract tests; commit comparison slice.

## Task 8: real source qualification

**Files:** Create `docs/workstream3/handoffs/benchmark-source.md`; accepted source config/metadata only if evidence supports it.

**Interfaces:** Produces provider-specific documented mapping into `BenchmarkDataset`; no public signature change.

- [ ] Timebox research and verify primary provider documentation, actual fields/sample, licence, entity IDs, annual revenue, scopes, scope2 method, industry and completed reporting dates.
- [ ] Count usable entities after compatibility/exclusion; require minimum10, not ten raw records from fewer entities.
- [ ] Record source limitations and demonstration-accounting compatibility; no arbitrary relabelling to `market_based_demo`.
- [ ] Choose verified source or explicitly unavailable real-source capability; synthetic remains a separate labelled example.
- [ ] Commit evidence/mapping note; do not implement imaginary HTTP fields/endpoints.

## Task 9: CSV/snapshot and bounded HTTP adapter

**Files:** Implement `src/benchmarking/adapters.py`; add `test_benchmark_adapters.py`; normalized snapshot and metadata.

**Interfaces:** `load_benchmark_data(*, source: BenchmarkSource, timeout_seconds: float = 5.0, offline: bool = False) -> BenchmarkDataset` exactly. Internal transport injectable; expected boundary exception names and conversion approved at C0.

- [ ] Test offline makes zero requests and returns validated snapshot; missing/corrupt/stale/version/source mismatches have agreed typed behavior.
- [ ] Test HTTP success, timeouts, bounded retries/Retry-After,401/403/404 no-retry, invalid content/schema/payload limits and secret redaction using fake transport/clock.
- [ ] Implement only verified provider mapping, finite timeout and retry policy; normalize before output, no import-time request or credential reads.
- [ ] Test compatible online-failure cache with preserved retrieval age/source kind; no silent synthetic or incompatible/stale fallback.
- [ ] Run adapter unit suite with network disabled/mocked; commit adapter slice.

## Task 10: optional provider integration and C5c handoff

**Files:** Coordinate `src/integration/services.py`, `pipeline.py`, `cache_keys.py`, capability flags and shared integration tests with WS4; own benchmark handoff docs/fixtures.

**Interfaces:** Existing Services/AnalysisBundle plus approved optional metadata, no consumer reimplementation of statistics/rank.

- [ ] Risk real provider swap preserves contract/IDs; benchmark valid/unavailable/cached cases render correct units/period/source/count labels.
- [ ] Known adapter failures become unavailable through WS4, programming errors surface; disabling risk/benchmark leaves P0 import and outputs usable.
- [ ] Keys invalidate on all domain inputs; tolerance-only reranks WS2 results without rerunning trials; sliders do not automatically trigger a full pool.
- [ ] Confirm C5a then C5b before claiming C5c feature acceptance; local module tests may pass earlier.
- [ ] Run coordinated integration + applicable shared regression tests; commit handoff, leave ownership-overlapping changes to WS4 review.

## Task 11: final verification and release-ready evidence

**Files:** Finalize risk/benchmark/source handoffs, owned fixtures/config snapshots, reproduction commands and limitations.

**Interfaces:** Consumer-readable evidence for contract1.0.0 and chosen config/sampler/dependency/fixture revisions.

- [ ] Run implemented contract/unit/integration suites offline; include real simulator and optional unavailable paths.
- [ ] Check 13 risk summary fields, sample schema, stable joins, strict boundary behavior, peer normalizations, typed failure mapping and no secrets/personal paths.
- [ ] Profile 1,000-trial plan and bounded pool; retain 5,000 only if justified. Document runtime shortfalls rather than fake compliance.
- [ ] Record no forecast-error calibration, illustrative action economics, independent draws, limited peer coverage, forecast-vs-reported gap and finite-trial interpretation.
- [ ] Save labelled replay artifacts; WS4 owns UI wiring, release tags and final demo acceptance.
- [ ] Commit owned completed slice only after actual checks; do not claim implementation from this plan.

## Commands after their prerequisites exist

```sh
python -m pytest tests/contracts -q
python -m pytest tests/unit/test_risk.py -q
python -m pytest tests/integration/test_risk_simulator.py -q
python -m pytest tests/unit/test_benchmark.py tests/unit/test_benchmark_adapters.py -q
python -m pytest tests/integration -q
```

These are planned commands. They are not runnable in the audited documentation-only checkout. Use the agreed installed Python3.11 environment after C0; no environment deletion or global-package modification is part of this plan.

## Self-review evidence

The plan covers WS3's risk inputs/output, initial uncertainty mapping, identity/CRN, statistical definitions, performance limits, recommendation handoff, annual peer schema/filtering/percentile, source qualification, adapter failure/cache/offline policy and both consumer gates. Proposed policies are explicitly separated from fixed contract requirements. The concrete edge matrix maps additional failures to tests; public signatures/types are identical to the pulled specs. Tasks have standalone behavioral tests and do not require a second action engine, UI implementation or live network to be reviewed.
