# WS3 readiness audit (Prompt 01)

> Background evidence from the completed preparatory audit. Historical inventories and old prompt numbers are not execution instructions. Use `carbonopt-ai-docs/docs/workstreams/03_EXECUTION_PROMPTS_4_HOURS.md`; unresolved proposals here remain draft.


State: **audit only**. This prompt adds no application code, makes no commits, and accepts no decisions. Every A-ID below is still **proposed** until a reviewer records it in `c0-boundary.md` (Prompt 02).

| Item | Observed value |
|---|---|
| Audit date | 2026-10-03 |
| Branch | `workspace3`, tracking `origin/workspace3`, working tree clean before this file |
| HEAD | `1950291` (docs: add comprehensive workstream 3 implementation guide and prompts) |
| `origin/main` / `origin/workstream2` | both `63dc29b`; confirmed with `git ls-remote origin` (local tracking refs are current) |
| Other branches | none on the remote besides `main`, `workspace3`, `workstream2` and `refs/pull/1/head` |
| Tracked files | 36: documentation, JSON examples, `environment.yml`, `.vscode/settings.json`, empty `__init__/__init__.py`, empty `carbonopt-ai-docs/.Rhistory` |

## What changed since `63dc29b`

`git diff --stat 63dc29b HEAD` shows only documentation changes:

```text
 README.md                                          |   4 +-
 .../plans/2026-10-03-workstream3-risk-benchmark.md | 224 ++++++
 retired WS3 prompt pack                  | 765 +++++++++++++++++++++
 retired WS3 architecture register        |  98 +++
 retired WS3 edge-case matrix                     | 165 +++++
 retired WS3 planning overview                         | 154 +++++
 6 files changed, 1409 insertions(+), 1 deletion(-)
```

Nothing in this range adds code, configuration, tests or dependency files. The snapshot in `retired WS3 planning overview` ("no `src/`, `app.py`, `pyproject.toml`…") is still accurate. The only change outside WS3 is a root `README.md` edit, which is covered in contradiction X1.

## 1. Implementation inventory and sources of truth

### 1.1 Code, config and tests that exist

| Target (IMPLEMENTATION_PLAN §4) | Present? | Evidence |
|---|---|---|
| `src/` package, including `src/contracts/{types,protocols,validation,serialization}.py` | **No** | Not in `git ls-files`. The root `__init__/__init__.py` is an empty file in a directory literally named `__init__`; it is not a `src` package. |
| `src/actions/engine.py` (`simulate_strategy`) | **No** | Not on `workspace3`, `main` or `origin/workstream2`, which all contain documentation only. |
| `src/risk/`, `src/benchmarking/` | **No** | — |
| `app.py`, `src/integration/`, `src/dashboard/` | **No** | — |
| `config/` (`default.json`, `action_assumptions.json`, `uncertainty.json`) | **No** | — |
| `data/` (`company_timeseries.csv`, `benchmark.csv`, `provenance.json`) | **No** | — |
| `tests/` (contracts, fixtures/v1, mocks, unit, integration) | **No** | — |
| `pyproject.toml`, `requirements*.txt`, `.env.example` | **No** | — |
| `.gitignore` | **No** | `git ls-files \| grep -c gitignore` returns `0` |
| CI configuration | **No** | — |
| `environment.yml` | Yes | conda `adahack`, `python=3.11`, **unpinned** numpy/pandas/scipy/matplotlib/seaborn/plotly/scikit-learn/statsmodels/jupyterlab/ipykernel/requests/python-dotenv/tqdm |

The local `adahack` environment (built from `environment.yml`) is the agreed project environment for now. It has Python 3.11.16, numpy 2.4.6 (default bit generator `PCG64`), pandas 3.0.6, scipy 1.17.1, scikit-learn 1.9.1, plotly 7.1.0 and requests 2.34.2. It does **not** have pytest, streamlit, lightgbm, xgboost, pymoo or shap. These versions are whatever resolved locally; they are not pins verified at C0. pandas 3.0 changes copy and string-dtype defaults, so pin decisions should be checked against it.

