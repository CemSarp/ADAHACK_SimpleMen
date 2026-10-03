# WS3 C0 boundary note (Prompt 02)

> Background evidence from the completed preparatory audit. Historical inventories and old prompt numbers are not execution instructions. Use `carbonopt-ai-docs/docs/workstreams/03_EXECUTION_PROMPTS_4_HOURS.md`; unresolved proposals here remain draft.


Status: **draft for review.** This file is the only change. Nothing is committed, merged or sent. No WS3 proposal is promoted to "accepted" by this note alone.

| Item | Observed value |
|---|---|
| Date | 2026-10-03 |
| WS3 branch | `workspace3` @ `1950291` (tracks `origin/workspace3`); `carbonopt-ai-docs/docs/handoffs/ws3/` untracked |
| Integration branch | `origin/main` @ `781e91d` = merge of PR #2 (`c76872f`, "feat(ws4): add Streamlit dashboard, provider registry and C0 contracts") |
| Contract / fixture revision | `1.0.0` (`SCHEMA_VERSION`) / `c0-fixtures-r1` (`tests/mocks/fixtures.py`) |
| Authority order | live `main` code > `carbonopt-ai-docs/` shared contracts > WS3 pack (`retired WS3 planning folder/`) |

**States used below**

- **accepted**: the exact value is already binding. Either frozen shared-doc text says it (cited), or the owner of that file merged it on `main`. Any cross-review still outstanding is listed.
- **proposed**: a WS3 recommendation. Named reviewers must approve before code depends on it.
- **deferred**: not needed before the next tasks. The trigger is listed, and the spec-fixed core still applies meanwhile.

## 1. Live evidence since `readiness.md`

`readiness.md` was written before PR #2 merged. Its §1 inventory, §5 table, §6 task-2 blocker and §7 "files another owner must supply" are superseded by this section. The readiness audit itself is left unedited as a dated record.

### 1.1 What `main` now gives WS3

| Item | Location (`origin/main@781e91d`) | Consequence for WS3 |
|---|---|---|
| `RiskConfig`, `RiskResult`, `BenchmarkResult`, `RISK_SUMMARY_FIELDS`, `RISK_SAMPLE_COLUMNS`, `RISK_STATUSES`, `BENCHMARK_STATUSES=("ok","unavailable")` | `src/contracts/types.py:103-133, 169, 238-243, 364-398` | Use them; never redefine. `BenchmarkResult` numeric/source fields are already nullable. |
| Sample frame spec `trial_id: int` | `src/contracts/serialization.py:111` | `trial_id` is the 0-based trial index (adopted in A21) |
| `MAX_RISK_SIMULATIONS = 5000`, `validate_risk_config` | `src/contracts/validation.py:65, 296-304` | X13 resolved; see A09 |
| `validate_constraints_for_baseline` | `validation.py:276-284` | Reuse before any trial (zero CO₂ + positive target) |
| `CURRENCY_ATOL_GBP=0.01`, `RATIO_ATOL=1e-8`, `SOLVER_FEASIBILITY_TOL=1e-8` | `validation.py:58-63` | Basis of the A07 recommendation |
| `compute_strategy_id`, `canonical_hash` | `src/contracts/identity.py:32-48` | `RiskResult.strategy_id` comes from the shared helper, not a simulator call |
| `RiskError(ProviderError)` | `src/contracts/errors.py:55` | Typed trial failure (A06) |
| `RiskProvider.evaluate(...)` has **no** `uncertainty` argument; provider exposes `uncertainty_id` | `src/contracts/protocols.py:97-113` | WS3's provider binds `UncertaintySpec`; the fixed domain signature is unchanged |
| `BenchmarkProvider.benchmark(baseline)`, docstring "failures return status=unavailable" | `protocols.py:126-132` | Conversion happens inside WS3's provider (A17, N1) |
| Real factories `src.risk.provider.create_risk_provider()`, `src.benchmarking.provider.create_benchmark_provider()` | `src/integration/real_providers.py:152-154` | Proposed by WS4; WS3 review in §9 |
| `select_risk_pool` (≤20, endpoints + even spacing); risk/benchmark stages catch **only** `ProviderError`; `RiskResult.strategy_id` must equal the Pareto ID or `ContractValidationError` aborts the run | `src/integration/pipeline.py:36, 56-101, 156-164` | Drives A06/A17 wrapping rules |
| Analysis cache key hashes `uncertainty_id` (not content) + every `ProviderInfo` | `src/integration/cache_keys.py:52-66` | Content must enter `ProviderInfo.version` (A21) |
| Six-action affine `BehavioralMockSimulator` | `tests/mocks/behavioral.py:75-164` | Reusable risk test double (§8) |
| `FixtureRiskProvider.uncertainty_id = "illustrative-risk-v1"` | `tests/mocks/fixture_providers.py:166-167` | Shape-only ID (X10) |
| Pins: numpy 2.4.6, pandas 3.0.6, plotly 7.1.0, streamlit 1.65.0, pytest 9.1.1; `requests`/`scipy` commented out in `requirements-p1.txt` | `requirements*.txt` | A24 has real pins (WS4 says WS1/WS2 review pending) |

**Still missing for WS3:**

- Shared types: `UncertaintySpec`, `BenchmarkSource`, `BenchmarkConfig`, `BenchmarkDataset` (with validators and serializers).
- A benchmark-source error class.
- Files: `config/uncertainty.json`, `data/benchmark.csv` and its metadata.
- WS2's `simulate_strategy` (C2).

### 1.2 Checks actually run

The merged suite ran on an exported copy of `main`. Your checkout, branches and global packages were not touched. The venv reuses the `adahack` interpreter (Python 3.11.16, numpy 2.4.6, pandas 3.0.6, plotly 7.1.0) and adds the pinned `pytest`/`streamlit`.

```sh
git archive origin/main | tar -x -C <scratch>/main781
<adahack-python> -m venv --system-site-packages <scratch>/venv
<scratch>/venv/bin/python -m pip install -r <scratch>/main781/requirements.txt
cd <scratch>/main781 && <scratch>/venv/bin/python -m pytest -q -p no:cacheprovider
# -> 102 passed in 6.45s
```

A scratch script (not committed) checked the following against the merged code, with numpy 2.4.6:

| Check | Result |
|---|---|
| `default_rng(42).random((100,18)) == default_rng(42).random((200,18))[:100]` | True (prefix property); bit generator `PCG64` |
| `1.0 + (1.0-1.0)*u == 1.0` for 10,000 draws | True (degenerate bounds are exact) |
| `np.quantile([10,20,30,40],[.05,.95],method="linear")`, mean | `[11.5, 38.5]`, `25.0` |
| `validate_risk_config(RiskConfig(seed=-1))` | passes, but `np.random.default_rng(-1)` raises `ValueError: expected non-negative integer` (N3) |
| `canonical_hash(df1) == canonical_hash(df2)` for two 100-row frames differing at row 50 | **True**: `default=str` hashes the truncated repr (N2) |
| `compute_strategy_id("baseline-demo-v1", action_config, "demo-actions-v1", "1.0.0")` | `strategy-8be15857fffc57f6` (matches fixture) |
| WS4 behavioral mock responds to: renewable/travel effectiveness, renewable capex | yes |
| ... to building/cloud max reduction, supplier reduction + savings, fixed opex ×1.1 | **no** (X15 confirmed) |
| Behavioral mock, `x_r=.5, x_ev=.4`, effects `.9/.8` | CO₂ `1053.6`, cost `110000.0`, profit `1198900.0` (equals the Prompt 04 oracle) |
| Neutral case (identical trial values = nonzero golden), n = 1/3/1000/5000 | quantiles bit-exact for every n; the mean is not always bit-exact (n=1000 profit mean off by `4.66e-10` GBP) |
| `git merge-tree --write-tree workspace3 origin/main` | one conflict: `README.md` |

### 1.3 Contradiction register update

