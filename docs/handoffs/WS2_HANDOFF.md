# WS2 Handoff — Action Engine, Constrained NSGA-II, Pareto and Recommendation

Contract version `1.0.0` · branch `workstream2` · audience: WS3 (risk), WS4 (dashboard and integration), WS1 (baseline producer)

## Status in one paragraph

The WS2 P0 backend runs end to end against the supplied synthetic baseline fixture: deterministic six-action simulator, shared constraint evaluation, manual what-if boundary, budget-bounded NSGA-II, validated feasible Pareto frontier and the P0 equal-weight recommendation. The P1 risk-aware selection policy is implemented against hand-authored `RiskResult` objects and the `risk_summary.json` fixture; WS3's Monte Carlo is not part of this work. This is checkpoint C2/C3 evidence on **fixtures only**: it does not mean forecasting, dashboard integration or the all-real C4 MVP is done, and every fixture-based output carries `provenance.is_mock = true`.

## 1. Change and public boundary

| Item | Value |
|---|---|
| Producer / consumers | WS2 → WS3 (risk trials, selection pool), WS4 (sliders, Pareto chart, recommendation, chat tools) |
| WS2-owned paths | `src/actions/`, `src/optimization/`, `config/action_assumptions.json`, `tests/unit/test_{actions,accounting,constraints,optimizer,pareto,recommendation}.py` |
| Shared paths touched (WS4 review) | `src/contracts/`, `tests/contracts/`, `tests/fixtures/v1/`, `tests/mocks/`, `tests/conftest.py`, `tests/support.py`, `environment.yml`, `.gitignore` (see §8) |
| Contract version | `1.0.0`; additive fields listed in §8 |
| Location | Repository root, as the docs package instructs (`src/`, `config/`, `tests/` sit beside `carbonopt-ai-docs/`) |

Production dependencies point inward only: `src.actions` and `src.optimization` import `src.contracts`, NumPy, pandas and (optimizer only) pymoo. Nothing imports Streamlit, risk, dashboard, HTTP or model artifacts, and no module keeps global state.

## 2. Public interfaces

Import consumer types from `src.contracts`. All functions are synchronous, validate before computing, never mutate inputs, and raise `ContractValidationError(field, reason)` for invalid inputs.

### Simulation (`src.actions`)

```python
simulate_strategy(baseline: BaselineBundle, config: ActionConfig, *, assumptions: ActionAssumptions) -> SimulationResult
compute_action_breakdown(baseline, config, *, assumptions) -> pd.DataFrame   # same transform, intermediate quantities
load_action_assumptions(path=None) -> ActionAssumptions                      # default: config/action_assumptions.json
compute_strategy_id(baseline_id, config, assumptions) -> str
apply_uncertainty_sample(assumptions, *, sample_id, effectiveness_multipliers=None,
                         capex_multipliers=None, opex_multipliers=None) -> ActionAssumptions   # WS3 hook
```

`simulate_strategy` is the canonical `SimulationFn`. It returns the 12 documented monthly columns plus reconciled horizon metrics, so no consumer needs its own accounting formula. `compute_action_breakdown` exposes resulting renewable and EV shares (show them next to the implementation fraction), activity changes and per-bucket emissions; the scope columns of the `SimulationResult` remain authoritative.

### Constraints and manual what-if (`src.optimization`)

```python
evaluate_constraints(result: SimulationResult, constraints: ConstraintConfig) -> ConstraintEvaluation
evaluate_what_if(baseline, config, *, assumptions, constraints=None, simulator=simulate_strategy) -> WhatIfEvaluation
```

`ConstraintEvaluation` carries `g_budget`, `g_profit`, `g_target`, `feasible`, `raw_violations` and the additive `satisfied.{budget,profit,target}` flags for UI badges. WS4 must not recompute feasibility. `evaluate_what_if` is the slider and chat-tool boundary: it calls the same simulator and constraint function as the optimizer.

### Optimization, Pareto and recommendation (`src.optimization`)