### 1.2 Source-of-truth paths, in precedence order

1. Live repository evidence: this audit.
2. Approved shared contracts: `carbonopt-ai-docs/docs/SHARED_CONTRACTS.md` (contract `1.0.0`) and `carbonopt-ai-docs/docs/DATA_SCHEMAS.md`.
3. Domain specifications:
   - `carbonopt-ai-docs/docs/ACTION_MODEL.md` (WS2)
   - `carbonopt-ai-docs/docs/RISK_AND_BENCHMARK_SPEC.md` (WS3, plus the WS2 recommendation section)
   - `carbonopt-ai-docs/docs/TESTING_AND_MOCKS.md`
   - `carbonopt-ai-docs/docs/INTEGRATION_GUIDE.md`
   - `carbonopt-ai-docs/docs/DECISIONS.md` (D01–D14 frozen)
   - `carbonopt-ai-docs/IMPLEMENTATION_PLAN.md`
   - `carbonopt-ai-docs/README.md`
4. Role file: `carbonopt-ai-docs/docs/workstreams/03_RISK_BENCHMARK.md`. Boundaries are read from `02_ACTIONS_OPTIMIZATION.md` and `04_DASHBOARD_INTEGRATION.md`.
5. Example payloads: `carbonopt-ai-docs/examples/*.json`, all 11 files, verified in §4.
6. WS3 local pack, which is proposal-level and does not override 2–4:
   - `retired WS3 planning overview`
   - `retired WS3 architecture register` (A01–A24, all proposed)
   - `retired WS3 edge-case matrix`
   - `retired WS3 prompt pack`
   - `retired WS3 implementation plan`

No `AGENTS.md` or `CLAUDE.md` exists in the repository.

## 2. Ownership and dependency map

| WS | Owns (target paths) | Publishes to WS3 | Consumes from WS3 | Status in repo |
|---|---|---|---|---|
| WS1 Data/ML | `src/data/`, `src/forecasting/`, `src/explainability/`, `data/company_timeseries.csv`, `data/provenance.json` | Real `BaselineBundle` (C1); baseline `scope2_method`, revenue, dates | Nothing directly; D10 says benchmarks never train the forecast | Docs only |
| WS2 Actions/Opt | `src/actions/`, `src/optimization/` (including `recommendation.py`), `config/action_assumptions.json` (values) | `simulate_strategy` (C2); `ActionAssumptions` values; no-op and nonzero fixtures; feasible Pareto frontier with stable IDs (C3); `evaluate_constraints` | `RiskResult` per strategy for risk-aware `recommend_strategy` (≤20 pool, common trials) | Docs only |
| **WS3 Risk/Bench** | `src/risk/monte_carlo.py` (plus optional small helpers); `src/benchmarking/{adapters,normalize,benchmark}.py`; `config/uncertainty.json`; `data/benchmark.csv` and source metadata; `tests/unit/test_risk.py`, `test_benchmark.py`, `test_benchmark_adapters.py`; `tests/mocks/risk_simulator.py` (test-only) | `RiskResult`, `BenchmarkDataset`, `BenchmarkResult`, handoff fixtures | Simulator callable, baseline, assumptions, constraints, contracts | Docs, plus this audit |
| WS4 UI/Integration | `app.py`, `src/dashboard/`, `src/integration/` (including `cache_keys.py`), `src/llm/`. Steward of `src/contracts/`, `tests/contracts/`, `tests/fixtures/`, dependency files, CI and shared docs/links | C0 types, validators, serializers, error classes, fixture loader, dependency pins, capability flags, failure → `unavailable` mapping, credential wiring | WS3 provider needs, failure types, cache-key inputs, UI copy | Docs only |

Import direction is fixed: WS3 imports `src.contracts` only, plus numpy/pandas and `requests` at the adapter boundary. It does not import optimizer internals, models or Streamlit.

The acceptance chain WS3 sits on is C0 → C1 → C2 → C3 → C4 → **C5a risk** → C5b SHAP → **C5c benchmark** → C6.

## 3. Contradictions and open conflicts (exact text)

