# Workstream 3 — Risk/Monte Carlo and External Benchmarking/API

Developer 3 owns two independent P1 services. Risk consumes the action simulator; benchmarking consumes baseline totals and normalized external peers. Neither imports Streamlit or trained model internals.

## Read first

Read [contracts](../SHARED_CONTRACTS.md), [schemas](../DATA_SCHEMAS.md), [risk/benchmark specification](../RISK_AND_BENCHMARK_SPEC.md), and [action model](../ACTION_MODEL.md).

## Ownership

Source: `src/risk/monte_carlo.py`, `src/benchmarking/adapters.py`, `src/benchmarking/normalize.py`, `src/benchmarking/benchmark.py`.

Configuration/data: `config/uncertainty.json`, `data/benchmark.csv` and its source metadata. Tests: `tests/unit/test_risk.py`, `test_benchmark.py`, `test_benchmark_adapters.py` within `tests/unit/`.

WS2 owns deterministic assumptions; sample copies of those objects rather than altering shared config. WS4 owns API credential wiring and cache policy at orchestration; WS3 specifies provider needs.

## Inputs and outputs

Risk inputs: baseline, action config, deterministic assumptions, constraints, uncertainty specification, risk configuration, injected simulator. Output: RiskResult with conditional trial summaries and reproducibility metadata.

Benchmark inputs: BenchmarkSource → normalized BenchmarkDataset; baseline + BenchmarkConfig → BenchmarkResult. HTTP responses and raw source-specific column names never reach the UI.

## Exact local implementation order

| Step | Priority | Task | Evidence |
|---:|---|---|---|
| 1 | P0 support | C0 uncertainty fields and fixture reviews | Simulator sampling hook agreed |
| 2 | P1 preparation | Seeded trial matrix + simulator injection | Stub-based tests pass independently |
| 3 | P1 preparation | Peer schema normalization + offline fixture | Unit/coverage/percentile tests |
| 4 | P1 | Real simulator Monte Carlo | Zero uncertainty/no-op parity |
| 5 | P1 | Risk result + tolerance selection handoff | C5a; WS2/WS4 approve |
| 6 | P1 | External adapter, snapshot/failure behavior | Mocked transport and provenance |
| 7 | P1 | Baseline benchmark UI handoff | C5c, after risk and SHAP acceptance |

Local preparation for benchmarking can happen early; production feature acceptance follows Risk → SHAP → Benchmark. No live API or dataset acquisition is a prerequisite for P0.

## Start without waiting

Accept a simulator callable from C0. Use the deterministic affine test double specified in [TESTING_AND_MOCKS.md](../TESTING_AND_MOCKS.md), ensuring sampled assumptions actually influence its outputs. A static fixture-only simulator is sufficient for UI shape but insufficient for uncertainty tests.

Build normalization and percentile logic from the synthetic compatible peer fixture. If no appropriate real dataset is found within the timebox, publish an unavailable external benchmark or a clearly labelled illustrative synthetic benchmark. Do not invent a real API source or silently treat a placeholder as reported data.

## Risk work details

Bound effect multipliers, vary cost coefficients and keep the baseline fixed. Pre-generate common random numbers for strategy comparison. Start at 1,000 trials for a selected plan. Evaluate at most 20 frontier strategies for policy selection, using the same trial matrix. Measure runtime before enabling 5,000 trials or retaining samples.

Summarize empirical intervals and individual/joint constraint probabilities. Preserve actual user budget/profit/target boundaries. Document that probabilities depend on chosen assumptions, and forecast uncertainty is not yet included.

No-op must reproduce baseline in every trial. Zero uncertainty must reproduce the canonical simulator, proving no second numerical engine has entered the risk code.

## Benchmark work details

Define source mapping, units, currency/FX, scope coverage, scope2 method, reporting periods, industry categories, exclusions and licence before publishing an external result. Use tonnes per million GBP consistently.

Make timeouts/retries bounded. Offline mode reads a normalized snapshot. No import-time network call. Tests replace the HTTP transport and do not need credentials.

Peer-count or compatibility failure produces an unavailable result with a reason. Same-company exclusion and percentile tie behavior are explicit. Forecast-vs-historical peer comparison remains labelled.

## Tests and handoffs

Risk tests: same seed/config → same numerical summary; different seed normally changes non-degenerate trials; p05 ≤ mean is not universally guaranteed, so test quantile ordering p05 ≤ p95 and means within sample min/max instead; probability bounds; raw flags; no-op/zero uncertainty; common trial alignment.

Benchmark tests: kg→tonnes; GBP denominator; FX provenance; duplicate/industry/source exclusions; period/scope mismatch; tied percentile; lower-is-better direction; small peer rejection; offline, timeout and cache statuses.

C5a handoff contains uncertainty JSON, RiskResult for two strategies, seed/trial count, tests, runtime and limitations. WS2 tests policy selection and WS4 charts.

C5c handoff contains source-normalization specification, peer snapshot metadata, valid/unavailable BenchmarkResult and offline-demo evidence.

Definition of done: typed services work against real baseline/simulator without special preprocessing; risk assumptions are disclosed; benchmarks are compatible and sourced; optional failure never breaks P0; tests need no network or secrets.

Reference branches: `feat/ws3-risk` and `feat/ws3-benchmark`.