```python
optimize_strategies(baseline, constraints, *, assumptions, config: OptimizerConfig, simulator: SimulationFn) -> OptimizationResult
compute_pareto_frontier(candidates: pd.DataFrame) -> pd.DataFrame
assign_pareto_ranks(candidates) -> pd.DataFrame          # 0 frontier, 1 feasible-but-dominated, -1 infeasible
dominance_tolerances(candidates) -> (emissions_tco2e, profit_gbp)
recommend_strategy(optimization, *, risk_results=None, tolerance="balanced") -> RecommendationResult
select_risk_pool(optimization, *, max_size=20) -> tuple[str, ...]
```

Production binds `simulator=simulate_strategy`. Test doubles belong in isolated solver tests only; the result exposes the simulators actually used in `diagnostics["simulator_providers"]` and in `provenance.is_mock`.

## 3. Behaviour that consumers rely on

**Action semantics.** Each value in [0, 1] is the fraction of the *remaining eligible opportunity*, implemented in month 1 and held. Out-of-range, non-finite, boolean and string values are rejected, never clamped, and `-0.0` normalises to `0.0`. Renewable 0.7 on a 0.2 baseline share gives a final share of 0.76, not a 70% target.

**Transform.** The transform follows `ACTION_MODEL.md` §3 in order: bucket allocation → building efficiency on baseline building load only → ICE-to-EV conversion with added load → renewable coverage on the resulting demand → separate travel, cloud and supplier buckets → accounting. Each scope is computed as `baseline_scope × (1 − reduction_fraction)`, which is algebraically identical to the documented bucket equations. The literal bucket re-summation does not round back to the baseline for about 6% (scope1) to 25% (scope3) of arbitrary float baselines, which would break the exact no-op on real WS1 data; the factored form keeps the all-zero config bit-exact for every emission and profit row, with zero costs. The total moves by the scope deltas, preserving the baseline's own scope/total reconciliation. EV adoption can raise scope2 and total emissions; negative reductions are never clamped.

**Accounting.** Capex is charged once, in month 1. Straight-line depreciation (`capex_i / asset_life_months_i`) hits operating profit and stops after the asset life; asset life must be a whole number of months. Profit equals baseline + savings − incremental opex − depreciation and may be negative. Budget cost is capex + incremental opex; savings never reduce it. Net cash impact is savings − opex − capex and is reported separately.

**Constraints.** `g_budget = (cost − budget)/max(budget, 1)`, `g_profit = (floor − profit)/max(|floor|, |baseline profit|, 1)`, and `g_target = target − reduction ratio`. A constraint passes when `g ≤ 1e-8` **and** its raw boundary holds (0.01 GBP for budget and profit, 1e-8 for the ratio), so the solver epsilon never allows a material overspend. A positive ratio target on a zero-CO2e baseline is a `ContractValidationError`; a zero target there gives `g_target = 0`.

**Optimizer.** The search runs as follows:
1. The no-op is evaluated first, then the deterministic seeds (each action alone at 1.0, all at 1.0, all at 0.5), then a seeded Latin-hypercube fill.
2. Every search evaluation, initialization included, counts against `max_evaluations`; the last generation is truncated to fit.
3. Termination reasons are `max_generations`, `max_evaluations` or `no_new_offspring`.
4. Candidate repair is explicit: vectors are clipped to [0, 1] and the count is reported in `repaired_candidates`.

Every unique evaluated config is kept: its full `SimulationResult` is in `strategies` and its summary row in `candidates`. Each published Pareto strategy is re-simulated from its stored exact config, must reproduce the stored outcome bit for bit, and must pass raw constraints. Those re-validation calls are reported as `revalidated_pareto_count` and are not part of the search budget. pymoo ≥ 0.6.2 uses a local generator, so the global NumPy RNG is untouched (tested). An empty frontier returns `status="infeasible"` with a typed empty Pareto table, per-constraint and joint violation minima, `least_violating_strategy_id`, and a warning that this is not a proof of global infeasibility. Unexpected solver or simulator failures raise `OptimizationError` with the original exception chained.

**Pareto.** Infeasible rows are filtered before any dominance test, and cost takes no part in dominance. A dominates B when it is no worse beyond tolerance in both objectives and strictly better beyond tolerance in one. The tolerances are 0.01 GBP for profit and 1e-6 t + 1e-8 × the largest feasible |CO2e| for emissions; they are published in `diagnostics["dominance_tolerances"]` and are the ones to use for any independent nondominance check. Distinct configs with equivalent objectives are all kept. Exact duplicate configs collapse onto the smallest ID. Rows are sorted by CO2e, then `strategy_id`.