For each conflict, the exact wording is shown and nothing is chosen silently. The resolver column names the owner or decision that must settle it.

| # | Conflict | Resolver |
|---|---|---|
| X1 | **Stale root README on `main`.** `git show 63dc29b:README.md` line 5 reads: `Build **CarbonOpt with Django + Plotly**. Start with the retired shared team center (`docs/team-execution/CENTER.md`) … retired supporting guides (`docs/technical-guide/README.md`)`. Neither linked path exists in the `63dc29b` tree. This conflicts with IMPLEMENTATION_PLAN §2 (Streamlit, "No initial FastAPI, React"). It is fixed **only on `workspace3`** (1950291), and that fix edits a WS4-stewarded shared doc inside a WS3 docs commit. Both branches also end the README with the stray test line `deneme1`. | WS4 reviews the README hunk when `workspace3` merges. |
| X2 | **Nested docs vs "copy to root".** `carbonopt-ai-docs/README.md:5` says "Copy the contents of this folder to the application repository root … Every source, configuration, fixture, and command path in the documentation is relative to that root". The docs are nested instead. `retired WS3 planning overview:33` says "Do not … blindly copy/delete its contents", and A01 proposes keeping the docs nested. A literal copy would overwrite root `README.md` and merge `carbonopt-ai-docs/docs/` into the existing root `docs/` (which holds `workstream3/` and `superpowers/`). IMPLEMENTATION_PLAN §4 also names the root `carbonopt-ai/`, while the repo is `ADAHACK_SimpleMen`. | A01 (WS4 + all) at C0 |
| X3 | **Two dependency workflows.** Root `README.md` says "Add the package under `dependencies:` in `environment.yml` … Commit the updated `environment.yml`", using conda with no pins. INTEGRATION_GUIDE §7 says `python -m venv .venv` and `pip install -r requirements.txt`, with `requirements-p1.txt`/`-p2.txt`. IMPLEMENTATION_PLAN §2 says "Choose and lock exact dependency versions during C0". The environment lacks pytest, so no test command can run yet. | WS4 at C0 (A01) |
| X4 | **Benchmark input: baseline only, or also selected strategy?** RISK_AND_BENCHMARK_SPEC §5 says "Benchmarks annotate baseline or selected strategy intensity using the same denominator". SHARED_CONTRACTS §3 says "Benchmarking runs on the baseline 12-month totals", and the fixed signature takes `baseline: BaselineBundle`. | A23: baseline-only now; a counterfactual needs a new reviewed API. WS3 + WS4 |
| X5 | **"Cached snapshot status" has no enum.** The SHARED_CONTRACTS §4 table says "Network timeout/API failure → Explicit cached snapshot status or `BenchmarkResult(status="unavailable")`". DATA_SCHEMAS §9 says "Result status is `ok` or `unavailable`", and its field list has no source-kind or age field. | A20 (provenance extension, WS3 + WS4) at C0 |
| X6 | **Same-company exclusion lacks an entity key.** RISK_AND_BENCHMARK_SPEC §4 says "Exclude the same company when its peer ID matches the target company identity; retain an exclusion count". But §3 defines `peer_id` as a "Unique comparable company-period ID" with no entity column, and the DATA_SCHEMAS §9 `BenchmarkResult` fields have no exclusion-count field. | A12 + A20 (WS3 + WS4) at C0 |
| X7 | **Adoption-factor replacement vs nondefault deterministic values.** ACTION_MODEL §2 lists `renewable_effectiveness`, `ev_effectiveness`, `travel_effectiveness` "in [0,1], default 1.0", so non-1 values are legal. RISK_AND_BENCHMARK_SPEC §1 says "sampled multipliers replace their default effectiveness values", which would silently discard a non-1 deterministic value. | A04 (WS2 + WS3) before the sampler |
| X8 | **Which opex varies.** RISK_AND_BENCHMARK_SPEC §1 says "per-action capex/opex multiplier bounds". Incremental opex has three parts (ACTION_MODEL §4): fixed action opex, EV electricity and renewable premium. The text does not say which are sampled. | A03 (WS3 + WS2) before the sampler |
| X9 | **What "raw boundary" means.** DATA_SCHEMAS §9 says "Trial flags use raw constraint boundaries". ACTION_MODEL §5's own "raw" check uses tolerances: "independently check raw totals with currency tolerance `0.01` and reduction tolerance `1e-8`". A07 proposes strict comparisons with no tolerance. The two readings give different flags at `cost = budget + 0.005`. | A07 (WS2 + WS3 + WS4) at C0 |
| X10 | **`UncertaintySpec` has no schema, and the fixture's ID is undefined.** SHARED_CONTRACTS §2 says only that it "contains distributions and correlation metadata". No uncertainty JSON exists anywhere. `risk_summary.json` cites `"uncertainty_id": "illustrative-risk-v1"`, which no document defines; the A02 proposal uses `illustrative-action-uncertainty-v1`. | A02 (WS3 + WS2 + WS4) at C0 |
| X11 | **`risk_summary.json` is not reproducible under the documented initial policy.** §4.3 shows three summary values outside the reachable range. `target_probability = 0.96` is also impossible, because the worst-case reduction ratio is `0.252402 ≥ 0.2`, which forces the probability to 1.0. The file is already labelled illustrative (`examples/README.md`). It must stay a **shape-only** fixture and never serve as a numerical oracle or C5a evidence. | WS3: replace it with real and neutral risk fixtures at Prompt 10/11 |
| X12 | **A10's completion rule vs the synthetic fixture.** A10 proposes "Reported peers must already be completed by retrieval date". The synthetic peers end `2026-12-31`, but `retrieved_at` is `2026-10-03T00:00:00Z`. The rule must apply to `is_synthetic=false` rows only, or the delivered fixture fails its own test. | A10 wording (WS3 + WS1 + WS4) |
| X13 | **Where the trial limit lives.** RISK_AND_BENCHMARK_SPEC §1 says "impose an application limit (default 5,000)". `RiskConfig` (SHARED_CONTRACTS §2) has no max field, so whether this is a constant, a config value or a capability is unspecified. | A09 (WS3 + WS2 + WS4) |
| X14 | **Branch names vs convention.** INTEGRATION_GUIDE §5 uses `feat/ws3-<task>` ("No personal names"), with reference branches `feat/ws3-risk` / `feat/ws3-benchmark`. The live branches are `workspace3` and `workstream2`. I am keeping the human's selected `workspace3`; no switch was made. | Team; WS4 for convention |
| X15 | **The affine double only partly covers risk.** In TESTING_AND_MOCKS §2, the double depends only on renewable/EV effectiveness and renewable/EV capex. It cannot detect wrong building, cloud or supplier mapping, or wrong fixed-opex scaling. Those mappings need tests that inspect captured assumptions (retired edge-case matrix already lists these). This is a coverage limit, not a contract conflict. | WS3 test design (Prompt 04/06) |

