# WS3 delivery: risk and benchmark

Branch `workspace3`, 2026-10-03. Everything below was run in this checkout unless stated otherwise.

> **Labels that must travel with every number below**
> - WS3 risk tests and the saved sample use the **behavioral mock simulator**. The hybrid dashboard preset runs risk trials over the **real WS2 action engine**. Uncertainty bounds are **illustrative, not calibrated**: independent uniform action multipliers, conditional on the fixed baseline forecast.
> - p05–p95 is a **trial outcome interval**, not a confidence interval. A probability of 1.0 is not a guarantee.
> - The benchmark uses **ten synthetic peers**. It is a labelled offline demonstration, not a real industry rank.
> - Risk-aware recommendation is WS2-owned and integrated in this checkout. It consumes WS3 risk results when requested; the mock optimizer still ignores risk results.

## Public APIs and factories

| Item | Location | Notes |
|---|---|---|
| `evaluate_strategy_risk(baseline, action_config, *, constraints, assumptions, uncertainty, config, simulator) -> RiskResult` | `src/risk/monte_carlo.py` | Calls the injected `SimulationFn` once per trial and contains no action formulas. Returns the original `compute_strategy_id`. |
| `UncertaintySpec`, `load_uncertainty(path)`, `sample_multipliers`, `apply_multipliers` | `src/risk/monte_carlo.py` | `UncertaintySpec.neutral()` sets all 18 bounds to [1, 1]. |
| `create_risk_provider(path=None) -> MonteCarloRiskProvider` | `src/risk/provider.py` | `RiskProvider` protocol. `info=(risk, ws3-monte-carlo, kind=real, is_mock=False)`. |
| `load_benchmark_data(*, source, timeout_seconds=5.0, offline=False) -> BenchmarkDataset` | `src/benchmarking/adapters.py` | Offline CSV only. `kind != "csv"` raises `BenchmarkSourceError("unsupported_source")`. |
| `benchmark_company(baseline, peers, *, config) -> BenchmarkResult` | `src/benchmarking/benchmark.py` | Comparison problems return `unavailable` with a reason and no rank. |
| `BenchmarkSource`, `BenchmarkConfig`, `BenchmarkDataset`, `normalize_peers`, `BenchmarkSourceError(ProviderError)` | `adapters.py`, `benchmark.py`, `normalize.py` | WS3-local types. No shared result schema changed. |
| `create_benchmark_provider(path=None) -> OfflineBenchmarkProvider` | `src/benchmarking/provider.py` | `BenchmarkProvider` protocol. Only `BenchmarkSourceError` becomes `unavailable`. |

Both factories are discovered by `src/integration/real_providers.py` with `create_services(mode="hybrid", provider_overrides={"risk": "real", "benchmark": "real"})`. They read their config when called, never at import.

## Configuration and content hashes

| File | sha256 | Notes |
|---|---|---|
| `config/uncertainty.json` | `0b9a8199ea70c704…` | Provider version `ws3-risk-1+illustrative-risk-v1@67b78b15c31285bb`; the suffix is the canonical content hash of the parsed spec. |
| `config/benchmark.json` | `720023ffc9edbb8d…` | Covered by the benchmark version string below. |
| `data/benchmark.csv` | `9af8613ccb4086d4…` | Covered by the benchmark version string below. |
| `data/benchmark_metadata.json` | `9f95768e1304c05e…` | Covered by the benchmark version string below. |

The benchmark provider version is `ws3-benchmark-1+synthetic-peers-v1+c720023ffc9ed+d9af8613ccb40+m9f95768e1304` (config, CSV and metadata hashes). Any edit to these files changes `ProviderInfo.version` and therefore the WS4 cache key (tested). If the snapshot changes after the provider is created, the result is `unavailable` with reason `snapshot_hash_mismatch`.

**Uncertainty.** All six actions use effectiveness [0.85, 1], capex [0.9, 1.1] and fixed opex [0.9, 1.1]. Sampling is `default_rng(seed).random((n, 18))` in action-major `(effectiveness, capex, fixed_opex)` order. Every compared strategy uses the same trials, and no seed is derived from a strategy ID. The default is 1,000 trials and the maximum 5,000. The demo script uses 100 trials, labelled.

**Benchmark.** Industry `technology`, coverage `scope1_scope2_scope3`, scope 2 method `market_based_demo`, `min_peers=10`, maximum period-end gap 24 months, basis `forecast_vs_historical_peers`. The 12-month forecast baseline (2027) is compared with the newest compatible historical annual peer periods (2026, a 12-month gap). `BenchmarkResult.period_start/end` is the **forecast** period, as in the shared fixture.