**Identity.** A strategy ID is `strategy-` + the first 16 hex characters of SHA-256 over sorted-key compact JSON of `{baseline_id, config (full-precision floats), assumptions_id, assumptions_version}`. It reproduces both fixture IDs exactly. If a truncated ID collides with a different full identity, the new ID is extended (24, 32, … hex characters). Never store or evaluate display-rounded configs; select by `strategy_id` and use `strategies[id].config`.

**P0 recommendation.** Equal-weight min-max score over feasible Pareto strategies (CO2e and negative profit). An objective whose range is within tolerance contributes zero. Ties break on the smallest ID, and a single point is selected directly. An infeasible optimization gives `strategy_id=None`, `score=None`.

**P1 recommendation.** `select_risk_pool` keeps both endpoints and samples evenly by emissions order, up to 20 strategies. The policies are:
- conservative: joint probability ≥ 0.90, then equal-weight CO2e p95 and negative profit p05;
- balanced: joint probability ≥ 0.75, then equal-weight mean CO2e and negative mean profit;
- aggressive: 0.75 × mean CO2e + 0.25 × negative mean profit.

Missing or invalid results are excluded and listed in `diagnostics.excluded_strategy_ids`. No usable results gives the deterministic fallback with `risk_status="unavailable"`, and no risk-aware selection is claimed. If no strategy meets the threshold, the highest joint probability wins, then the policy score, with `risk_status="threshold_unmet"` and a `shortfall`. Partial coverage shows as `risk_status="partial"`, or, when the threshold is also unmet, in `diagnostics.coverage` and `reason`. Results from different trial sets (`uncertainty_id`, `n_simulations`, seed) are rejected.

## 4. Assumptions

`config/action_assumptions.json` (`demo-actions-v1`, version `1.0.0`, `is_calibrated: false`) is byte-identical to the documented illustrative example. It describes the synthetic demo company only and is **not** calibrated company economics. Changing any coefficient requires a new ID/version, because strategy identities depend on it. The parser is strict: unknown fields fail, so a typo cannot silently fall back to a default. Renewable, EV and travel effectiveness default to 1.0.

Model-compatibility rules enforced by the simulator (ACTION_MODEL.md §2, DATA_SCHEMAS.md §2):

| Baseline condition | Result |
|---|---|
| ICE-fleet scope1 allocated but `fleet_km × (1 − ev_share) = 0` | `ContractValidationError` on `fleet_km` |
| Gas scope1 allocated but `gas_kwh = 0` | error on `gas_kwh` |
| `scope2 > 0` with `electricity_kwh = 0` | error on `electricity_kwh` |
| `scope2 > 0` with `renewable_energy_share = 1` | error on `scope2_tco2e` |
| Travel or cloud scope3 allocated with zero km or hours | error on that activity column |

An action with zero eligible opportunity must have zero cost coefficients in the assumption set: the engine charges coefficients as written, so a mis-specified set produces cost without benefit (tested and documented, not hidden).

Uncertainty hook for WS3: `apply_uncertainty_sample` implements the RISK spec §1 mapping exactly.
- Renewable, EV and travel multipliers *replace* effectiveness.
- Building, cloud and supplier multipliers *scale* the maximum-reduction coefficient; supplier also scales savings.
- Capex and opex multipliers scale per-action cost coefficients.

`sample_id` becomes the copy's `assumptions_id` and must differ from the parent's, so sampled trials never share a deterministic identity. All-ones multipliers reproduce the deterministic outcome bit for bit (tested).

## 5. Fixtures and samples

`tests/fixtures/v1/` holds byte-identical copies of the WS2-relevant documentation examples; a contract test fails on drift. The real engine reproduces `simulation_noop.json` exactly and `simulation_nonzero.json` within 2.3e-13 (identical strategy IDs; golden totals 843.744 t, GBP 1,210,940.7847619047 profit, GBP 164,000 capex, GBP 186,581.12 gross outlay). `tests/mocks/affine_simulator.py` is the documented test-only affine double; it is labelled mock and responds to sampled effectiveness and capex.

