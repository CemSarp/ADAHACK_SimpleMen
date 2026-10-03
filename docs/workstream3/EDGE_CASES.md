# Workstream 3 edge cases and test oracles

Use this matrix alongside the current shared contracts. **F** means behavior fixed in the pulled specification. **P(Axx)** means the behavior below is proposed in the decision register and needs agreement before a test makes it authoritative. Tests live in WS3's owned unit files unless a shared-contract/integration owner is explicitly named.

Never update a golden result by calling the same helper under test and saving its answer. Use hand arithmetic, deliberately constructed samples, and existing reviewed fixtures. Numerical reproducibility ignores transient run IDs/time, not seed/config/hash/strategy identity.

## Contracts and baseline

| Case | Required behavior | Test / owner |
|---|---|---|
| Missing required field; wrong enum; unknown contract major | F: `ContractValidationError`, field/reason; no expensive work | Shared validation; WS4 steward |
| NaN/Infinity in input/output | F: reject; never emit invalid JSON or fake zeros | Contracts + every WS3 boundary |
| Actions 80 instead of 0.8; outside [0,1] | F: reject, no silent percent conversion/clamping | `test_risk.py` + contracts |
| More than one company; missing/duplicate/out-of-order month | F: reject malformed canonical baseline | Contracts |
| Scope totals mismatch or totals disagree with monthly sums | F: reject; identity tolerance rtol 1e-8, atol 1e-6 tonnes; currency atol 0.01 | Contracts |
| Positive fleet/gas/electricity allocated CO₂ with zero matching activity | F: reject incompatible simulator input, not impute activity | WS2 + WS3 real integration |
| Zero activity with zero allocated emissions | F: valid when remaining schema permits; tests must not reject all zero activity indiscriminately | Contracts + simulator integration |
| Profit negative / baseline profit zero | F: losses valid; relative profit change null at zero, floor probability still evaluated on raw profit | Risk + real simulator |
| Baseline CO₂ zero, target >0 | F: reject ratio target as undefined before trials | `test_risk.py` |
| Baseline CO₂ zero, target 0 | F: reduction ratio null; P(A07): target flag true, other constraints still active | `test_risk.py` |
| 36/60-month P0 request | F: forecast rejects unsupported horizon; benchmark unavailable until annual-slice policy exists. Risk only accepts advertised baseline capability. | WS1 + benchmark test |
| Mutating caller's DataFrame/nested costs | F: original content, dtypes, identities and nested values unchanged | `test_risk.py`, `test_benchmark.py` |
| Serialized dataclasses/DataFrames | F: records, ISO dates, Python bool/int/float and null; round-trip meaning preserved | Shared serializers |
| Synthetic future-dated fixture | F: explicitly synthetic; never labelled reported or used to substantiate source accuracy | Fixture/provenance review |

## Sampling and assumption mapping

