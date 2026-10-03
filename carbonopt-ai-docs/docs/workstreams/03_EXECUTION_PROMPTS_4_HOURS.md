# Workstream 3: five prompts for the last four hours

**Preparatory audits are complete. These five prompts are the only execution checklist.** No separate bootstrap is needed. Stay in the same agent session where possible, review each result, then send the next prompt.

## Current repository check

Freshly fetched on 2026-10-03:

- `workspace3` HEAD `732a6f1` already includes WS4's implementation `c76872f` and the latest `origin/main` merge `781e91d`. No additional merge is needed. Your branch is three commits ahead of `origin/workspace3`; preserve it and the untracked handoff files.
- WS4 delivered shared contracts, serializers/validators/identity helpers, fixtures, behavioral mocks, dashboard, integration pipeline, cache keys and tests. Skip recreating these.
- Still missing: `UncertaintySpec`, `BenchmarkSource`, `BenchmarkConfig`, `BenchmarkDataset`, WS3 numerical modules/configs/provider factories, and WS2's real action engine in this checkout.
- WS4 expects `src.risk.provider.create_risk_provider()` and `src.benchmarking.provider.create_benchmark_provider()`. Domain functions alone will not enable dashboard capabilities.
- Pipeline already selects at most 20 frontier plans and catches `ProviderError` for optional failures. Existing `RiskError` is suitable; preserve existing result types/statuses.
- Existing behavioral simulator responds to some effectiveness/capex inputs. It does not test building/cloud/supplier coefficients or fixed opex; inspect sampled assumptions for those mappings.
- The preserved `c0-boundary.md` remains a draft. Its multiplicative-effect and raw-tolerance proposals differ from the older prompts. They are not recorded team approvals.
- A fresh test attempt in local `adahack` stopped at `No module named pytest`. The draft's scratch-environment 102-test pass is historical, not a fresh result here.

## Scope and timing

| Prompt | Budget | Outcome |
|---|---:|---|
| 1 | 25 min | Minimum missing contracts, configs and test environment |
| 2 | 70 min | Complete Monte Carlo plus focused tests |
| 3 | 45 min | Labelled offline synthetic benchmark plus tests |
| 4 | 40 min | Discoverable providers and hybrid integration |
| 5 | 35 min | Regression/parity checks, fixes and handoff |
| Buffer | 25 min | Installation, conflicts or numerical fixes |

Cut live HTTP, real-source research, credentials, retries/cache fallback, non-GBP sources, correlations, forecast-error uncertainty, extra result fields, detailed 5,000-trial reports, multi-year/optimized benchmarks and new UI/chat features. Keep the default 1,000 trials and existing maximum 5,000; small test counts are fine, silent count reduction is not.

The goal is working injected-simulator risk and a clearly labelled offline benchmark. Real risk acceptance still requires WS2's real simulator; risk-aware selection belongs to WS2. A synthetic benchmark is a demonstration, not real external-data evidence.

## Proposed defaults for this fast path

Follow any newer accepted decision first. Otherwise use these **provisional implementation policies from your latest boundary draft**, document them, and leave consumer review pending rather than claiming approval:

- Multiply parent effect coefficients for all actions; current adoption defaults are 1, so this matches current shared-fixture behavior. Nondefault adoption semantics need WS2 review. Neutral means all multipliers [1,1].
- Sample per-action capex and fixed monthly opex only. Supplier effect scales both maximum reduction and monthly savings. Keep tariffs/grid factors/asset lives fixed.
- Trial flags use shared raw tolerances: cost ≤ budget + 0.01 GBP; profit ≥ floor − 0.01 GBP; reduction ≥ target − 1e-8. No normalized solver epsilon. Do not reuse the old strict-boundary expectations unchanged.
- Generate an independent n×18 matrix in action-major `(effectiveness, capex, fixed_opex)` order; draw all channels. Compared strategies use common trials, never seeds derived from strategy IDs.
- Preserve current `RiskResult`, `BenchmarkResult` and six-field `Provenance`; put hashes in provenance/provider version and supplementary audit details in config/dataset metadata and handoff. Avoid optional result-schema expansion.
- Preserve public signatures/statuses and version-1 fixture compatibility. Only offline GBP data is enabled; unsupported HTTP/FX/correlation inputs fail explicitly.

## Prompt 1 — finish the minimum foundation