Checked and **not** contradictory:

- On `workspace3`, no tracked markdown prescribes Django. The only mentions are the WS3 pack's notes that those references are stale (`retired WS3 planning overview:5`, `retired prompt pack:40`).
- All relative links in the 21 tracked markdown files resolve (0 broken on `workspace3`).
- The 204-month history window (Jan 2010–Dec 2026 = 17 × 12) is consistent.
- `RiskConfig` defaults (seed 42, 1,000 trials, `retain_samples=False`) match across documents.
- WS2's role file confirms that WS3 owns uncertainty distributions and WS2 owns deterministic accounting.

## 4. Fixture verification (independent arithmetic)

Command, run from the repository root with the `adahack` Python 3.11 environment:

```sh
python carbonopt-ai-docs/docs/handoffs/ws3/audit_examples.py
```

The script uses the standard library only. It re-derives every value from the ACTION_MODEL.md hand equations and the RISK_AND_BENCHMARK_SPEC.md §4 rules, without reading the fixture's own metrics as input. It is an **audit-only oracle**: it must never be imported by `src/` or used as a simulator. Actual result: `103 PASS`, `0 FAIL(S)`, exit code 0.

### 4.1 Baseline and deterministic simulations

| Check | Result |
|---|---|
| All 11 examples parse; no NaN/Infinity tokens | PASS ×11 |
| Baseline months | 12 contiguous months, `2027-01-01..2027-12-01`, immediately after `history_end=2026-12-01`; one company |
| Baseline sums | revenue 12,000,000; profit 1,200,000; CO₂ 1,200 (equal to `totals`); per-row scope1+2+3 = total |
| Assumption partitions | scope1 0.6+0.4 = 1; scope3 0.2+0.2+0.5+0.1 = 1; adoption factors all 1.0 (the A04 premise holds for this fixture) |
| No-op (`strategy-84d0730a93b9d729`) | Every monthly emission and profit value equals the baseline row exactly; all cost columns are exactly 0; metrics 1200 / 1200000 / 0 |
| Nonzero (`strategy-8be15857fffc57f6`) | Hand equations give CO₂ **843.744**, profit **1210940.7847619047**, capex **164000**, gross cost **186581.1200000001**, opex 22581.12, savings 54360, net cash −132221.12. Month-1 scopes are **16.08 / 8.982 / 45.25**. Every metric equals the monthly column sums. |
| Accounting identities, every month | `budget_cost = capex + opex`; `net_cash = savings − opex − capex`; `profit = base + savings − opex − depreciation` (capex not subtracted from profit); capex in month 1 only; revenue unchanged |
| Canonical identity | SHA-256 of sorted compact JSON `{"assumptions_id":"demo-actions-v1","assumptions_version":"1.0.0","baseline_id":"baseline-demo-v1","config":{…floats…}}`, first 16 hex characters, reproduces **both** strategy IDs |
| Renewable final share | 0.2 + (1 − 0.2) × 0.7 = **0.76** |
| Optimization fixtures | Candidate and Pareto IDs join `strategies`; `ok` has 1 feasible rank-0 point; `infeasible` has an empty Pareto; each stored strategy's totals match the hand equations |