| Case | Required behavior | Test oracle |
|---|---|---|
| n=0, negative, float, string, bool, over agreed max | F: positive integer/application limit; P(A09): 1..5,000, reject bool | Parameterized validation before RNG/simulator calls |
| n=1 | F: valid; quantiles equal the one sample; MCSE zero if p=0/1 | Hand sample |
| Invalid seed, negative/nonintegral/bool | P(A05): nonnegative integer, supported by agreed RNG policy; clear field error | Validation |
| Missing action or channel; unsupported distribution | F: invalid spec before sampling; all six actions required | Parameterized uncertainty validation |
| Bounds reversed, nonfinite, negative costs, effect >1 | F: fail before any trial; allowed ranges document meaning | Bounds tests |
| Equal low/high | F: permitted degenerate channel; exact constant values | neutral and nonneutral degenerate examples |
| “Zero uncertainty” uses [0,0] effects | F: zero-width alone is not neutral; P(A04): use all [1,1] for deterministic parity | Compare literal-zero effects vs neutral multipliers |
| Adoption deterministic factor is not 1 | P(A04): reject unsupported initial mapping; don't privately change replacement semantics | Renewable/EV/travel each tested |
| Renewable, EV, travel mapping | F: sampled value replaces default effectiveness; investments still cost money | Inspect captured simulator assumption copies |
| Building/cloud mapping | F: multiply parent's maximum reduction once | Parent 0.3, multiplier 0.9 → 0.27; parent unchanged |
| Supplier mapping | F: same effect multiplier scales maximum reduction and full savings | Parent 0.3/1000, multiplier 0.9 → 0.27/900 |
| Cost mapping | P(A03): per-action capex/fixed monthly opex scaled separately; life/tariffs/avoided rates fixed | Capture nested costs; two unequal multipliers |
| Zero parent coefficient | F: remains zero under multiplier; no invented eligible opportunity | Zero capex / savings / max reduction cases |
| Nested frozen dataclass contains a mutable map | F: no aliasing to parent; sampled objects independent; use frozen nested types/defensive copies | Change retained sample/test-only nested object; parent/other trial unchanged |
| Same seed/spec/version/input | F: same matrix and numerical summaries within pinned environment | Compare numerical fields and stable IDs |
| Different seed, nondegenerate bounds | F: normally different sampled outcomes; do not demand difference for neutral/no-op cases | Test fixed nondegenerate chosen seeds |
| Some actions zero | F: draw all channels anyway; trial alignment preserved | Two configs with different active actions see same captured channel multipliers |
| Strategy order reversed | F: risk outcomes unchanged per strategy; no stateful advancing shared RNG | Evaluate A,B and B,A |
| More trials requested | P(A05): deterministic fixed-width generation preserves existing prefix within same sampler | Matrix 100 rows equals first 100 of 200 |
| Global RNG use | F: no global RNG mutation | Seed/state a separate generator/global test state around call |
| Correlation supplied, invalid/non-PSD matrix | F: no silent interpretation; P(A02): reject all nonempty correlation requests for initial independent sampler | Explicit unsupported test |
| Parent/uncertainty content changes without ID update | F: immutable identities; P(A21): content-hash mismatch caught/keys differ; require revision | Provenance/hash test |
| Sample ID collision or same sample identity reused | F: IDs include parent/uncertainty identity, seed/index; preserve full hashes for audit | Unique sample indices; changed parent/spec/seed changes IDs |

## Monte Carlo runner and statistics

| Case | Required behavior | Test oracle |
|---|---|---|
| Test double ignores sampled assumptions | F: unsuitable uncertainty test double; keep static shape stub out of runner tests | Affine double cost/effect sensitivity test |
| Simulator called wrong number of times | F: one trial call per sampled assumption; don't silently retry | Capturing callable asserts n trial calls; separate deterministic identity call, if needed, disclosed |
| Top-level strategy ID becomes last trial ID | F: original deterministic strategy ID retained; each sample has separate identity | Capture all sample IDs and compare result to deterministic fixture ID |
| All-zero action config, nonneutral uncertainty | F: all trials match baseline CO₂/profit; costs zero | 1,200 tonnes / 1,200,000 GBP / 0 fixture |
| Neutral spec, nonzero strategy | F: all trials match canonical deterministic simulator | 843.744 tonnes / 1,210,940.7847619047 GBP / 186,581.12 GBP |
| EV raises total CO₂ | F: negative reduction allowed; no floor at zero; target probability may be 0 | WS2 reviewed adverse-grid fixture |
| Costs remain despite low effect | F: low effect does not erase configured capex/fixed opex | Real simulator + captured sampling |
| Mean outside p05–p95 | F: valid; test ordered quantiles and mean between sample min/max | Skewed array 99 zeros + one extreme outlier |
| Quantile method unspecified | P(A08): linear interpolation | [10,20,30,40] → p05=11.5, p95=38.5, mean=25 |
| Exact constraint equality | F: boundary is inclusive; P(A07): strict raw values, no solver epsilon | Cost=100, budget=100 true; profit=floor true; reduction=target true |
| Barely violates currency boundary by <0.01 | P(A07): risk flag false even when optimizer tolerance may accept | Budget=100, cost=100.001; keep distinction visible |
| Raw target barely below threshold | P(A07): flag false; normalized solver tolerance not used | reduction=0.199999999, target=0.2 |
| Separate probabilities versus joint | F: joint from row-wise AND; do not multiply marginals | target T,T,F,F; profit T,F,T,F; budget T,T,T,F → .5,.5,.75,joint .25 |
| MCSE formula | F: `sqrt(p*(1-p)/n)` using actual target denominator | p=.5,n=4 → .25 |
| p=0 or 1 | F: valid finite-trial estimate; MCSE=0 does not imply guarantee | all flags false / true; limitation copy |
| Undefined target ratio summary | F: null only for undefined ratios; P(A07) zero/zero convention makes success probability 1 | No NaN and documented branch |
| Bad simulator raises or returns nonfinite/invalid object | P(A06): abort; unexpected errors propagate, no survivor bias or false summary | Counting failing double; assert no result published |
| Samples disabled/enabled | F: summary same; absent samples null; retained columns exact and bool flags preserved | Same seed/config both flags |
| Large sample results/logging | F: no large sample dumps in default results, no secrets/absolute personal paths | Serialization/handoff review |
| Selected-plan latency / whole pool latency | F: measure on declared machine; 1,000 trials <5s is starting target, not portable test assertion | Non-gating benchmark script + recorded profile |