```text
We have four hours. The preparatory audits are complete. Read
carbonopt-ai-docs/docs/workstreams/03_EXECUTION_PROMPTS_4_HOURS.md, carbonopt-ai-docs/docs/handoffs/ws3/c0-boundary.md,
current src/contracts and docs/handoffs/WS4_DASHBOARD_HANDOFF.md.
Implement only this task, aiming for 25 minutes. Preserve workspace3 and all
existing/untracked work; do not repeat the readiness audit or reset branches.

Reuse existing RiskConfig/RiskResult/BenchmarkResult/ActionAssumptions,
identity helpers, validators, serializers and RiskError. Add only missing
uniform bounds/action uncertainty/UncertaintySpec and BenchmarkSource,
BenchmarkConfig, BenchmarkDataset with required validation/JSON conversion.
Use the boundary draft's compatible input shapes; only offline CSV/JSON GBP
sources are enabled. No new fields on existing outputs or private competing types.
Record provisional decisions/reviewer needs in a short implementation note.

Create config/uncertainty.json: six canonical actions, each independent
effectiveness[.85,1], capex[.9,1.1], fixed_opex[.9,1.1], sampler version and
illustrative calibration note. Add neutral test spec with all 18 bounds[1,1].
Reject missing actions, unsupported distributions/correlations, nonfinite or
reversed bounds, effects outside[0,1], negative costs, negative/noninteger seed,
noninteger/bool trial count and counts outside 1..5000.

Use a suitable existing test environment, otherwise create repo-local .venv
from available Python 3.11 and install requirements.txt. Local adahack lacks
pytest. Do not change global packages or delete environments; reuse WS4 pins.
Test config round-trips, invalid inputs and existing fixture compatibility.
Run focused tests plus tests/contracts when possible. Stop with actual commands,
results, changed files and remaining dependencies. No UI/HTTP or broad redesign.
```

## Prompt 2 — implement the complete risk service

```text
Read carbonopt-ai-docs/docs/workstreams/03_EXECUTION_PROMPTS_4_HOURS.md and latest boundary decisions.
Aim for 70 minutes. Implement src/risk/monte_carlo.py with the fixed public API:
evaluate_strategy_risk(baseline, action_config,*, constraints, assumptions,
uncertainty, config, simulator)->RiskResult. Reuse shared contracts and validation.

Generate default_rng(seed).random((n,18)) in canonical action-major order;
draw every channel. Copy parent assumptions/nested costs without mutation.
Multiply renewable/EV/travel effects, building/cloud maximum reductions,
supplier reduction AND full monthly savings; sample per-action capex/fixed
opex independently. Keep action config, baseline, tariffs/grid/asset lives fixed.
Use parent/spec content hashes, seed, index for unique sampled assumption IDs.
Top-level strategy_id is ORIGINAL deterministic shared compute_strategy_id.

Call injected simulator per trial; extract CO2/profit/gross cost from metrics.
Never duplicate action/accounting formulas. Abort invalid trials with RiskError
at the provider boundary; never drop/resample. Unexpected programming bugs surface.
Preserve mock provenance when using a mocked simulator.
Produce all 13 summary fields and optional 7 sample columns from DATA_SCHEMAS;
linear p05/p95, means, p95cost, shared raw-tolerance flags, rowwise-AND joint and
target MCSE=sqrt(p*(1-p)/n). ZeroCO2 + positive target invalid, zero/zero target true;
losses valid, no NaN/Infinity. Retention toggle must not change summaries.

tests/unit/test_risk.py must prove bounds, seed/common-trial alignment,
captured six-action/fixed-opex mappings, supplier savings, immutability, IDs,
neutral/no-op parity, failed-trial abort, quantiles[10,20,30,40]→25/11.5/38.5,
hand-authored probabilities target .5/profit .5/budget .75/joint .25/MCSE .25,
n=1 and tolerance boundaries. Reuse BehavioralMockSimulator.simulate for development;
capture assumptions for mappings it ignores. If WS2 engine exists, neutral golden
843.744CO2/1210940.7847619047profit/186581.12cost and no-op1200/1200000/0
must pass. If absent, report C2 dependency;do not build a replacement action engine.
Run focused tests, save genuine computed sample for the simulator actually used,
measure 1,000 trials if feasible, and stop with evidence and integration needs.
```

## Prompt 3 — ship the offline benchmark

```text
Read carbonopt-ai-docs/docs/workstreams/03_EXECUTION_PROMPTS_4_HOURS.md. Aim for 45 minutes. Implement
src/benchmarking/{normalize, adapters, benchmark}.py with shared types and exact APIs:
load_benchmark_data(*, source, timeout_seconds=5.0, offline=False)->BenchmarkDataset;
benchmark_company(baseline, peers,*, config)->BenchmarkResult.
Support normalized offline CSV/JSON only. CSV never needs network regardless
of offline flag. Explicitly reject unsupported HTTP/non-GBP;no research/retries/FX.

Use existing ten synthetic peers for data/benchmark.csv plus source metadata;
keep synthetic/source/retrieval/licence/period labels. Add config/benchmark.json:
technology, scope1_scope2_scope3, matching demo scope2 method, min_peers=10, end gap 24 months,
forecast_vs_historical_peers. Validate explicit kg/tonne and GBP revenue scales,
positive revenue, finite nonnegative CO2, full annual fiscal/calendar periods,
unique IDs, industry/coverage/method/cohort and computed intensity. Missing scopes≠0.

Compare 12 month baseline only:CO2/(revenueGBP/1e6), median, midpoint percentile
100*(L+.5E)/N, better100-percentile. Absolute tie tolerance1e-8:ties first,
L=peer<c-tol (no overlap). Exclude target entity via explicit identity mapping,
not substring guessing;newest compatible period per peer entity. Keep exclusion
counts/reasons in dataset metadata/handoff. After filters require 10 peers;
too few/mismatch/unsupported horizon→unavailable with reason, not fake rank0.
Preserve existing BenchmarkResult shape;document baseline versus peer periods.

Focused benchmark/adapter tests:fixture intensity 100, median 105, percentile 45,
better 55, N=10;all ties 50, all higher 0, all lower 100;9-peer failure;units/revenue;
method/scope/date mismatch;entity exclusion;zero network;missing/corrupt snapshot;
JSON round-trip. Run tests and stop with working labelled offline capability.
```

