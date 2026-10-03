# WS2 Follow-ups After Merge

Open work for Workstream 2 (actions, optimization, Pareto, recommendation) as of commit `22cee48` on `workstream2`. Everything WS2 implemented is described in [WS2_HANDOFF.md](WS2_HANDOFF.md); this file lists only what is **not** done yet, so it can be picked up after `workstream2` is merged with the other workstreams.

Each item names its owner, what blocks it, and what counts as done. Tick the box when finished.

## 1. Small WS2 items (no dependencies; can be done any time)

- [ ] **Multi-point frontier fixture.** `carbonopt-ai-docs/examples/README.md` asks for one so WS4 can build the Pareto chart and dominance tests; the existing optimization fixtures have one and zero frontier points.
  - Owner: WS2. Reviewer: WS4.
  - Do: run a small seeded optimization on the fixture baseline (for example population 16, about 200 evaluations) and save it with `optimization_result_to_dict(result, strategies="frontier")` as `tests/fixtures/v1/optimization_multipoint.json`. Add a contract test that it parses, that every Pareto row is feasible and nondominated under `diagnostics.dominance_tolerances`, and that every Pareto `strategy_id` joins the `strategies` map.
  - Done when: the fixture is committed, under about 300 KB, and tested.
- [ ] **Engine-generated sample results for the handoff.** The handoff template asks for "a sample serialized result". Today the samples are the documentation fixtures, which the engine reproduces exactly but did not generate.
  - Owner: WS2.
  - Do: save engine output for the no-op and the example config (`python -m src.optimization.cli simulate --output ...`), labelled with real provider `action-engine` and `is_mock=true` (fixture baseline).
  - Done when: files are committed next to the fixtures and referenced from the handoff.
- [ ] **Log optimizer termination.** `02_ACTIONS_OPTIMIZATION.md` says "respect maximum evaluations and log termination". The reason is stored in `diagnostics["termination_reason"]`, but nothing is written to Python logging.
  - Owner: WS2.
  - Do: add a module logger in `src/optimization/optimizer.py` and log one INFO line per run with `run_id`, termination reason, evaluation counts, Pareto count and runtime. No secrets or absolute paths in the message.
  - Done when: a test using `caplog` sees the line.
- [ ] **Contract type annotation.** `recommend_strategy(..., tolerance: str = "balanced")` should be annotated with the contract's `Literal["conservative", "balanced", "aggressive"]` (`RiskTolerance` in `src/contracts/types.py`). Behaviour is already correct; invalid values are rejected.
  - Owner: WS2.

## 2. Reviews and sign-offs (need other people)

- [ ] **WS4 review of the shared C0 foundation added by WS2.** C0 did not exist, so the WS2 branch contains a minimal version (see §8 of the handoff):
  - `src/contracts/` (types, errors, validation, serialization, protocols);
  - `tests/fixtures/v1/`, `tests/conftest.py`, `tests/support.py`, `tests/mocks/affine_simulator.py`, `tests/contracts/test_contracts_foundation.py`;
  - `environment.yml` (`pytest`, `pymoo>=0.6.2`) and `.gitignore`.

  WS4 decides whether to keep, merge or replace these. If another branch also defines `src/contracts/`, reconcile into **one** schema system before merging to `main`; do not keep two.
- [ ] **WS4 decision on additive contract fields.** Approve or reject:
  - `ConstraintEvaluation.satisfied` (per-constraint badges);
  - `RecommendationResult` carrying `schema_version`, `run_id`, `provenance` and `diagnostics`;
  - `strategies_included` in serialized `OptimizationResult`;
  - `pareto_rank = 1` for feasible-but-dominated candidates (the docs define only 0 and -1);
  - extra optimizer diagnostics keys;
  - canonical identity JSON using `ensure_ascii=False`.

  Record approved changes in `carbonopt-ai-docs/docs/DECISIONS.md`.
- [ ] **C2 sign-off** (simulator, what-if, constraints): WS3 and WS4.
- [ ] **C3 sign-off** (optimizer, Pareto, infeasible payload, selection): WS4.

## 3. Integration work blocked on other workstreams

- [ ] **Run against WS1's real baseline (C1).** So far only the synthetic fixture and generated variants have been used.
  - Do: load WS1's `BaselineBundle`, run `python -m pytest tests/contracts tests/unit` plus the CLI `simulate` and `optimize` against it, and confirm no consumer code changes are needed.
  - Watch for the simulator's compatibility rules (handoff §4), most often `ev_share = 1` in a month where ICE-fleet scope1 is still allocated, or positive scope2 with renewable share 1. Fix such cases in the baseline or the assumptions, not by loosening the checks.
- [ ] **Wire WS2 into WS4's services (C2/C3).** Bind `simulator=simulate_strategy` in `mode="real"`; sliders call `evaluate_what_if`; Pareto clicks use `strategies[strategy_id]` and its exact config. Add WS4's provider-swap tests (mock versus real simulator and optimizer).
- [ ] **P1 with real risk results (C5a).** The risk-aware policies are tested only with hand-authored `RiskResult` objects and `risk_summary.json`.
  - Do: once WS3 ships Monte Carlo, run `select_risk_pool` → WS3 risk for that pool (built with `apply_uncertainty_sample`, one shared trial set) → `recommend_strategy` for all three tolerances. Add a test using real WS3 output, including the zero-uncertainty parity check.
- [ ] **Scenario comparison (C6, WS4).** Calls `recommend_strategy` three times on the same risk pool; WS2 reviews.
- [ ] **All-real C4 run.** Full pipeline with no mock provenance in P0 outputs, then the `mvp-working` tag (WS4).

## 4. Later decisions (not blocking P0)

- [ ] **Calibrated assumptions.** `config/action_assumptions.json` (`demo-actions-v1`) is illustrative and uncalibrated. Real values need a new `assumptions_id`/`version`, evidence and a reviewer recorded per `DECISIONS.md`; strategy IDs will change accordingly.
- [ ] **Performance on the declared demo profile.** Measured only on one developer machine (simulation about 0.8 ms, 2,048-evaluation optimization about 3 s). Re-run `python -m src.optimization.cli profile` on the team's demo setup once WS4 declares it.
- [ ] **Dependency lock.** `environment.yml` only sets `pymoo>=0.6.2` (needed: older versions use the global NumPy random generator). WS4 pins exact versions at C0; the suite passes on both NumPy 2.4 / pandas 3.0 and NumPy 1.26 / pandas 2.3.
- [ ] **Saved result size.** A full 2,048-candidate result serializes to about 15 MB. Decide with WS4 whether replay bundles use the compact `strategies="frontier"` form (about 4 MB).
- [ ] **36/60-month horizons.** The simulator already handles them (depreciation cut-off is tested on 60 months), but they stay hidden until WS1's forecast supports them.
- [ ] **Root `README.md`.** Still describes an older Django plan and links missing files; WS4 to update after the docs package is moved to the repo root.