## Frontier and recommendation boundary

| Case | Required behavior | Owner / check |
|---|---|---|
| Frontier empty/infeasible | F: no manufactured recommendation/risk pool | WS2/WS4 integration |
| Frontier ≤20 | F: evaluate all deterministic feasible plans | WS2/WS4 selection-pool test |
| Frontier >20, equivalent objectives | F: endpoints retained, bounded evenly sampled emissions-order pool, full configs/IDs retained; deterministic tie order | WS2/WS4; proposed rounding/dedupe policy documented |
| Risk summary has wrong baseline, constraints, assumptions or config | F: reject stale/mismatched join, not merely matching visible rounded action values | Shared validation/cache integration |
| Some risk results missing/failed | F: exclude from risk-aware pool, show partial coverage | WS2 recommendation |
| All risk absent/failed | F: deterministic recommendation with `risk_status="unavailable"` | WS2 recommendation |
| Conservative/balanced threshold unmet | F: largest joint probability then policy score; `threshold_unmet` visible | Hand-authored pool fixture |
| Constant objective / one strategy | F: normalized constant term 0, stable ID tie-break | WS2 tests |
| Same strategy chosen for several tolerances | F: valid; fixture distinguishing policies for tests, no forced different strategies | WS2/WS4 |
| Threshold-unmet plus partial coverage | F: both facts visible; exact status precedence requires WS2/WS4 agreement and reason metadata | Integration decision, not WS3 private enum |
| Budget/assumptions/uncertainty change | F: invalidate risk keys; tolerance-only change can reuse trial results then rerank | WS4 cache tests |

## Benchmark normalization and comparison

| Case | Required behavior | Test oracle |
|---|---|---|
| kg / tonnes / million tonnes | F: explicit unit conversion; no magnitude guessing | 1,000 kg→1 tonne; 0.001 million tonnes→1,000 tonnes if source supports that unit |
| Revenue in units / thousands / millions | F: explicit denominator scale before FX | 10 source-million GBP→10,000,000 GBP |
| Non-GBP revenue | F: verified direction/date/method; P(A15): GBP per source unit supplied explicitly | 2,000,000 source currency ×.8 →1,600,000 GBP |
| Missing FX, unsupported units/currency | F: unavailable source/invalid row with reason, never assume parity | Normalization test |
| Missing scope3 or only scope1+2 | F: incompatible with all-scope total; no zero fill | Exclusion counts |
| Market-based versus location-based | F: exclude mismatched method; `market_based_demo` not equated to reported `market_based` | Method filter |
| Synthetic and reported mixed | F: separate comparison cohorts; no mixed claimed rank | Config/source consistency test |
| Nonpositive revenue; negative/nonfinite CO₂ | F: exclude/reject by documented row policy; zero emissions with positive revenue is valid | Parameterized cases |
| Positive revenue extremely small | F: intensity must remain finite; P(A16): exclude overflow with reason | Tiny denominator input |
| Supplied intensity disagrees with normalized totals | F: recompute from normalized source values; verify stored canonical identity | Provenance + independent arithmetic |
| Missing/malformed industry | P(A13): exclusion, not guessed mapping | Explicit taxonomy cases |
| Wrong industry or no eligible peers | F: unavailable with reason/count | `test_benchmark.py` |
| 9 peers versus min_peers 10 | F: unavailable after all filters; don't weaken minimum silently | 9/10 boundary |
| min_peers nonpositive/noninteger/bool; negative/noninteger period gap | P(A10/A13): config validation before comparison | Parameterized config tests |
| All peer intensities equal target | F: percentile 50 and better-than 50 | Ten peers at 100 |
| All peers higher / lower than target | F: percentile 0 / 100; better-than 100 / 0 | ten 200 / ten 50 peers with target 100 |
| Values close to tie tolerance | P(A11): disjoint lower/equal/upper groups; counts sum N | c−2tol, c−tol/2, c, c+tol/2, c+2tol |
| Existing fixture | F: N10, intensity100, median105, percentile45, better55 | Direct math from ten known rows |
| Same-company row with different period ID | F: exclude target entity, not only exact company-period ID; P(A12) identity map | target FY2024/FY2025 both excluded |
| Multiple years from one peer | P(A12): latest compatible period per entity so one company gets one vote | Two annual rows for one company |
| Exact/conflicting duplicate peer ID | F: unique canonical IDs; P(A16): reject conflicting duplicates, report source duplicates explicitly | Source normalization cases |
| Leap-year / non-January fiscal year | P(A10): full calendar-year span allowed; no 365-day shortcut | 2024-01-01..2024-12-31; 2025-04-01..2026-03-31 |
| Partial year / 13 months | F: not comparable annual peer; explicit exclusion | Reporting-span tests |
| Period gap exactly24 / greater24 months | F: include/exclude using agreed calendar policy | Boundary fiscal-month test |
| Future reported period at retrieval | P(A10): exclude impossible completed reporting; synthetic future demo remains labelled | Metadata comparison |
| Peer periods vary | F: preserve peer reporting span/coverage metadata; baseline period not substituted as peer period | Serialization/handoff |
| Baseline 36/60 months | F: benchmark unavailable until annual slices specified | Explicit capability reason |
| Optimized strategy passed to baseline-only function | F: contract validation; separate future counterfactual API needed | Signature/type test |
| Benchmarks enter forecast/optimizer | F: no dependency or mutation; comparison only | Import/dataflow review |