A full reference optimization serializes to about 15 MB because every candidate keeps its monthly frame. For saved replay bundles use `optimization_result_to_dict(result, strategies="frontier")` (about 4 MB indented for the reference run): candidates stay complete, the `strategies` map keeps the frontier plus the no-op, and the payload states `strategies_included`.

## 6. Reproduction (repository root)

```sh
# Option A: team conda environment (environment.yml now includes pytest and pymoo>=0.6.2)
conda env update -f environment.yml && conda activate adahack
# Option B: isolated venv with Python 3.11
python -m venv .venv && . .venv/bin/activate
python -m pip install numpy pandas "pymoo>=0.6.2" pytest

python -m pytest tests/contracts tests/unit                    # full WS2 + contract suite
python -m src.optimization.cli simulate --constraints tests/fixtures/v1/constraints.json
python -m src.optimization.cli simulate --action ev_adoption=1 --action renewable_energy=0
python -m src.optimization.cli optimize --output optimization.json --compact
python -m src.optimization.cli profile                         # runtime on this machine
```

Defaults: `tests/fixtures/v1/baseline_12m.json`, `config/action_assumptions.json`, `tests/fixtures/v1/constraints.json`, optimizer seed 42, population 64, generations 32, 2,048 evaluations. Use `python -m pytest`, not bare `pytest`, so the repository root is importable.

## 7. Evidence

| Check | Result |
|---|---|
| `python -m pytest tests/contracts tests/unit` | 230 passed, about 7 s (Python 3.11.9, NumPy 2.4.6, pandas 3.0.6, pymoo 0.6.2) |
| Same suite on NumPy 1.26.4 / pandas 2.3.3 | 230 passed (§7a) |
| Golden arithmetic | Independent hand-derived literals for every single action, interactions, buckets, accounting and totals |
| No-op | Bit-exact on the fixture and on a 60-month irregular-float baseline that defeats the literal bucket sum |
| Stored vs direct | Every stored candidate equals a direct `simulate_strategy` call (metrics, monthly frame, `g` values) |
| Manual vs optimizer | `evaluate_what_if` on a recommended config equals the stored strategy exactly |
| Toy problem | Affine double with an analytical frontier: the search beats the best seed (min CO2e < 959 t; optimum 944.0 t) without beating the optimum |

Runtime on the reference configuration (MacBook, Apple Silicon arm64, macOS 15.7; one machine, not a guarantee):

| Measurement | Result | Team starting budget |
|---|---|---|
| `simulate_strategy`, 12-month fixture, 500 calls | median 0.83 ms, p95 0.94 ms | < 20 ms |
| `optimize_strategies`, 64 × 32 = 2,048 evaluations | 2.9–3.0 s wall (289 Pareto strategies, all re-validated) | < 20 s for 2,000 evaluations |

### 7a. Library compatibility

| Stack | Result |
|---|---|
| Python 3.11.9, NumPy 2.4.6, pandas 3.0.6, pymoo 0.6.2 | 230 passed |
| Python 3.11.9, NumPy 1.26.4, pandas 2.3.3, pymoo 0.6.2 | 230 passed |

## 8. Shared changes flagged for WS4 review

C0 did not exist, so this branch contains the **smallest contract-compatible foundation WS2 needs**, isolated in shared paths for steward review rather than a competing schema system:

1. `src/contracts/` defines `types.py`, `errors.py` (`ContractValidationError`, `OptimizationError`), `validation.py`, `serialization.py` and `protocols.py` (`SimulationFn`), covering only the types WS2 publishes or consumes: `ActionConfig`, `ConstraintConfig`, `OptimizerConfig`, `Provenance`, `BaselineBundle`, `ActionAssumptions`, `SimulationResult`, `ConstraintEvaluation`, `OptimizationResult`, `RiskResult`/`RiskSummary` and `RecommendationResult`. `RiskConfig`, `UncertaintySpec`, `ModelBundle`, `BenchmarkResult` and the others are left to their owners. Config types validate themselves on construction; boundary functions also validate.
2. Additive fields and conventions:
   - `ConstraintEvaluation.satisfied`;
   - `RecommendationResult` carries `schema_version`, `run_id`, `provenance` and a `diagnostics` map;
   - the `OptimizationResult` JSON field `strategies_included`;
   - `pareto_rank = 1` for feasible-but-dominated candidates (the docs define only 0 and −1);
   - optimizer diagnostics keys beyond the fixture's;
   - canonical identity JSON uses `ensure_ascii=False` (affects non-ASCII IDs only);
   - result parsers tolerate unknown fields; config parsers reject them.