### Provisional policies (boundary draft; reviewers still needed)

- **Effect multipliers:**
  - Renewable, EV and travel effectiveness.
  - Building and cloud maximum reduction.
  - Supplier maximum reduction **and** supplier monthly savings.
- **Cost multipliers:** capex and fixed monthly opex, sampled per action.
- **Fixed during sampling:** tariffs, grid factors and asset lives.
- **Trial flags** use raw tolerances: cost ≤ budget + 0.01 GBP, profit ≥ floor − 0.01 GBP, reduction ≥ target − 1e-8.
- **Benchmark ranking:**
  - Midpoint percentile `100*(L + 0.5E)/N` with tie tolerance 1e-8.
  - The target company is excluded by exact `entity_id` match (or `peer_id` when there is no `entity_id`), plus `exclude_entity_ids`.
  - Only the newest compatible period per entity counts.

## Reproduce

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/demo_ws3_risk.py
.venv/bin/streamlit run app.py
```

**Environment.** `.venv` was built from the local `adahack` Python 3.11.16 with `pip install -r requirements.txt`: numpy 2.4.6, pandas 3.0.6, streamlit 1.65.0, pytest 9.1.1. The machine is an Apple M5 Pro.

**Dashboard steps:**
1. Set **Provider mode** to `hybrid`.
2. Set the risk and benchmark providers to `real`; leave the other providers on `mock`.
3. Tick **Risk (Monte Carlo)** and **Benchmark**, then click **Optimize**.
4. Open the Risk and Benchmark tabs.

## Results (actual runs)

**Tests.** Latest full-suite run: `501 passed, 1 skipped in 84.52s`. The skip is the opt-in live Ollama smoke test. The WS3 files are:
- `tests/unit/test_risk.py`: 25
- `tests/unit/test_benchmark.py`: 19
- `tests/integration/test_ws3_providers.py`: 18

`tests/integration/test_provider_swap.py` had one assertion that expected risk and benchmark to be unimplemented; it was updated.

**Risk coverage:**
- Bounds and all 18 channel mappings, including supplier savings and fixed opex.
- Common trials across strategies.
- Neutral-uncertainty parity and no-op behaviour.
- Inputs are not mutated, and strategy IDs are the originals.
- Hand-authored oracles: quantiles 25 / 11.5 / 38.5; probabilities 0.5 / 0.5 / 0.75 / 0.25; MCSE 0.25; raw-tolerance boundaries.
- A single trial (n=1).
- Zero CO2: an undefined reduction ratio counts as met when the target is zero, and raises `RiskError` when the target is positive. Losses (negative profit) are valid outcomes.
- Two different strategies receive identical sampled assumptions trial by trial (common trials).
- A failed trial aborts with `RiskError`.
- Invalid specs and configs are rejected.

**Benchmark coverage:**
- Oracle 100 / 105 / 45 / 55 / 10.
- Ties: all equal gives 50, all higher 0, all lower 100, and values at the tie tolerance count correctly.
- Nine peers gives `unavailable`.
- Units, currency and revenue scale.
- Scope, method and period mismatches.
- Entity exclusion and newest period per entity.
- No network: sockets are blocked during the test.
- Missing, corrupt and HTTP sources.
- A 36-month baseline gives `unsupported_horizon`.
- JSON round-trips.

**Integration coverage:**
- Hybrid discovery of both providers.
- A pipeline with both enabled: risk IDs equal the selected Pareto pool, the benchmark oracle holds, results are labelled synthetic, and the bundle survives a JSON round-trip.
- A missing or corrupt snapshot leaves P0 and risk working.
- A missing or invalid `uncertainty.json` or `benchmark.json` disables **only** that capability, with a visible reason, and P0 still runs.
- Programming errors still surface.

**Runtime.** One strategy at 1,000 trials takes 0.25 s over the mock simulator. A dashboard **Optimize** run in hybrid mode with risk (1,000 trials across the pool of 19 frontier strategies) and benchmark takes 5.6 s in a headless Streamlit `AppTest` run, with no errors or exceptions. The benchmark caption reads "10 peers · source `synthetic-peers-v1` (synthetic)".

**Saved sample.** `carbonopt-ai-docs/docs/handoffs/ws3/risk_sample_mock_simulator.json` holds a full `RiskResult` with all 1,000 retained trials (seed 42, mock simulator, illustrative uncertainty, fixture strategy):
- CO2 mean 957.282, p05–p95 945.346–969.576.
- Target probability 0.605 (MCSE 0.0155); joint 0.605.

A test recomputes it and requires identical summary and samples.

**Demo, 100 trials, mock simulator, fixture strategy `strategy-8be15857fffc57f6`:**
- CO2 mean 958.474 tCO2e, p05–p95 946.537–969.889.
- Profit mean 1,198,359.89 GBP.
- Budget probability 1.000.
- Target probability 0.540 (MCSE 0.050).

### WS2 real-engine parity and integration

The earlier parity check extracted the WS2 engine from `origin/workstream2` (`22cee48`, `src/actions/engine.py`) into a temporary directory because that branch's `src/contracts` diverged from WS4's. It connected the engine to `evaluate_strategy_risk` through the shared v1 JSON serializers. WS2 is now integrated in this checkout, and `tests/integration/test_ws2_ws4_hybrid.py` exercises the real simulator, optimizer, recommendation policy, and dashboard state. The isolated parity measurements were:

- **Deterministic (WS2):** CO2 843.7439999999999, profit 1,210,940.7847619047, cost 186,581.12.
- **Neutral uncertainty, 20 trials:** mean CO2 843.744, with p05 = p95; profit 1,210,940.784761905; cost 186,581.12. This matches the golden values to within 1e-9.
- **No-op under illustrative uncertainty:** CO2 1200 / 1200, profit 1,200,000 / 1,200,000, cost 0.
- **Illustrative, 1,000 trials over the WS2 engine:** 3.14 s.
  - CO2 mean 870.081, p05–p95 853.058–888.042.
  - Profit mean 1,208,384.86; cost mean 185,061.24.
  - Target, budget and joint probability all 1.000.

`is_mock=True` there because WS2 propagates the fixture baseline's flag. This is evidence only. The in-repo tests still run over the mock simulator until WS2 merges.

## Limitations

- **Risk over the mock simulator:** the behavioral mock ignores the building, cloud and supplier coefficients and opex. Unit tests confirm those values reach the simulator; the integrated hybrid preset also runs against WS2's real engine.
- **Benchmark exclusion counts:** counts from the comparison step appear only in `reason` when the result is `unavailable`. `ok` results carry none, because no schema fields were added. Exclusions found during normalization are kept in `BenchmarkDataset.metadata["exclusions"]`.
- **No live or HTTP benchmark, FX, correlations, forecast-error uncertainty or multi-year slices.** An HTTP source returns `unavailable` (`unsupported_source`).
- **Unchanged WS4 files:** `BenchmarkSourceError` lives in `src/benchmarking/adapters.py`, so WS4's `errors.py` is untouched. Shared `RiskResult` and `BenchmarkResult` are unchanged.

## Dependencies and follow-ups

**WS2**
1. Review the provisional multiplier mapping (supplier savings, fixed opex) and the raw-tolerance flags.
2. Keep the real-engine parity check reproducible in the repository as integration tests evolve; isolated measurements above are historical evidence from before the merge.

**WS4**
1. Review the one-line boundary change in `real_providers._factory_provider`. A `ContractValidationError` raised by a factory now becomes `ProviderUnavailable`, so a bad optional config disables only that slot with a reason. Other exceptions still surface. A P0 factory config error still stops services in real mode, as before.
2. The Benchmark tab caption labels `period_start/end` as "peer period". Per the shared fixture contract these are the **forecast** period (2027); peers are 2026. This is a wording fix only and was not changed here.
3. Optional: decide whether `BenchmarkSourceError` should move into `src/contracts/errors.py`.

**WS1**
1. The benchmark uses `baseline.totals` (12-month revenue and CO2), the monthly timestamps and `scope2_method`. A real forecast must keep `scope2_method` equal to `market_based_demo`, or update `config/benchmark.json`; a mismatch returns `unavailable`. Horizons of 36 or 60 months return `unsupported_horizon` until annual slices are specified.

**Before any non-synthetic claim:** qualify a real peer source (at least 10 entities, scope 1+2+3, compatible scope 2 method, GBP or FX, completed periods, usage rights) and calibrate the uncertainty bounds.


## Integration update (branch `feat/integration-all-workstreams`)

- **Risk:** risk runs over the real WS1 baseline and WS2 engine in `real` mode. `load_uncertainty` resolves relative paths against the working directory, so the integration adapter passes a repo-rooted path. A follow-up could resolve relative paths against the repository root inside WS3.
- **Benchmark:** the CSV company uses `config/benchmark_supply_chain.json` (industry `logistics`, scope 2 `market_based`). The bundled peers are `technology`, so the result is an explicit `unavailable` (industry_mismatch=10).
- **Peer period wording:** the WS4 caption now reads "forecast period compared", resolving follow-up WS4-2.

See [INTEGRATION_HANDOFF.md](../../../../docs/handoffs/INTEGRATION_HANDOFF.md).