## Adapter, provenance and optional failures

| Case | Required behavior | Test oracle / boundary |
|---|---|---|
| Import / offline=True | F: zero requests; no credential or network prerequisite | Import smoke and capturing transport |
| Missing offline snapshot / malformed JSON / wrong version | F: expected typed snapshot failure; unavailable through WS4 mapping, no mock invention | Loader + integration tests |
| HTTP timeouts/connection/429/selected5xx | F: finite retry bound; P(A18): at most3 attempts total, bounded delay including Retry-After | Fake transport/clock, exact attempt assertions |
| 401/403/404 | P(A18): no retries; credential/source unavailable reason, no secret leakage | One attempt |
| Bad content type / HTML / invalid JSON / unexpected payload shape | F: validate response before normalization; no arbitrary execution or source-text instruction following | Mock responses |
| Excessive response / unbounded pagination | P(A18): provider-specific finite payload/row/page limits recorded before enabling; fail on excess | Adapter specification/tests |
| Endpoint/schema changes | F: unavailable or source error; no guessed columns | Missing/moved source-field test |
| Online failure, compatible allowed-age snapshot | F: visible cache source/age; preserve original retrieval time | Benchmark provenance extension A20 |
| Stale / incompatible cached snapshot | P(A19): unavailable for online fallback; explicitly labelled offline replay only if allowed | Fake clock and periods |
| Cached synthetic snapshot for reported source | F: no silent synthetic substitution | Source-kind/identity test |
| Cached result status | F: `ok|unavailable` enum retained; cache/source kind in agreed provenance | Serialization |
| Snapshot modified without ID revision | P(A21): content hash detects drift; treat as invalid/revised source | Snapshot hash test |
| Credential absent; URL/log errors contain credential | F: known provider unavailable; redacted diagnostics, variable names only in docs | Fake sensitive response URL |
| Unexpected programmer exception | F: surface to logs/tests, not generic “no peers” result | Distinct error injection |
| Risk/benchmark unavailable | F: P0 forecast/simulation/optimizer/dashboard still work; capability/panel reason visible | WS4 optional-provider integration |
| Repeated UI rerun | F: slider invokes simulation; heavy risk only explicit/cached; keys include all result dependencies | WS4 tests |

## Minimal independent numerical oracles

```text
Baseline no-op: CO2=1200, profit=1200000, gross cost=0.
Nonzero golden: CO2=843.744, profit=1210940.7847619047,
                capex=164000, gross cost=186581.12.
Neutral Monte Carlo: every trial equals its deterministic strategy.
Quantiles [10,20,30,40]: mean=25, linear p05=11.5, p95=38.5.
Four flags: target=.5, profit=.5, budget=.75, joint=.25;
            target MCSE=sqrt(.5*.5/4)=.25.
Benchmark: 1200/(12000000/1000000)=100 tCO2e/million GBP.
Peers [40,60,80,90,100,110,120,140,160,200]:
        median=105, L=4, E=1, N=10, percentile=45, better=55.
```

Freeze generated **real** risk fixtures only after the implementation passes these independent checks and the canonical simulator parity tests. Keep illustrative shape fixtures separately labelled.