3. The test kit adds `tests/fixtures/v1/` (copied examples plus README), `tests/conftest.py`, `tests/support.py`, `tests/mocks/affine_simulator.py` and `tests/contracts/test_contracts_foundation.py`.
4. `environment.yml` adds `pytest` and `pymoo>=0.6.2` (pip), unpinned beyond that floor; WS4 locks versions at C0. `.gitignore` adds Python caches and `.venv/`.
5. The root `README.md` still describes an older Django plan and links missing files; it is unchanged here and needs a WS4 decision.

## 9. Integration requirements

**WS4.**
- Bind `simulate_strategy` in `mode="real"`.
- Sliders call `evaluate_what_if`; badges read `ConstraintEvaluation.satisfied`.
- A Pareto click stores `strategy_id` and uses `strategies[id]` and its exact config; round for display only.
- Show final renewable and EV shares from `compute_action_breakdown`.
- Render the infeasible state from `status`, `diagnostics.warning` and `minimum_normalized_violations`.
- Show a mock banner whenever `provenance.is_mock` is true.
- Cache keys must include baseline fingerprint, assumptions ID/version, all constraints, and optimizer seed and budget (all inside `provenance.input_hash`, which is deterministic, as is `run_id`).
- Plot profit positively if desired, but never feed that sign back into search.

**WS3.**
- Inject the same `simulate_strategy`.
- Build trials with `apply_uncertainty_sample` and a unique `sample_id` per trial.
- Zero uncertainty must reproduce the deterministic result.
- Evaluate risk only for `select_risk_pool(optimization)` with one shared trial set.
- Return `RiskResult` keyed by the deterministic `strategy_id` with the documented summary fields. Only `target_probability`, `joint_feasibility_probability` and its standard error may be null; a null joint probability excludes that strategy from the conservative and balanced policies.

**WS1.** The real `BaselineBundle` must pass `validate_baseline_bundle`:
- `horizon_months` in {12, 36, 60} with exactly that many contiguous `datetime64` month-start rows starting the month after `history_end` (a `datetime.date`);
- one `company_id`;
- totals equal to the column sums;
- scope sums within 1e-6 t + 1e-8 relative;
- the §4 compatibility rules, most often `ev_share < 1` wherever ICE-fleet scope1 is allocated, and `scope2 = 0` when renewable share is 1.

The simulator needs no preprocessing beyond that.

## 10. Known limitations

- Assumptions are illustrative and uncalibrated; the baseline is a flat synthetic fixture. No real WS1 forecast has been run through the engine yet.
- NSGA-II is stochastic: results are reproducible per seed and validated, not globally optimal. `infeasible` means none was found within the budget.
- No discounting, financing, tax, disposal value or action-driven revenue (P0 scope). Depreciation requires whole-month asset lives.
- Full-precision JSON for a reference run is large (§5). Frontier re-validation adds simulator calls outside the search budget.
- P1 risk selection is verified only with hand-authored and fixture `RiskResult`s until WS3 delivers real Monte Carlo; uncertainty sampling and benchmarks remain WS3 work.
- Runtime figures come from one developer machine; measure on the declared demo profile before raising budgets.

## 11. Remaining cross-workstream dependencies

1. WS4 reviews and merges or replaces the minimal `src/contracts/` foundation (C0), then locks dependencies and CI.
2. WS1 delivers a real `BaselineBundle` (C1); run the WS2 suite and the CLI against it with no consumer changes expected.
3. WS4 wires the simulator, what-if and optimizer providers and swaps mocks one at a time (C2, C3), then the all-real C4 run and the `mvp-working` tag.
4. WS3 delivers real `RiskResult`s for the selection pool (C5a); WS2 re-runs the policy tests with real outputs.