| # | Status now | Resolution path |
|---|---|---|
| X1 stale README | `main` README now says Streamlit + venv, but still carries the conda section and the stray `deneme1`. The `workspace3` README hunk conflicts with `main`. | Take `main`'s README (WS4-owned) at merge; drop the WS3 hunk |
| X2 "copy docs to root" | Open: `carbonopt-ai-docs/README.md:5` | A01 doc fix by WS4 |
| X3 two dependency workflows | Partly resolved: pinned `requirements*.txt` + CI; `environment.yml` is still unpinned | A01 |
| X4 baseline vs selected-strategy benchmark | Resolved by contract authority | A23 (accepted) |
| X5 cached status | → A20 | proposed |
| X6 entity key | → A12 | proposed |
| X7 replace vs nondefault parents | → A04 (multiplicative recommendation) | proposed |
| X8 which opex varies | → A03 | proposed |
| X9 "raw" boundary meaning | → A07 (recommendation changed, see A07) | proposed |
| X10 uncertainty schema / ID | → A02; `illustrative-risk-v1` stays a shape-only ID | proposed |
| X11 `risk_summary.json` unreachable | Unchanged; copied unchanged into `c0-fixtures-r1` and used only by `FixtureRiskProvider` (shape stub) | Neutral/real fixtures later |
| X12 completion rule vs synthetic dates | → A10 (reported rows only) | proposed |
| X13 trial-limit location | **Resolved**: shared validator constant | A09 (accepted) |
| X14 branch naming | Unchanged; WS4 followed `feat/ws4-*`; WS3 stays on `workspace3` (your choice) | — |
| X15 mock coverage | Confirmed on WS4's six-action mock | §8 capture tests |
| **N1** | `BenchmarkProvider` docstring puts failure → `unavailable` in the provider. Prompt 00 says "Expected loader errors are mapped by WS4". | A17 |
| **N2** | `canonical_hash(..., default=str)` silently hashes object reprs (verified collision) | A21 |
| **N3** | `validate_risk_config` accepts negative seeds that NumPy rejects | §6.3 |
| **N4** | Pipeline catches only `ProviderError` for optional stages; an unwrapped `ContractValidationError` from a risk trial aborts the whole P0 analysis | A06, A17 |
| **N5** | Cache keys see `uncertainty_id`, not spec content | A21 provider-version recipe |
| **N6** | A `ContractValidationError` raised by an optional real factory is not mapped to `ProviderUnavailable`, so real mode fails to start | §6.4 |
| **N7** | `benchmark_from_dict` requires every field (`_require`), so new optional fields would break old fixtures unless decoded with `.get` | §6.2 |
| **N8** | `_plain` turns NaN into `null` (`serialization.py:140`) | WS3 validates every result before returning it |

## 2. Decision summary

"Blocks" names the first prompt that needs the decision settled.

| ID | Topic | State | Recommended value (detail in §3) | Blocks | Reviewers |
|---|---|---|---|---|---|
| A01 | Root layout / dependency workflow | **accepted** (layout) / proposed (single workflow) | Runtime at Git root; docs stay nested; `requirements*.txt` is the only pinned source | — | WS4 (owner) |
| A02 | `UncertaintySpec` JSON/type | proposed | §7.1 JSON; strict validation; IDs `illustrative-action-uncertainty-v1` and `neutral-action-uncertainty-v1` | P03 | WS4, WS2 |
| A03 | Which cost coefficients vary | proposed | `capex_at_full_gbp`, `monthly_opex_at_full_gbp` only, per action | P06 | WS2 |
| A04 | Neutral spec; adoption factors | proposed (changed) | Neutral = all 18 bounds `[1,1]`; all six effect multipliers **multiply** the parent coefficient | P06 | WS2 |
| A05 | Channel order / algorithm | proposed | `uniform-action-major-v1`: `rng.random((n,18))`, column `3*action+channel` | P03 (names), P05 | WS3 (+WS4 note) |
| A06 | One trial fails | proposed | Validate first; invalid trial → `RiskError`; never drop or resample | P07 | WS4 |
| A07 | Flag boundaries vs epsilons | proposed (changed) | Raw totals with the raw-check tolerances 0.01 GBP / 1e-8 ratio; no solver epsilon | P08 | WS2, WS4 |
| A08 | Quantiles / retention | proposed | `np.quantile(..., method="linear")`, float64 | P08 | WS4 |
| A09 | Trial/pool budgets | **accepted** (limits) / deferred (runtime) | 1,000 default; 5,000 max in the shared validator; pool ≤20 | P11 | WS4 (merged); WS2 |
| A10 | Annual period / gap | proposed | Month-start + 12 full months; absolute month-ordinal gap ≤24; completion rule for reported rows only | P12 | WS4, WS1 |
| A11 | Tie tolerance | proposed | absolute `1e-8`, rtol 0, disjoint L/E/G | P13 | WS4 |
| A12 | Entity identity | proposed | Optional `entity_id` peer column + `BenchmarkConfig.exclude_entity_ids` | P03 (shape) | WS4 |
| A13 | Industry / cohort | proposed | Explicit mapping; one source and one `is_synthetic` per dataset | P12 | WS4 |
| A14 | Real provider | deferred | P1 ships a labelled synthetic snapshot or `unavailable` | P14 | WS1/2/4 |
| A15 | FX | deferred | Metadata fields reserved now; policy when a non-GBP source qualifies | P12 (non-GBP only) | WS4 |
| A16 | Malformed / partial rows | proposed | Dataset-level fail vs row exclusion with closed reason codes | P12 | WS4 |
| A17 | Loader failure → result | proposed | `BenchmarkSourceError(ProviderError)`; WS3 provider returns `unavailable` | P03 (class), P15 | WS4 |
| A18 | HTTP policy | deferred | Spec core fixed; details for the verified provider only | P16 | WS4 |
| A19 | Cache / offline | deferred | Fallback only to the committed snapshot, ≤30 days for online fallback | P17 | WS4 |
| A20 | Source-kind/age/exclusion metadata | proposed (changed) | Additive optional `BenchmarkResult` fields; `source_kind ∈ {live, snapshot, cache}` | P03 | WS4 |
| A21 | Hashes, sample IDs, cache inputs | proposed | Hash serialized dicts only; `sample-<16hex>`; content in `ProviderInfo.version` | P03, P06 | WS4, WS2 |
| A22 | Imports / error exposure | **accepted** (spec-derived) | Contracts + numpy/pandas only; `requests` only on the HTTP path | all | D14 |
| A23 | Baseline-only / >12 months | **accepted** (baseline-only) / deferred (counterfactual) | 12-month baseline only; other horizons → `unavailable` | P13 | D14 |
| A24 | Reproducibility | proposed | Within pinned runtime + sampler version; record numpy/bit generator | P09 | WS4 |

Frozen and **not reopened** anywhere in this note:

- every public signature in `SHARED_CONTRACTS.md` §3;
- `RISK_STATUSES` (`not_requested`/`unavailable`/`partial`/`evaluated`/`threshold_unmet`) and `BENCHMARK_STATUSES` (`ok`/`unavailable`);
- the 13 summary field names and the 7 sample columns;
- the six-field `Provenance` object.

No `RiskResult` status and no `cached` benchmark status are proposed.

## 3. Decision records (A01–A24)

### A01 Application root and dependency workflow

**State:** accepted (layout); proposed (single dependency workflow)

**Value**

- `src/`, `tests/`, `config/`, `data/`, `app.py`, `pyproject.toml` and `requirements*.txt` live at the Git root.
- The authoritative docs stay nested in `carbonopt-ai-docs/` and are cited by repo-relative path.
- WS3 notes live in `carbonopt-ai-docs/docs/handoffs/ws3/`.

**Evidence:** PR #2 merged this layout into `main` (`781e91d`). WS4 owns the layout (`IMPLEMENTATION_PLAN.md:48`). The `types.py` docstring says the docs are "currently under carbonopt-ai-docs/".

**Open part:** `main`'s README documents both venv + `requirements.txt` and the unpinned conda `environment.yml`.

- Recommendation: `requirements*.txt` is the only pinned source. `environment.yml` is either removed or reduced to `python=3.11` + `pip: [-r requirements.txt]`.
- `carbonopt-ai-docs/README.md:5` ("Copy the contents of this folder to the application repository root") should be reworded by WS4 (X2).
- WS3 adds a `requests` pin to `requirements-p1.txt` only through a WS4-reviewed PR, and only when HTTP is enabled (A18).

**Record:** reviewer WS4 (owner, merged); WS1/WS2/WS3 concurrence pending (WS4 handoff: "no approvals have occurred"). Config: contract `1.0.0`. Fixtures: `c0-fixtures-r1`. Effective commit `781e91d`.

### A02 `UncertaintySpec` JSON and type

**State:** proposed

**Value:** the JSON in §7.1 and the type in §6.1. Validation, all before any random draw, raising `ContractValidationError(field, reason)`:

- **Actions and channels:** `actions` keys are exactly `ACTION_NAMES`. Each action has exactly the channels `effectiveness`, `capex`, `fixed_opex`. Unknown keys fail.
- **Bounds:**
  - `distribution == "uniform"`;
  - `low` and `high` are finite real numbers (bool rejected) with `low <= high`;
  - effectiveness bounds lie within `[0, 1]`;
  - capex/fixed-opex bounds are `>= 0`;
  - bounds are normalised to float before hashing (`1` and `1.0` must hash equally).
- **Method:** `sampling_method == "independent_uniform"`, `sampler_version == "uniform-action-major-v1"`, `correlation_groups == []`. A non-empty correlation list is rejected as unsupported; it is never silently treated as independent (`RISK_AND_BENCHMARK_SPEC.md:38`).
- **Identity:** `uncertainty_id`, `version` and `calibration_note` are non-empty. Any content change needs a new ID or version, detected by hash (A21).

**IDs and files:**