### 4.2 Benchmark

| Check | Result |
|---|---|
| Peers | 10 unique IDs; one industry (`technology`); all `2026-01-01..2026-12-31` (full 12 months); `scope1_scope2_scope3`; `market_based_demo` (same as baseline); `is_synthetic=true`; stored intensity = CO₂/(revenue/1e6) |
| Company intensity | 1200 / (12000000 / 1e6) = **100** |
| Peer intensities | [40, 60, 80, 90, 100, 110, 120, 140, 160, 200]; **median 105** |
| Rank with A11 proposal (tol 1e-8) | L=4, E=1, N=10 → **percentile 45, better-than 55**, equal to `benchmark_result.json` |
| Period gap | Peer end 2026-12 vs forecast end 2027-12 = 12 months ≤ 24; result labelled `forecast_vs_historical_peers` |

### 4.3 `risk_summary.json`: shape fixture, not sampled

Internally the file is consistent: it has exactly the 13 summary fields in contract order, MCSE = √(0.96 × 0.04 / 1000), joint ≤ min(marginals), `samples: null`, and `provenance.is_mock=true`.

The script then checks whether these numbers could come from the documented initial policy. It applies effectiveness U[0.85, 1] and capex/fixed-opex U[0.9, 1.1] through the proposed A03/A04 mapping to the nonzero strategy. All totals are multilinear in these independent box parameters, so their extremes lie at the 2⁶ × 2 vertices the script enumerates. The reachable ranges are:

```text
co2    [843.744, 897.118]        profit [1201582.143, 1215233.362]   cost [166823.808, 203262.592]
co2_p95_tco2e=920        OUTSIDE
profit_p05_gbp=1200000   OUTSIDE
profit_p95_gbp=1220000   OUTSIDE
worst-case reduction ratio 0.252402 >= target 0.2  -> target_probability would be 1.0, fixture says 0.96
```

The CO₂ and target conclusions do not depend on the A03 cost scope. **Conclusion:** this file is illustrative shape data (X11). No WS3 test may assert these numbers.