## Prompt 4 — publish the provider factories and integrate

```text
Read carbonopt-ai-docs/docs/workstreams/03_EXECUTION_PROMPTS_4_HOURS.md, protocols.py and existing
integration/{real_providers, services, pipeline, cache_keys}.py. Aim for 40 minutes.
Add src/risk/provider.py:create_risk_provider() and
src/benchmarking/provider.py:create_benchmark_provider();WS4 requires these.

Risk exposes info:ProviderInfo, uncertainty_id and RiskProvider.evaluate signature;
bind uncertainty config, delegate to runner with simulator injected by pipeline.
Benchmark exposes info and benchmark(baseline);bind offline source/config,
delegate loading/ranking. Expected source failure→BenchmarkResult unavailable
with reason;RiskError lets pipeline exclude failed risk strategies without
breaking P0. Do not catch arbitrary programmer bugs or invent new status enums.
No import-time IO/network, Streamlit/model/optimizer-private imports.

ProviderInfo describes the numerical implementation;synthetic peer results remain
is_synthetic=true and risk over mocked simulator remains mock-provenanced.
Use content hashes in ProviderInfo.version so existing cache fingerprint changes
with uncertainty/source/config;hash serialized dicts/records, never DataFrame repr.
No new cache architecture. Confirm changed domain inputs invalidate results.

Hybrid smoke: create_services(mode='hybrid', provider_overrides={'risk':'real',
'benchmark':'real'}) using mocked P0 only if real P0 absent, and visibly disclose it.
Test riskIDs match ParetoIDs, benchmark output validates, and optional failures leave
P0 working. Reuse existing ≤20 pool. WS2 owns risk-aware recommendation;if absent,
document mock deterministic fallback, do not fake tolerance policy or replace NSGA-II.
Write exact WS2/WS4 follow-ups in a handoff;no external messages. Run relevant
provider-swap/integration tests and stop with discoverability/smoke evidence.
```

## Prompt 5 — verify, fix and hand off; add no features

```text
Read carbonopt-ai-docs/docs/workstreams/03_EXECUTION_PROMPTS_4_HOURS.md. Spend remaining ~35 minutes on
WS3 unit tests, existing contracts/integration suites, bounded fixes and handoff.
Report actual commands/results, not the old scratch 102-test pass. Fix owned defects;
no unrelated cleanup, new API or optional schema expansion. Never alter golden
expectations just to silence failures or discard bad trials.

If WS2 engine now exists, prove neutral golden parity/arbitrary-uncertainty no-op
through canonical simulator;otherwise report real-engine/C2 blocker honestly.
Measure 1,000 trials/selected strategy and pool if feasible, record machine/versions;
do not silently shrink n or implement fast duplicate accounting. Review zero CO2/
profit, losses, tolerances, IDs, common trials, all mappings, finite/null JSON, peer units/
identity/method/period/rank and optional failure isolation. Mock optimizer cannot
certify risk-aware selection;WS2 must supply real recommendation.

Write concise carbonopt-ai-docs/docs/handoffs/ws3/WS3_DELIVERY.md with public functions/
factory names, files/config IDs/hashes, seed/n, actual tests/runtime, computed examples,
synthetic/offline status, real-vs-mock dependencies and consumer reviewer needs.
Disclose illustrative independent action uncertainty conditional on fixed forecast;
p05–p95 is trial outcome interval, not confidence interval;p=1 isn't guarantee;
synthetic benchmark isn't a real global industry rank. Preserve Risk→SHAP→Benchmark
acceptance order;only claim gates actually passed. State exact WS2/WS4 next actions.
Finish with reviewable diff and suggested commit;don't switch/reset/delete/push/
publish/message unless separately requested. Stop;no new features or extra prompts.
```

## When the clock gets tight

Keep risk correctness, provider factories and one hybrid smoke test. If CSV conversion costs time, load the supplied normalized synthetic JSON and document its supported format. Skip helper-file proliferation, extra metadata fields, repeated audits and broad dependency changes. If WS2 remains absent, ship tested injected-simulator risk with an honest unresolved real-simulator handoff. Do not trade units, no-op identity, truthful provenance or failure isolation for apparent completeness.