- `illustrative-action-uncertainty-v1` → `config/uncertainty.json` (WS3).
- `neutral-action-uncertainty-v1` → `tests/fixtures/v1/uncertainty_neutral.json` (WS3 content, in WS4's stewarded fixture directory).
- `illustrative-risk-v1` (used by `risk_summary.json` and `FixtureRiskProvider`) has no spec file and stays a shape-only ID (X10).

**Evidence:**

- `SHARED_CONTRACTS.md:59`: the type only "contains distributions and correlation metadata".
- `RISK_AND_BENCHMARK_SPEC.md:9`: field list and initial policy.

**Consequence:** no generic distribution registry. A new distribution or correlation support means a new `sampler_version` plus an additive contract change.

**Reviewers:** WS4 (type, serializer, validator); WS2 (channel → assumption-field mapping).

### A03 Which cost coefficients vary

**State:** proposed (strong textual support)

**Value**

- **Sampled, per action, independently:** `capex` scales `costs[a].capex_at_full_gbp`; `fixed_opex` scales `costs[a].monthly_opex_at_full_gbp`.
- **Never sampled:**
  - `asset_life_months`;
  - `renewable_premium_gbp_per_kwh`;
  - `electricity_gbp_per_kwh`, both as EV load price and as avoided rate;
  - `gas_gbp_per_kwh`, `ice_fuel_gbp_per_km`, `travel_gbp_per_km`, `cloud_gbp_per_hour`;
  - `grid_tco2e_per_kwh`, `ev_kwh_per_km`;
  - all scope partitions.

**Evidence**

- `RISK_AND_BENCHMARK_SPEC.md:22`: "Capex and fixed opex still use the implementation config `x`, multiplied by sampled cost coefficients".
- `:9`: "per-action capex/opex multiplier bounds".
- `ACTION_MODEL.md:100`: incremental opex = fixed action opex + EV electricity + renewable premium. Only the first is a per-action coefficient.

**Consequence**

- Depreciation and profit respond to the capex multiplier through WS2's engine. Risk never recomputes either.
- Renewable-premium and EV-electricity costs stay deterministic, so cost uncertainty for those two actions is understated. This is a stated limitation.
- Widening the scope means a new `sampler_version` and a WS2 review.

**Reviewers:** WS2.

### A04 Neutral uncertainty and adoption factors

**State:** proposed. This changes the A04 text in `retired architecture register` and needs a WS2 decision.

**Neutral.** All 18 bounds are `[1.0, 1.0]`. Every sampled assumption is then numerically identical to the parent, so each trial reproduces the deterministic simulation. Effects of `[0, 0]` are **not** neutral: they zero the effects while costs remain.

**Recommended mapping:** every effect multiplier `m` multiplies the parent coefficient.

| Action | Sampled field(s) |
|---|---|
| renewable | `renewable_effectiveness = parent × m_r` |
| EV | `ev_effectiveness = parent × m_ev` |
| travel | `travel_effectiveness = parent × m_t` |
| building | `building_max_reduction = parent × m_b` |
| cloud | `cloud_max_reduction = parent × m_c` |
| supplier | `supplier_max_reduction = parent × m_s` **and** `supplier_monthly_savings_at_full_gbp = parent × m_s` |

A zero parent stays zero. Products stay within `[0, 1]`.

**Why multiply rather than replace**

- With the shipped parents (all adoption factors `1.0`, `ACTION_MODEL.md:22` default), multiplying gives exactly the same numbers as "sampled multipliers replace their default effectiveness values" (`RISK_AND_BENCHMARK_SPEC.md:24`).
- For a nondefault parent (say a calibrated 0.9), literal replacement would draw from `[0.85, 1.0]`. That would mostly *raise* effectiveness above the calibrated value, and neutral `[1, 1]` would no longer reproduce the deterministic result.
- Multiplying keeps neutral parity for every valid parent.

**Alternative** (the A04 text as written): replace for renewable/EV/travel and reject any parent factor ≠ 1.0 with `ContractValidationError` before sampling. It gives identical numbers on every current fixture and fails closed for nondefault parents.

**Test impact if the recommendation is accepted:** plan Task 2's "nondefault adoption mapping rejection" becomes "parent 0.9 × multiplier 0.9 → 0.81". The building `.3 × .9 = .27` and supplier `.3/1000 × .9 = .27/900` oracles are unchanged.

**Reviewers:** WS2 (owns action semantics), WS3.

### A05 Channel order, algorithm and reuse

**State:** proposed (WS3-owned sampler; document before fixtures)

**Value:** `sampler_version = "uniform-action-major-v1"` means:

1. `U = numpy.random.default_rng(seed).random((n, 18))`: float64, C order, PCG64.
2. Column `j = 3*action_index + channel_index`. Action order is `ACTION_NAMES`; channel order is `(effectiveness, capex, fixed_opex)`.
3. `multiplier = low + (high - low) * U[:, j]`. A degenerate `low == high` gives exactly `low`.
4. Every channel is drawn for every trial, whatever the action config or bounds.
5. The matrix depends only on `(seed, n, sampler_version)`. It never depends on strategy, config or strategy ID.
6. The first `k` rows are identical for any `n >= k` (verified).
7. `seed` is an `int >= 0`; bool is rejected (validator delta in §6.3).

**Evidence:** `RISK_AND_BENCHMARK_SPEC.md:28` (canonical action order, common random numbers, no per-strategy seeds); §1.2 checks.

**Illustrative first row** (seed 42, §7.1 bounds, numpy 2.4.6), to be frozen as a fixture only after acceptance:

```text
[0.966093, 0.987776, 1.07172, 0.954605, 0.918835, 1.095124, 0.964171, 1.057213, 0.925623,
 0.917558, 0.97416, 1.085353, 0.94658, 1.064552, 0.988683, 0.884086, 1.010917, 0.912763]
```

**Consequence:** any change to the layout, the draw call or the A03/A04 mapping requires a new `sampler_version` and revised fixtures.

### A06 Failure of one Monte Carlo trial

**State:** proposed

**Value**

1. **Before the first simulator call**, validate everything:
   - `validate_baseline`, `validate_action_config`, `validate_constraints_for_baseline`, `validate_assumptions`;
   - `validate_risk_config` (with seed ≥ 0) and `validate_uncertainty_spec`;
   - the A04 rule.

   These raise `ContractValidationError`. They are caller or config errors, and the pipeline deliberately lets them propagate.
2. **Each trial** makes one simulator call, then `validate_simulation_result(result, baseline)`, then checks `result.config == action_config`.
3. **An invalid trial output** raises `RiskError(f"trial {i} ({sample_id}): {field}: {reason}") from err`. `RiskError` is a `ProviderError`, so the pipeline excludes that strategy and warns "Risk evaluated for k of n" (`pipeline.py:96-100`).
4. **A simulator `ProviderError`** (for example `SimulationError`) is re-raised unchanged with `err.add_note(f"risk trial {i}")`.
5. **Any other exception** propagates unchanged. It is a programming error and stays visible.
6. A trial is never dropped, resampled or retried. A summary is never published over fewer than `n` trials, and no partial-result status exists.

**Why wrap:** an unwrapped `ContractValidationError` from a trial would abort the whole P0 analysis whenever risk is enabled (N4).

**Evidence:** `SHARED_CONTRACTS.md:225`; `RISK_AND_BENCHMARK_SPEC.md:44` ("A missing/failed risk result is excluded"); `errors.py:55`.

**Consequence:** one bad trial removes only that strategy from the pool. WS2's policy reports `partial` or `unavailable`.

**Reviewers:** WS4 (orchestration mapping).

### A07 Probability boundaries versus solver epsilon

**State:** proposed. This changes the recommendation in `retired architecture register` A07 and the Prompt 00 brief, and needs WS2 + WS3 + WS4.

**Recommended: option T**, raw totals with the documented raw-check tolerances. Values come from each trial's `SimulationResult.metrics`; risk never recomputes a ratio.

```text
budget_met = total_cost_gbp        <= budget_gbp              + CURRENCY_ATOL_GBP   (0.01)
profit_met = total_profit_gbp      >= min_total_profit_gbp    - CURRENCY_ATOL_GBP   (0.01)
target_met = co2_reduction_ratio   >= min_co2_reduction_ratio - RATIO_ATOL          (1e-8)
             baseline CO2 == 0 and target == 0 -> True;  baseline 0 and target > 0 -> rejected before trials
joint_met  = budget_met AND profit_met AND target_met   (row-wise; never a product of marginals)
MCSE       = sqrt(p*(1-p)/n), p = target_probability
```

The solver's normalized `SOLVER_FEASIBILITY_TOL` on `g_*` is **not** used.

**Why**

- `ACTION_MODEL.md:143` defines the raw check itself as "raw totals with currency tolerance `0.01` and reduction tolerance `1e-8`".
- `main` exposes these as shared constants (`validation.py:61-62`), and WS4's mock evaluator applies them to raw violations.
- `DATA_SCHEMAS.md:21` describes the epsilon as "not permission to exceed budget materially".
- Under T, a neutral spec gives joint probability `1.0` for every validated feasible Pareto point, and last-bit floating-point noise at an exact boundary cannot flip a flag.

**Option S** (strict, as written in `retired architecture register`): `cost <= budget`, `profit >= floor`, `ratio >= target`, with no tolerance. Consequences:

- A frontier point WS2 accepts at `cost = budget + 0.004` (NSGA-II tends to converge onto an active budget constraint) gets `budget_probability = 0` even under the neutral spec.
- Exact boundaries can flip on summation noise.

**retired edge-case matrix rows that change under T**

| Case | Under S | Under T |
|---|---|---|
| "Barely violates currency boundary by <0.01" | false | true |
| "reduction 0.199999999 vs 0.2" (difference 1e-9 < 1e-8) | false | true |

Unambiguous "false" cases: `cost = budget + 0.02`; `ratio = target - 2e-8`. Equality cases are true under both options.

**Reviewers:** WS2 (owns the raw check), WS4 (UI copy), WS3.

### A08 Quantile convention and retention

**State:** proposed

**Value**

- Trial totals are held as float64 arrays.
- `mean = float(np.mean(x))`.
- `p05, p95 = np.quantile(x, [0.05, 0.95], method="linear")`. The method is written explicitly even though it is NumPy's default.
- Cost mean and p95 use the same rule. Probabilities are `float(np.mean(flags))`.
- During a run only the three totals and three flags are kept. The samples frame is built only when `retain_samples=True`. Summary values are identical either way.

**Oracles:** `[10, 20, 30, 40]` → `11.5 / 38.5 / 25.0`.

**Neutral parity tests:**

- per-trial totals compared with exact equality;
- quantiles compared with exact equality;
- means compared with `rel_tol=1e-12`, because the n=1000 profit mean is off by `4.66e-10` GBP (§1.2).

**Reviewers:** WS4 (labels), WS3.

### A09 Runtime, trial and frontier budgets

**State:** accepted (limits); deferred (runtime tuning)

**Accepted**

- Default `n = 1000`: `RiskConfig` default (`types.py:240-241`); `RISK_AND_BENCHMARK_SPEC.md:34`.
- Maximum `5000`, enforced in the shared validator (`validation.py:65, 300-301`), matching `RISK_AND_BENCHMARK_SPEC.md:26`: "impose an application limit (default 5,000)".
- Pool ≤ 20 with both endpoints: `RISK_AND_BENCHMARK_SPEC.md:42`; implemented in `pipeline.py:36, 56-65`.

**Deferred** until WS2's C2: measure the 1,000-trial and pool runtimes.

**Flag now:** the pool is 20 × n sequential simulator calls. At the ≤5 s per 1,000-trial-plan target (`IMPLEMENTATION_PLAN.md:162`), a full pool can take about 100 s. After measurement WS4/WS2 can choose between a smaller pool `n` with 1,000 trials for the selected plan, or an explicit "evaluate risk" action plus a cache. Nothing is chosen here.

**Record:** reviewer WS4 (merged); WS2/WS3 review of `select_risk_pool` is pending (§9). Contract `1.0.0`; fixtures `c0-fixtures-r1`; effective commit `781e91d`.

### A10 Benchmark period and date rules

**State:** proposed

**Value**

- **Annual period:** `period_start` is the first day of a month, and `period_end` is the last day of the 12th month (for example `2024-01-01..2024-12-31` or `2025-04-01..2026-03-31`). This is leap-safe. Other spans (52/53-week years, mid-month starts, 13 months) are excluded as `non_annual_period`, with a visible count.
- **Gap:** compute `|ordinal(forecast_end) - ordinal(peer_end)|` with `ordinal = 12*year + month`. A peer is compatible when the gap is `<= max_period_end_gap_months` (24, inclusive). `forecast_end` is the last baseline month.
- **Completion:** rows with `is_synthetic=false` need `period_end < date(retrieved_at)`; otherwise they are excluded as `period_not_completed`. Synthetic rows are exempt, which fixes X12, and they remain labelled.

**Oracle:** fixture gap = 12 months (2027-12 vs 2026-12), so the peers are included.

**Reviewers:** WS4, WS1 (baseline dates).

### A11 Percentile tie tolerance

**State:** proposed

**Value:** module constant `INTENSITY_TIE_ATOL = 1e-8` tCO₂e/£m, rtol 0, not a config field.

```text
E = |p - c| <= tol
L = p < c - tol
G = p > c + tol          (L + E + G = N)
percentile = 100*(L + 0.5*E)/N
better_than_pct = 100 - percentile
industry_median = np.median(compatible intensities)   (no tolerance)
```

**Oracles:**

- Fixture: L4 E1 N10 → `45 / 55`.
- Boundary peers `{c-2tol, c-tol/2, c, c+tol/2, c+2tol}` → `L1 E3 G1`.

### A12 Company identity across periods

**State:** proposed. It changes the dataset shape, so WS4 must review.

**Value**

- Add an optional canonical peer column `entity_id` (string). It is required when the dataset has `is_synthetic=false`. In a synthetic dataset without it, each `peer_id` is its own entity.
- **Target exclusion:** drop rows whose `entity_id` is in `{baseline.company_id} ∪ config.exclude_entity_ids`, by exact string equality (no substring or case folding). Reason: `target_entity`.
- **One vote per entity:** after the compatibility filters, keep the latest `period_end` per entity; the others are excluded as `superseded_entity_period`.
- Two compatible rows with the same entity and the same `period_end` make the dataset invalid (A16).

**Alternative:** a `peer_id → entity_id` map in dataset metadata. It avoids a column change, but every consumer must join it and it is harder to validate.

**Evidence:**

- `RISK_AND_BENCHMARK_SPEC.md:66`: `peer_id` is a "company-period ID".
- `:98`: exclude the same company and keep a count.

**Oracle:** the fixture with `exclude_entity_ids=("synthetic-peer-05",)` leaves 9 peers, so the result is `unavailable` (§7.4a).

### A13 Industry taxonomy and comparison population

**State:** proposed

**Value**

- `BenchmarkConfig.industry` is a canonical lowercase category (fixture: `technology`).
- Source codes map through an explicit `industry_mapping` in the source metadata during normalization. Unmapped codes are excluded as `industry_unmapped`; mismatches are excluded as `industry_mismatch`.
- **Dataset invariant:** exactly one `source_id` and one `is_synthetic` value across all rows; otherwise `ContractValidationError`. Synthetic and reported peers therefore never mix, and `BenchmarkResult.is_synthetic` is unambiguous.
- No global taxonomy in P1.

### A14 Real provider, licence and minimum coverage

**State:** deferred to Prompt 14. **Trigger:** any non-synthetic claim.

P1 ships the labelled synthetic snapshot or an `unavailable` external capability. Qualification criteria stay as written in `retired architecture register`: at least 10 eligible *entities*, scope1+2+3, a compatible scope2 method, annual revenue/FX, completed periods and usage rights. Real `market_based` peers are never relabelled as `market_based_demo`.

### A15 FX conversion

**State:** deferred until a non-GBP source qualifies. The metadata fields are reserved now (§6.1):

- `fx_method`: `not_required` / `annual_average` / `provider_reported_gbp`
- `fx_rate_gbp_per_unit`, `fx_rate_date`, `fx_source`: all null when `not_required`

When FX is used, `revenue_gbp = revenue_source × fx_rate_gbp_per_unit`, and no HTTP call happens inside normalization or ranking.

### A16 Duplicate, malformed and partially usable rows

**State:** proposed (blocks Prompt 12, not Prompt 03)

**Value**

- **Whole dataset fails** with `BenchmarkSourceError("snapshot_invalid")` when:
  - a required column is missing or a type cannot be parsed;
  - the schema major version is not 1;
  - a `peer_id` is duplicated with conflicting values;
  - the content hash does not match (A21).
- **Rows are excluded during normalization**, with closed reason codes recorded in `metadata.exclusions`: `duplicate_row` (exact duplicate), `missing_scope`, `nonpositive_revenue`, `invalid_emissions`, `non_annual_period`, `period_not_completed`, `industry_unmapped`, `unsupported_unit`, `missing_fx`, `intensity_nonfinite`.
- **Comparison-stage exclusions** happen in `benchmark_company`: `industry_mismatch`, `scope_mismatch`, `method_mismatch`, `period_gap`, `target_entity`, `superseded_entity_period`.
- A canonical `BenchmarkDataset` holding an invalid row is malformed: its validator raises.

### A17 Source-loading failures and result conversion

**State:** proposed. It resolves N1 differently from the Prompt 00 brief and needs WS4.

**Value**

- **New error class.** Add `BenchmarkSourceError(ProviderError)` to `src/contracts/errors.py`, with a `reason_code` attribute. Codes: `offline_snapshot_missing`, `snapshot_invalid`, `snapshot_hash_mismatch`, `snapshot_stale`, `credentials_missing`, `transport_failed`, `http_status`, `response_invalid`.
- **Loader signature unchanged.** `load_benchmark_data` returns `BenchmarkDataset` or raises that error for expected failures.
- **Conversion in WS3's provider.** `src/benchmarking/provider.py` catches **only** `BenchmarkSourceError` and returns `BenchmarkResult(status="unavailable", reason="source_unavailable:<code>: <redacted message>")`, as the merged protocol docstring says (`protocols.py:128`). WS4's `except ProviderError` (`pipeline.py:163`) stays as a backstop.
- **Comparison outcomes are results, not errors.** `benchmark_company` returns `unavailable` (never raises) for:
  - incompatibility, such as a baseline `scope2_method` that differs from the config;
  - too few peers;
  - an unsupported horizon.
- **Invalid config.** Invalid `BenchmarkSource`/`BenchmarkConfig` values raise `ContractValidationError` when the provider is created. WS4 maps that to a disabled capability (§6.4, N6).
- **Programming errors propagate.**

**Why the provider, not WS4:** the merged protocol already defines it that way, and the code sits in a WS3-owned file, so WS4 never assembles domain fields such as company intensity or periods.

### A18 HTTP transport policy

**State:** deferred to Prompt 16, and only for a verified provider. The spec core is fixed (`RISK_AND_BENCHMARK_SPEC.md:104`).

**Proposed details**

- **Requests:** GET-only to the configured endpoint, through an injected `requests.Session`.
- **Timeouts:** `timeout=(min(3.05, t), t)` with `t = timeout_seconds`.
- **Retries:** at most 3 attempts in total, only for connect/read timeouts, `ConnectionError`, 429, 502, 503 and 504.
- **Backoff:** `min(0.5 × 2^k, 4.0)` s. `Retry-After` is honoured only when ≤ 4.0 s; otherwise retrying stops.
- **No retry** for 401, 403, 404 or any other 4xx.
- **Response validation:** JSON content type, ≤ 5 MB, ≤ 10,000 rows.
- **Credentials:** read only from the environment variable names given in `BenchmarkSource`; never placed in URLs, logs or results.
- **Import:** `requests` is imported only inside the HTTP code path.

### A19 Cache age, snapshot selection and offline semantics

**State:** deferred to Prompt 17

**Proposed**

- **No runtime cache writes in P1.** The "cache" is the committed normalized snapshot of the **same** `source_id`.
- **Online fallback.** After a live failure, the snapshot is used only if:
  - its metadata is compatible and its content hash verifies;
  - `loaded_at - retrieved_at <= cache_max_age_days` (proposed 30).

  It is then labelled `source_kind="cache"` with `source_age_days` set. Otherwise the result is `unavailable`.
- **Offline.** `offline=True` uses the snapshot at any age, labelled `snapshot`, with the age still reported.
- A synthetic snapshot never substitutes for a reported source: `source_id` and `is_synthetic` must match.
- The clock is injected for tests.

### A20 Where source-kind, age and exclusion metadata lives

**State:** proposed. Changed from the original A20: `synthetic` is dropped from `source_kind`.

**Value:** additive optional `BenchmarkResult` fields (§6.2):

| Field | Meaning |
|---|---|
| `source_kind` | `live` / `snapshot` / `cache` |
| `source_age_days` | Age of the data when loaded |
| `peer_period_start`, `peer_period_end` | Span of the compatible peer reporting periods |
| `exclusion_counts` | Reason code → count, covering normalization and comparison exclusions |

- Status stays `ok`/`unavailable`, and the six provenance fields are unchanged.
- `source_kind` is orthogonal to the existing `is_synthetic`, so a cached synthetic snapshot stays unambiguous.
- `source_age_days` is derived from wall-clock time. Like `run_id`, it is excluded from numerical reproducibility.

**Evidence:**

- `SHARED_CONTRACTS.md:221`: "Explicit cached snapshot status or…".
- `DATA_SCHEMAS.md:200`: the status enum and field list.
- `RISK_AND_BENCHMARK_SPEC.md:106`: "marks its source as cache with retrieval age".
- WS4 handoff: panels show "period gap and source kind".

### A21 Content hashes, sample IDs and cache invalidation

**State:** proposed

**Value**

**General rule:** hash only plain serialized values, using the `src.contracts.serialization` dicts with `run_id` removed. Never pass a DataFrame or dataclass to `canonical_hash`: its `default=str` hashes the truncated repr, and two different 100-row frames collided (§1.2). Recommended WS4 patch: drop `default=str` so unsupported objects fail loudly.

**Hashes**

- `uncertainty_sha256 = canonical_hash(uncertainty_spec_to_dict(spec))`, with bounds as floats.
- `parent_assumptions_sha256 = canonical_hash(assumptions_to_dict(parent))`.

**Sample identity**

```text
sample_id = "sample-" + canonical_hash({
    parent_assumptions_id, parent_assumptions_version, parent_assumptions_sha256,
    uncertainty_id, uncertainty_version, uncertainty_sha256,
    sampler_version, seed, trial_index})[:16]
```

- Uniqueness is checked within the run; on a collision, extend to 32 hex characters.
- The sampled copy gets `assumptions_id = sample_id`, `version = parent.version` and `is_calibrated = False`. Its `description` cites parent, spec, seed and trial.
- The identity is independent of strategy, so trial `i` has the same `sample_id` for every strategy in a pool. That is the evidence for common random numbers.
- Each trial's `SimulationResult.strategy_id` therefore differs from the deterministic one, as the spec requires (`RISK_AND_BENCHMARK_SPEC.md:30`).

**Top-level risk identity**

- `RiskResult.strategy_id = compute_strategy_id(baseline.baseline_id, action_config, parent.assumptions_id, parent.version)`. The pipeline requires it to equal the Pareto ID.
- `samples.trial_id` is the 0-based trial index (`int`, as in `RISK_SAMPLE_SPEC`).

**`RiskResult.provenance`**

| Field | Value |
|---|---|
| `provider` | `"ws3-monte-carlo"` |
| `is_mock` | `baseline.provenance.is_mock or any(trial.provenance.is_mock)` |
| `seed` | `config.seed` |
| `input_hash` | `canonical_hash({baseline (serialized, no run_id), config, constraints, parent assumptions dict, uncertainty dict, seed, n_simulations, retain_samples, sampler_version})` |
| `config_id` | `f"{uncertainty_id}@{uncertainty_version}"` |
| `assumptions_id` | parent ID |

**Provider versions**

- Risk `ProviderInfo.version` = `f"{module_version}+{uncertainty_id}@{version}+{sampler_version}+u{uncertainty_sha256[:12]}"`. WS4's cache keys hash `ProviderInfo`, so a content edit invalidates them with no WS4 change (N5).
- Benchmark `ProviderInfo.version` = `f"{module_version}+{snapshot_id}+d{content_sha256[:12]}+c{config_sha256[:12]}"`.
- Benchmark `input_hash` = `canonical_hash({baseline_id, baseline totals, forecast period, scope2_method, dataset content_sha256, config dict})`.

**Illustrative values** for the exact JSON in §7, computed with the merged `canonical_hash`. They become fixtures only after A02/A05/A21 are accepted.

| Item | Value |
|---|---|
| Illustrative spec hash | `68e3478426b965d5f73169ea979689e0bafcd85790b199bc3ddd4fd76e52052f` |
| Neutral spec hash | `69edc20581125a9e87c8d7489695cf6cbf755d8b48c6ac4a752b3c2b9a47ebed` |
| `demo-actions-v1` hash | `06f18c027151b3b880b0912dc69f1b1e0cac5cd9f3461f7626a1fdbbd5a86f7e` |
| Sample IDs (seed 42, illustrative spec) | trial 0 `sample-444d602d80d581fa`; trial 1 `sample-5b13befcdd01edaa` |

### A22 Optional imports and error exposure

**State:** accepted (spec-derived; adds no new behavior)

**Value**

- `src/risk/` and `src/benchmarking/` import only `src.contracts`, numpy, pandas and the standard library. `requests` is imported only inside the HTTP code path.
- They never import Streamlit, `src.integration`, optimizer internals or model artifacts, and do no network or file I/O at import.
- Only the defined failures become optional-unavailable: `RiskError`, `BenchmarkSourceError`, and the `unavailable` results. Everything else surfaces.

**Evidence:** `SHARED_CONTRACTS.md:7, 225, 229`; `IMPLEMENTATION_PLAN.md:50, 156`; the merged `tests/contracts/test_offline_startup.py` enforces offline contract imports.

**Record:** reviewer = frozen contract (D14, all four). Contract `1.0.0`. Fixtures `c0-fixtures-r1`. Contract text unchanged since `956fb95`.

### A23 Selected-strategy benchmark and >12 months

**State:** accepted (baseline-only, 12 months); deferred (optimized counterfactual)

**Value**

- `benchmark_company` compares a complete 12-month `BaselineBundle` only.
- `horizon_months != 12` returns `unavailable` with `reason="unsupported_horizon: annual slices not specified"`.
- No `SimulationResult` input and no annualization.

**Evidence:**

- `SHARED_CONTRACTS.md:3`: "Contract `1.0.0` is the integration authority".
- `SHARED_CONTRACTS.md:175`: "Benchmarking runs on the baseline 12-month totals".
- `RISK_AND_BENCHMARK_SPEC.md:81`: unavailable for 36/60.
- The conflicting sentence at `RISK_AND_BENCHMARK_SPEC.md:108` ("baseline or selected strategy") is superseded by the contract signature (X4).

**Deferred:** a counterfactual needs a new reviewed API (WS3 + WS4), the same revenue denominator and a separate label.

**Record:** reviewer D14 (all four). Contract `1.0.0`. Fixtures `c0-fixtures-r1`.

### A24 Numerical reproducibility across versions

**State:** proposed

**Value**

- Numbers are promised to reproduce only within the pinned runtime: Python 3.11, `numpy==2.4.6`, `pandas==3.0.6` (WS4 pins; WS1/WS2 review pending), `uniform-action-major-v1`, and the same spec and assumption content hashes.
- `RiskResult.sampling` records `numpy_version` and `bit_generator`.
- Determinism comparisons exclude only `run_id` and `source_age_days`.
- A dependency upgrade that changes numbers revises the fixtures through review; snapshots are never silently regenerated.

## 4. WS2 obligations (producer → WS3), for review

1. `simulate_strategy` computes `strategy_id` with `src.contracts.identity.compute_strategy_id`. The pipeline compares `RiskResult.strategy_id` with the Pareto IDs.
2. It accepts any valid `ActionAssumptions`, including unseen `assumptions_id`s such as `sample-…`. It never looks parameters up by ID.
3. It reads every sampled field from the object passed in, never from `config/action_assumptions.json` or globals: all six effect fields, `supplier_monthly_savings_at_full_gbp`, and `costs[a].capex_at_full_gbp` / `monthly_opex_at_full_gbp`.
4. It is deterministic: no RNG, no input mutation, fresh return objects. All-zero config is exact no-op under **any** valid assumptions.
5. Confirm A03 (`fixed_opex` = `monthly_opex_at_full_gbp` only), A04 (multiply vs replace) and A07 (the raw-check tolerances `evaluate_constraints` uses).
6. Before risk-aware ranking, `recommend_strategy` checks that every pool result shares `baseline_id`, `uncertainty_id`, `sampling.uncertainty_sha256`, seed, `n_simulations` and the proposed `constraints` field, and that the constraints equal `optimization.constraints`. A mismatch counts as missing risk.

## 5. WS3 obligations (producer → WS4)

1. `create_risk_provider()` loads and validates `config/uncertainty.json` and exposes `uncertainty_id`. Its `info` is `ProviderInfo(slot="risk", name="ws3-monte-carlo", version=<A21>, is_mock=False, kind="real")`. `evaluate(...)` calls `evaluate_strategy_risk(..., uncertainty=<bound spec>)` unchanged.
2. `create_benchmark_provider()` loads `config/benchmark.json` (§7.6), validates source and config, and binds `offline=True` while the only source is CSV. `benchmark(baseline)` follows A17.
3. Every returned object passes the shared validator before return (N8).
4. UI copy (later, Prompts 11/19):
   - "assumption-based action uncertainty; forecast baseline fixed";
   - "90% of trials fell in this range (not a confidence interval)";
   - "met in all N trials; not a guarantee";
   - "synthetic illustrative peer set";
   - forecast period vs peer reporting period.

## 6. Contract deltas for WS4 (steward) review

### 6.1 New shared types (`src/contracts/types.py`, proposed)

```python
UNCERTAINTY_CHANNELS = ("effectiveness", "capex", "fixed_opex")
BENCHMARK_SOURCE_KINDS = ("live", "snapshot", "cache")
PEER_COLUMNS = ("peer_id", "industry", "period_start", "period_end", "revenue_gbp",
                "total_co2e_tco2e", "scope_coverage", "scope2_method",
                "intensity_tco2e_per_million_gbp", "source_id", "is_synthetic")  # + optional "entity_id" (A12)

@dataclass(frozen=True)
class UniformBounds:
    low: float
    high: float
    distribution: str = "uniform"

@dataclass(frozen=True)
class ActionUncertainty:
    effectiveness: UniformBounds
    capex: UniformBounds        # scales costs[a].capex_at_full_gbp (A03)
    fixed_opex: UniformBounds   # scales costs[a].monthly_opex_at_full_gbp (A03)

@dataclass(frozen=True)
class UncertaintySpec:
    uncertainty_id: str
    version: str
    sampling_method: str                     # "independent_uniform"
    sampler_version: str                     # "uniform-action-major-v1"
    correlation_groups: tuple[object, ...]   # must be () in this sampler
    calibration_note: str
    actions: Mapping[str, ActionUncertainty] # keys == ACTION_NAMES

@dataclass(frozen=True)
class BenchmarkSource:
    source_id: str
    kind: str                                # "csv" | "http"
    snapshot_path: str                       # repo-relative normalized peers CSV
    metadata_path: str                       # repo-relative JSON sidecar
    is_synthetic: bool
    endpoint_url: str | None = None          # public https URL, kind="http" only
    credential_env_vars: tuple[str, ...] = ()  # names only, never values
    cache_max_age_days: float = 30.0         # A19, online fallback only

@dataclass(frozen=True)
class BenchmarkConfig:
    industry: str
    scope2_method: str                       # must equal baseline.scope2_method, else unavailable
    scope_coverage: str = "scope1_scope2_scope3"
    min_peers: int = 10
    max_period_end_gap_months: int = 24
    comparison_basis: str = "forecast_vs_historical_peers"
    exclude_entity_ids: tuple[str, ...] = ()  # A12

@dataclass(frozen=True)
class BenchmarkMetadata:                     # = examples/benchmark_peers.json "metadata" + proposed fields
    source_id: str
    source_url: str | None
    retrieved_at: str                        # UTC ISO
    snapshot_id: str
    is_synthetic: bool
    original_currency: str
    original_emissions_unit: str
    reporting_frequency: str                 # "annual"
    fx_method: str                           # A15
    licence_note: str
    transforms: tuple[str, ...]
    exclusions: tuple[Mapping[str, str], ...]  # {"peer_id"|null, "reason", "detail"}
    content_sha256: str | None = None        # A21; required for non-synthetic sources
    fx_rate_gbp_per_unit: float | None = None
    fx_rate_date: str | None = None
    fx_source: str | None = None
    industry_mapping: Mapping[str, str] = field(default_factory=dict)
    source_kind: str = "snapshot"            # set at load time, not stored in the sidecar
    loaded_at: str | None = None             # set at load time from the injected clock

@dataclass(frozen=True, eq=False)
class BenchmarkDataset:
    schema_version: str
    metadata: BenchmarkMetadata
    peers: pd.DataFrame                      # PEER_COLUMNS (+ entity_id)
```

`ActionAssumptions` needs no change: every field the sampler touches already exists (`types.py:252-283`). Note that `costs` is a plain dict inside a frozen dataclass, so the sampler must build a new mapping and never mutate the parent's.

### 6.2 Additive optional fields on existing types

| Type | Field | Type / default | Purpose |
|---|---|---|---|
| `RiskResult` | `constraints` | `ConstraintConfig \| None = None` | The original boundaries behind the flags (WS2 join check) |
| `RiskResult` | `sampling` | `Mapping[str, str] \| None = None` | Keys: `uncertainty_version`, `uncertainty_sha256`, `sampler_version`, `bit_generator`, `numpy_version`, `quantile_method` |
| `BenchmarkResult` | `source_kind` | `str \| None = None` | A20 |
| `BenchmarkResult` | `source_age_days` | `float \| None = None` | A19/A20; transient |
| `BenchmarkResult` | `peer_period_start`, `peer_period_end` | `str \| None = None` | Peer span, distinct from the forecast `period_*` |
| `BenchmarkResult` | `exclusion_counts` | `Mapping[str, int] \| None = None` | A16/A12 |

The decoders must read these with `.get(...)`, because the current `benchmark_from_dict` requires every field (N7). Old fixtures then stay valid.

**Version treatment for WS4 to decide:**

- **Precedent:** WS4 added `AnalysisBundle.request`/`providers` as "additive optional fields (contract 1.x)" and kept `SCHEMA_VERSION = "1.0.0"`.
- **The rule:** `DECISIONS.md:36` says "Minor versions add optional fields".
- **Recommendation:** one combined decision for all additive fields, either keep `1.0.0` (precedent) or bump once to `1.1.0`. WS3 follows whichever WS4 chooses.

### 6.3 Validator deltas (`src/contracts/validation.py`)

- **`validate_risk_config`:** also require `seed >= 0` (N3).
- **`validate_risk_result`:**
  - if `samples` is present: columns exactly `RISK_SAMPLE_COLUMNS`, `len == n_simulations`, `trial_id == range(n)`, bool flags, finite totals;
  - if `constraints` is present: `validate_constraints`;
  - optionally assert `MCSE == sqrt(p(1-p)/n)` within `rel_tol=1e-12`.
- **`validate_benchmark_result`:** `source_kind` is in `BENCHMARK_SOURCE_KINDS` when not null; `exclusion_counts` values are ints ≥ 0; `source_age_days` is finite and ≥ 0.
- **New `validate_uncertainty_spec`:** the A02 rules.
- **New `validate_benchmark_source`:**
  - paths are relative, with no `..` and no drive or home prefix;
  - `endpoint_url` is https and present iff `kind == "http"`;
  - env var names match `^[A-Z][A-Z0-9_]*$`.
- **New `validate_benchmark_config`:**
  - `min_peers` is a positive int and `max_period_end_gap_months` an int ≥ 0, bool rejected for both;
  - `comparison_basis == "forecast_vs_historical_peers"`;
  - `scope_coverage == "scope1_scope2_scope3"`.
- **New `validate_benchmark_dataset`:**
  - columns and dtypes match; `peer_id` is unique;
  - A10 annual spans; revenue > 0; emissions finite and ≥ 0;
  - the intensity identity holds within rtol `1e-8`, atol `1e-6`;
  - there is one `source_id` and one `is_synthetic` value, and they equal the metadata;
  - `entity_id` is present when reported (A12/A13).

### 6.4 Errors, identity and wiring

| File | Delta |
|---|---|
| `src/contracts/errors.py` | Add `BenchmarkSourceError(ProviderError)` with `reason_code` (A17) |
| `src/contracts/identity.py` | Remove `default=str` from `canonical_hash`, or document "plain values only" (A21, N2) |
| `src/contracts/serialization.py` | `uncertainty_spec_to/from_dict`; `benchmark_dataset_to/from_dict` (the JSON shape of `benchmark_peers.json`) plus a CSV peers frame spec; `.get` for the §6.2 fields |
| `src/integration/real_providers.py` | `_factory_provider`: map `ContractValidationError` raised by an **optional** factory to `ProviderUnavailable(reason)`, so a bad WS3 config disables the capability instead of failing real-mode startup (N6) |
| `tests/fixtures/v1/` (r2) | `uncertainty_neutral.json`; neutral `RiskResult` (§7.3); two unavailable benchmarks (§7.4) |

## 7. Examples (proposed; shapes for review, not delivered fixtures)

### 7.1 `config/uncertainty.json`

```json
{
  "uncertainty_id": "illustrative-action-uncertainty-v1",
  "version": "1.0.0",
  "sampling_method": "independent_uniform",
  "sampler_version": "uniform-action-major-v1",
  "correlation_groups": [],
  "calibration_note": "Illustrative independent action-effect and per-action capex/fixed-opex ranges; fixed forecast baseline and action config; not calibrated company risk.",
  "actions": {
    "renewable_energy":    {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}},
    "ev_adoption":         {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}},
    "building_efficiency": {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}},
    "travel_reduction":    {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}},
    "cloud_efficiency":    {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}},
    "supplier_transition": {"effectiveness": {"distribution": "uniform", "low": 0.85, "high": 1.0}, "capex": {"distribution": "uniform", "low": 0.9, "high": 1.1}, "fixed_opex": {"distribution": "uniform", "low": 0.9, "high": 1.1}}
  }
}
```

### 7.2 Neutral spec: `tests/fixtures/v1/uncertainty_neutral.json`

```json
{
  "uncertainty_id": "neutral-action-uncertainty-v1",
  "version": "1.0.0",
  "sampling_method": "independent_uniform",
  "sampler_version": "uniform-action-major-v1",
  "correlation_groups": [],
  "calibration_note": "Deterministic-parity test spec: every multiplier is fixed at 1.0.",
  "actions": {
    "renewable_energy":    {"effectiveness": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "capex": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "fixed_opex": {"distribution": "uniform", "low": 1.0, "high": 1.0}},
    "ev_adoption":         {"effectiveness": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "capex": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "fixed_opex": {"distribution": "uniform", "low": 1.0, "high": 1.0}},
    "building_efficiency": {"effectiveness": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "capex": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "fixed_opex": {"distribution": "uniform", "low": 1.0, "high": 1.0}},
    "travel_reduction":    {"effectiveness": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "capex": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "fixed_opex": {"distribution": "uniform", "low": 1.0, "high": 1.0}},
    "cloud_efficiency":    {"effectiveness": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "capex": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "fixed_opex": {"distribution": "uniform", "low": 1.0, "high": 1.0}},
    "supplier_transition": {"effectiveness": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "capex": {"distribution": "uniform", "low": 1.0, "high": 1.0}, "fixed_opex": {"distribution": "uniform", "low": 1.0, "high": 1.0}}
  }
}
```

### 7.3 Neutral `RiskResult` with retained samples

Inputs: nonzero strategy, `constraints.json`, neutral spec, `seed=42`, `n_simulations=3`, `retain_samples=true`.

These are exact oracles: every trial equals the deterministic golden result, and the 3-trial mean and quantiles are bit-exact (§1.2). They hold for WS2's real engine at C2 (golden values) and for `FixtureSimulatorProvider`. The behavioral mock gives its own affine numbers.

```json
{
  "schema_version": "1.0.0",
  "run_id": "<transient>",
  "provenance": {"provider": "ws3-monte-carlo", "is_mock": true, "seed": 42,
                 "input_hash": "<canonical_hash per A21>",
                 "config_id": "neutral-action-uncertainty-v1@1.0.0", "assumptions_id": "demo-actions-v1"},
  "baseline_id": "baseline-demo-v1",
  "strategy_id": "strategy-8be15857fffc57f6",
  "n_simulations": 3,
  "uncertainty_id": "neutral-action-uncertainty-v1",
  "summary": {
    "co2_mean_tco2e": 843.744, "co2_p05_tco2e": 843.744, "co2_p95_tco2e": 843.744,
    "profit_mean_gbp": 1210940.7847619047, "profit_p05_gbp": 1210940.7847619047, "profit_p95_gbp": 1210940.7847619047,
    "cost_mean_gbp": 186581.1200000001, "cost_p95_gbp": 186581.1200000001,
    "target_probability": 1.0, "profit_floor_probability": 1.0, "budget_probability": 1.0,
    "joint_feasibility_probability": 1.0, "target_probability_mc_standard_error": 0.0
  },
  "samples": [
    {"trial_id": 0, "total_co2e_tco2e": 843.744, "total_profit_gbp": 1210940.7847619047, "total_cost_gbp": 186581.1200000001, "target_met": true, "profit_met": true, "budget_met": true},
    {"trial_id": 1, "total_co2e_tco2e": 843.744, "total_profit_gbp": 1210940.7847619047, "total_cost_gbp": 186581.1200000001, "target_met": true, "profit_met": true, "budget_met": true},
    {"trial_id": 2, "total_co2e_tco2e": 843.744, "total_profit_gbp": 1210940.7847619047, "total_cost_gbp": 186581.1200000001, "target_met": true, "profit_met": true, "budget_met": true}
  ],
  "constraints": {"budget_gbp": 500000.0, "min_total_profit_gbp": 1000000.0, "min_co2_reduction_ratio": 0.2},
  "sampling": {"uncertainty_version": "1.0.0",
               "uncertainty_sha256": "69edc20581125a9e87c8d7489695cf6cbf755d8b48c6ac4a752b3c2b9a47ebed",
               "sampler_version": "uniform-action-major-v1", "bit_generator": "PCG64",
               "numpy_version": "2.4.6", "quantile_method": "linear"}
}
```

Why the flags are true: cost `186581.12 <= 500000`; profit `1210940.78 >= 1000000`; reduction `(1200-843.744)/1200 = 0.29688 >= 0.2`. Why `is_mock` is true: the fixture baseline has `is_mock=true` (A21).

### 7.4 Unavailable benchmarks

**(a) Too few peers after target-entity exclusion.** Fixture peers, `exclude_entity_ids=["synthetic-peer-05"]`.

```json
{
  "schema_version": "1.0.0", "run_id": "<transient>",
  "provenance": {"provider": "ws3-benchmark", "is_mock": true, "seed": null, "input_hash": "<A21>", "config_id": "<benchcfg hash>", "assumptions_id": null},
  "status": "unavailable",
  "company_intensity_tco2e_per_million_gbp": 100.0,
  "industry_median": null, "percentile": null, "better_than_pct": null,
  "peer_count": 9,
  "source_id": "synthetic-peers-v1", "source_url": null, "retrieved_at": "2026-10-03T00:00:00Z",
  "snapshot_id": "synthetic-peer-snapshot-v1", "is_synthetic": true,
  "period_start": "2027-01-01", "period_end": "2027-12-31",
  "scope_coverage": "scope1_scope2_scope3", "scope2_method": "market_based_demo",
  "comparison_basis": "forecast_vs_historical_peers",
  "reason": "too_few_peers: 9 compatible peers after filters; minimum is 10",
  "source_kind": "snapshot", "source_age_days": 0.5,
  "peer_period_start": "2026-01-01", "peer_period_end": "2026-12-31",
  "exclusion_counts": {"target_entity": 1}
}
```

**(b) Source failure with no usable snapshot.** Shape only: a hypothetical HTTP source, because no real provider is selected (A14).

```json
{
  "status": "unavailable",
  "company_intensity_tco2e_per_million_gbp": 100.0,
  "industry_median": null, "percentile": null, "better_than_pct": null, "peer_count": 0,
  "source_id": "<verified-provider-id>", "source_url": "https://<public-endpoint>",
  "retrieved_at": null, "snapshot_id": null, "is_synthetic": false,
  "period_start": "2027-01-01", "period_end": "2027-12-31",
  "scope_coverage": "scope1_scope2_scope3", "scope2_method": "<baseline method>",
  "comparison_basis": "forecast_vs_historical_peers",
  "reason": "source_unavailable:transport_failed: read timeout after 3 attempts; no compatible snapshot within 30 days",
  "source_kind": null, "source_age_days": null, "peer_period_start": null, "peer_period_end": null, "exclusion_counts": null
}
```

### 7.5 Cached provenance: `ok` result after a live failure

Shape only, with a hypothetical source. Only the fields that differ from a live result are shown.

```json
{
  "status": "ok",
  "source_id": "<verified-provider-id>", "source_url": "https://<public-endpoint>",
  "retrieved_at": "2026-09-20T08:00:00Z", "snapshot_id": "<provider>-snapshot-2026-09-20",
  "is_synthetic": false,
  "source_kind": "cache", "source_age_days": 13.166666666666666,
  "peer_period_start": "2024-04-01", "peer_period_end": "2025-12-31",
  "exclusion_counts": {"method_mismatch": 4, "superseded_entity_period": 6, "missing_scope": 3},
  "reason": null
}
```

The status stays `ok`. The cache fact lives in `source_kind`/`source_age_days`, and the original `retrieved_at` is preserved. The example ages here and in §7.4a assume `loaded_at = 2026-10-03T12:00:00Z`.

### 7.6 `config/benchmark.json` (new WS3 config; WS4 to acknowledge the path)

```json
{
  "source": {"source_id": "synthetic-peers-v1", "kind": "csv",
             "snapshot_path": "data/benchmark.csv", "metadata_path": "data/benchmark_metadata.json",
             "is_synthetic": true, "endpoint_url": null, "credential_env_vars": [], "cache_max_age_days": 30.0},
  "comparison": {"industry": "technology", "scope2_method": "market_based_demo",
                 "scope_coverage": "scope1_scope2_scope3", "min_peers": 10, "max_period_end_gap_months": 24,
                 "comparison_basis": "forecast_vs_historical_peers", "exclude_entity_ids": []}
}
```

`data/benchmark_metadata.json` is the fixture's `metadata` object plus `content_sha256`, `fx_rate_gbp_per_unit: null`, `fx_rate_date: null`, `fx_source: null` and `industry_mapping: {}`. `source_kind` and `loaded_at` are set at load time and are not stored in the file.

## 8. Independent test cases that can be written now

These do not wait for the open decisions: each oracle is fixed or written once per option.

1. **Reuse WS4's behavioral mock for Prompt 04.** It already reproduces the Prompt 04 oracle exactly (CO₂ `1053.6`, cost `110000`, profit `1198900`, §1.2). Recommendation: no new `tests/mocks/risk_simulator.py`; add a capturing wrapper in `tests/unit/test_risk.py`. Because the mock ignores building, cloud, supplier and fixed opex (X15), mapping tests for those must assert on the **captured** sampled assumptions, not on totals.
2. **Neutral parity.** Per-trial totals equal a direct deterministic call exactly; quantiles are exact; means are within `rel_tol=1e-12`. Run with n ∈ {1, 3, 1000}.
3. **No-op under the illustrative spec.** Every trial gives 1200 / 1200000 / 0, and every trial still consumed its 18 draws.
4. **Common random numbers.** For two strategies, the captured sample IDs and multiplier-derived fields at each trial index are identical. Reversing evaluation order changes nothing.
5. **Prefix.** n=100 vs n=200: the first 100 sample IDs and multipliers are identical.
6. **Identity.** `RiskResult.strategy_id == compute_strategy_id(parent…)`. No `sample-` ID appears at top level, and the sample IDs within a run are unique.
7. **Failure mapping (A06).** A double returning NaN at trial 5 raises `RiskError` naming trial 5, with no result. A double raising `SimulationError` propagates the same type with a note. A `KeyError` propagates unchanged. In a two-strategy pipeline where one strategy fails, 1 result is returned plus a warning.
8. **Boundaries (A07).** One parametrized table with an expected-value column per option; acceptance removes one column. Equality is true under both options.
9. **Seed.** `-1` and `True` are rejected before any draw (after the §6.3 delta).
10. **Uncertainty validation.** An unknown channel `opex`, a missing action, `low > high`, NaN, an effect `1.01`, a negative cost, `"triangular"`, a non-empty correlations list, or `n=5001` all fail before any draw. Spec bounds `1` and `1.0` hash equally.
11. **Benchmark entities (A12).** The §7.4a case gives 9 peers → `unavailable`, `{"target_entity": 1}`. Two years of one entity count once (`superseded_entity_period: 1`). Mixed `is_synthetic` rows give `ContractValidationError`.
12. **Ties and periods.** The A11 boundary set gives L1 E3 G1. Periods `2024-01-01..2024-12-31` and `2025-04-01..2026-03-31` are annual; `2024-01-15..2025-01-14` and 13-month spans are not. A gap of 24 is included and 25 is excluded.
13. **Loader conversion (A17).** A loader raising `BenchmarkSourceError("transport_failed")` makes the provider return `unavailable` with a `source_unavailable:` reason and no credential text. `benchmark_company` on a 36-month baseline returns `unavailable` with reason `unsupported_horizon`.

## 9. WS4 review requests addressed to WS3

From `docs/handoffs/WS4_DASHBOARD_HANDOFF.md`, "Review requirements (no approvals have occurred)". These are the agent's recommendations; the WS3 owner signs.

| WS4 request | WS3 recommendation | Condition |
|---|---|---|
| Factory names `src.risk.provider.create_risk_provider()` / `src.benchmarking.provider.create_benchmark_provider()` and the `ProviderInfo` convention | Accept | `info.version` recipe in A21; N6 mapping delta |
| `pipeline.select_risk_pool` (endpoints + even spacing, max 20) | No WS3 objection. It matches `RISK_AND_BENCHMARK_SPEC.md:42`, sorts by `(total_co2e_tco2e, strategy_id)` and keeps both ends; Python `round` (half-even) is deterministic | WS2 owns the policy; confirm whether the rule stays in WS4's pipeline or moves to WS2's recommendation module |
| Fixture revision `c0-fixtures-r1` | Accept. The WS3 fixtures (`risk_summary.json`, `benchmark_result.json`, `benchmark_peers.json`, `action_assumptions.json`) are byte-identical to `carbonopt-ai-docs/examples/`. `risk_summary.json` stays shape-only (X11). | Add the §6.4 r2 fixtures after A02/A20/A21 are accepted |
| P0 pins in `requirements.txt` | No objection. Risk needs only numpy/pandas. | `requests` is pinned in `requirements-p1.txt` only when Prompt 16 enables HTTP |

## 10. Decisions that block the next implementation task (Prompt 03, the WS3 contract slice), in order

1. **A02 + A05 channel names**: the `UncertaintySpec` type and JSON shape (§6.1, §7.1). Reviewers: WS4, WS2.
2. **A20 + A12**: the additive `BenchmarkResult` fields, `BenchmarkDataset`/`BenchmarkMetadata`, the optional `entity_id` column and `exclude_entity_ids`. Reviewer: WS4.
3. **A17**: `BenchmarkSourceError(ProviderError)` in contracts, conversion inside WS3's provider, and the N6 factory mapping. Reviewer: WS4.
4. **A21**: the additive `RiskResult.constraints`/`sampling` fields and the hashing rule (`canonical_hash` without `default=str`). Reviewers: WS4, WS2.
5. **Version treatment** for all additive fields (`1.0.0` per precedent, or `1.1.0`), plus the `seed >= 0` validator patch. Reviewer: WS4.

**Prerequisite, not a decision:** WS3 code must start from `main`. Either merge `origin/main` into `workspace3` (one `README.md` conflict; take `main`'s side) or branch `feat/ws3-contracts` from `main`. This note does neither; it needs your choice.

**Needed later, not now:**

| Decision | Reviewer | Needed for |
|---|---|---|
| A04 | WS2 | Prompt 06 |
| A03 | WS2 | Prompt 06 |
| A06 | WS4 | Prompt 07 |
| A07 | WS2 + WS4 | Prompt 08 |
| A08 | WS4 | Prompt 08 |
| A10/A11/A13/A16 | WS4 | Prompts 12–13 |

## 11. Sign-off

| Decision group | Required reviewers | Approved by / date | Commit / fixture revision |
|---|---|---|---|
| A02, A05 (uncertainty shape, sampler) | WS3 owner, WS4, WS2 | | |
| A03, A04 (cost scope, effect mapping) | WS2, WS3 owner | | |
| A06, A07, A08 (failure, flags, quantiles) | WS2, WS4, WS3 owner | | |
| A10–A13, A16 (benchmark data rules) | WS4, WS3 owner (WS1 for dates) | | |
| A17, A20, A21 (+ version treatment) | WS4, WS2, WS3 owner | | |
| A24 (reproducibility) | WS4, WS3 owner | | |
| Already accepted: A01 (layout), A09 (limits), A22, A23 | Recorded above; WS3 owner concurrence only | | `781e91d` / `c0-fixtures-r1` |

## 12. Limitations of this note

- Verification ran against an exported copy of `main` in a scratch venv that reuses the local `adahack` interpreter and libraries. It is not a clean CI run, and the GitHub CI workflow itself has not run (WS4 handoff).
- Hashes, sample IDs and the first matrix row are tied to the exact JSON in §7, the merged `canonical_hash` and numpy 2.4.6. They are illustrations until A02/A05/A21 are accepted.
- §7.3 assumes WS2's real engine reproduces the golden nonzero totals (C2). Exact last bits come from WS2's engine; golden comparisons use 1e-6 t / 0.01 GBP.
- §7.4b and §7.5 use placeholders, because no real benchmark provider exists (A14).
- WS2's simulator, constraints and recommendation are still absent from every branch, so the WS2 obligations in §4 are unconfirmed.