### 4.4 Statistical oracles from retired edge-case matrix (numpy 2.4.6)

| Oracle | Result |
|---|---|
| `[10,20,30,40]` with linear quantiles | mean 25.0, p05 11.5, p95 38.5 |
| Flags: target T,T,F,F; profit T,F,T,F; budget T,T,T,F | 0.5 / 0.5 / 0.75; **joint 0.25** (row-wise AND; the product of marginals would be 0.1875); MCSE 0.25 |
| Skewed sample: 99 zeros and one 1000 | mean 10.0 while p05 = p95 = 0.0, so the mean lies outside [p05, p95], as retired edge-case matrix says is valid |

### 4.5 Synthetic future dates (labels preserved)

The audit date is 2026-10-03, so several fixture dates lie in the future:

- The documented history window ends December 2026; October–December 2026 are synthetic future months.
- The baseline `history_end` is 2026-12-01 and the forecast covers 2027-01..2027-12.
- Peer reporting periods end 2026-12-31, after `retrieved_at` 2026-10-03.

Every one of these carries a synthetic or mock label: `data_kind="synthetic"`, `provenance.is_mock=true`, `is_synthetic=true`, `licence_note="Synthetic example supplied with documentation."`. None may be described as reported observations. X12 is the decision this date gap affects.

## 5. C0 prerequisites: ready vs missing

| Prerequisite | State |
|---|---|
| Contract 1.0.0 text, public WS3 signatures, risk/benchmark field names | **Ready** (docs) |
| 11 example payloads, independently verified | **Ready**; still need copying into `tests/fixtures/v1/` |
| WS3 decision proposals A01–A24 | **Drafted, none accepted** |
| Python 3.11 + numpy/pandas/requests locally | **Partially ready**: unpinned and not team-verified |
| pytest (and its pin) | **Missing**; no test can run |
| `src/__init__.py`, `src/contracts/*` (types, protocols, validation, serialization, `ContractValidationError`, `UnsupportedHorizon`) | **Missing** (WS4) |
| `UncertaintySpec`, `RiskResult`, `BenchmarkSource`, `BenchmarkConfig`, `BenchmarkDataset`, `BenchmarkResult` types and serializers | **Missing**; WS3 proposes fields, WS4 implements them in contracts |
| Narrow benchmark loader exception names (A17) | **Missing / undecided** |
| `ActionAssumptions` type with nested `costs` | **Missing** (contracts; WS2 approves fields) |
| `simulate_strategy` (C2), `evaluate_constraints` | **Missing** (WS2) |
| `config/uncertainty.json` plus a neutral spec | **Missing**; blocked on A02/A03/A04/A05 |
| Fixtures: neutral risk, two-strategy risk pool, unavailable benchmark, multi-point frontier, invalid cases | **Missing**; TESTING_AND_MOCKS §1 lists them as C0 tasks |
| `.gitignore`, CI, `pyproject.toml`/`requirements*.txt` | **Missing** (WS4) |
| Layout/docs-root decision (X2), dependency workflow (X3) | **Undecided** (A01) |
| Real benchmark provider | **None selected or verified**; not needed before P1 |

## 6. Next three tasks

| # | Task (prompt) | Deliverable | Pass check | Can start? |
|---|---|---|---|---|
| 1 | Resolve architecture choices (Prompt 02) | `carbonopt-ai-docs/docs/handoffs/ws3/c0-boundary.md`: one record per A01–A24 using the template in retired architecture register, each with state (`proposed`/`accepted`), named reviewer and affected fixture. It also carries proposed resolutions for X2–X13 and an explicit list of shared-contract field additions for WS4 (UncertaintySpec shape, benchmark provenance extension, entity mapping, exclusion counts, loader exception names). | Every A-ID appears exactly once. No `accepted` row lacks a reviewer and evidence. Each X-item maps to an A-ID or owner. No file outside `retired WS3 planning folder/` changes. | **Now.** Docs only, in a WS3-owned path. Acceptance needs WS2/WS4 review. |
| 2 | WS3 C0 contract slice (Prompt 03) | A small coordinated patch for WS4 to steward: risk/benchmark types and validators in `src/contracts/`, `config/uncertainty.json` and the neutral spec, contract tests that round-trip all 11 examples plus both uncertainty specs and reject NaN/bool counts/reversed bounds. | `python -m pytest tests/contracts -q` passes from the repo root on the pinned environment. The shared-file diff is reviewed by WS4, and by WS2 for assumption fields. | **Blocked** until WS4 lands the C0 skeleton and pins (or authorizes WS3 to contribute on `chore/c0-contracts`) and A02–A05/A07 are accepted. |
| 3 | Behavioral risk test double (Prompt 04) | `tests/mocks/risk_simulator.py`, an affine `SimulationFn` with `is_mock=true`, plus hand-arithmetic sensitivity tests in `tests/unit/test_risk.py`: changing effectiveness or capex changes totals; the no-op is exact; inputs are not mutated. | `python -m pytest tests/unit/test_risk.py -q` passes. Expected values are typed in by hand, not produced by calling the double. | **Blocked** on C0 types/serializers and pytest. It does **not** need WS2's simulator. |

Benchmark normalization (Prompt 12) is the parallel track after task 2. It needs the approved `BenchmarkSource`/`BenchmarkDataset` types (A10–A13/A16/A20) and does not depend on any other workstream's code.

## 7. Dependency report

**Can start now:**

- Task 1 (`c0-boundary.md`).
- Collecting reviewer answers on A01–A24.
- Drafting WS3's requested field list for WS4.

None of these needs code from another owner.

**Needs C0 (WS4 shared foundation):** tasks 2 and 3; sampler, runner and statistics (Prompts 05–09); benchmark normalization, ranking and adapters (Prompts 12–17).

**Needs the shared simulator boundary (WS2 C2) or later:**

| Needs | Prompts |
|---|---|
| WS2 C2 | Real-simulator parity (Prompt 10); runtime measurement and C5a handoff (Prompt 11) |
| WS2 C3 | Risk-pool selection handoff (Prompt 18) |
| WS4 Services | Provider wiring (Prompt 19) |

**Files another owner must supply:**

| Owner | Exact files / artifacts |
|---|---|
| WS4 (steward) | `pyproject.toml` and/or `requirements.txt`, `requirements-p1.txt`, `requirements-p2.txt` with verified pins including **pytest**; `.gitignore`; `src/__init__.py`; `src/contracts/__init__.py`, `types.py`, `protocols.py`, `validation.py`, `serialization.py` (including `ContractValidationError`, `UnsupportedHorizon`, A17 loader exceptions, `SimulationFn`); `tests/contracts/`; `tests/fixtures/v1/` (the 11 copied examples); `tests/mocks/` and `tests/unit/` directories; CI config; the A01 layout/README decision (X1–X3) |
| WS2 | `src/actions/engine.py::simulate_strategy` (C2) and `src/actions/definitions.py`; `config/action_assumptions.json`; the accepted `ActionAssumptions` field list for contracts; `src/optimization/constraints.py::evaluate_constraints`; C2 no-op/nonzero fixtures produced by the real engine; later `src/optimization/pareto.py` and `recommendation.py` (C3, P1 risk-aware selection); review of A03/A04/A07/A09 |
| WS1 | Not required for WS3 development (the fixture baseline suffices). Later: real `BaselineBundle` (C1); confirmation of baseline `scope2_method` and the industry label, both needed to qualify a real benchmark source (A14) |

## 8. Limitations of this audit

- The environment check ran the local `adahack` interpreter directly; `conda run` failed in this shell, a local tooling issue unrelated to the repository. Library versions are evidence of the local environment only, not team pins.
- The reachability bounds in §4.3 assume the proposed A03 cost scope and A04 replacement mapping. The CO₂ and target-probability conclusions hold under any cost scope.
- The A11 tie tolerance used in §4.2 is a proposal. On this fixture, exact equality gives the same result.
- The hand-equation oracle checks the delivered example numbers. It is not, and must not become, a replacement for WS2's simulator.
