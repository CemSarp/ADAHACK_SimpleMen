# WS2 Follow-ups

> **Productisation update:** the app launches one CSV-backed company path with no provider selector. Earlier milestone descriptions below are historical. See [the current README](../../README.md) for launch and configuration instructions.

Open work for Workstream 2 (actions, optimization, Pareto, recommendation) after integrating with WS4 on `workstream2` (merge of `main`, pending review). [WS2_HANDOFF.md](WS2_HANDOFF.md) describes what works; this file lists what does not yet. Each item names its owner, what blocks it, and what counts as done.

## Done during the WS2–WS4 integration

- [x] One contract package: WS4's `src/contracts/` is the schema; WS2's stopgap copy was removed and WS2 code adapted.
- [x] Real WS2 providers bound through WS4's registry; documented hybrid preset "Fixture forecast + real WS2".
- [x] `pymoo==0.6.2` pinned in `requirements.txt`; `src.optimization` imports without pymoo.
- [x] Single risk-pool rule (`risk_pool_from_frontier`) shared by the WS4 pipeline and the recommendation.
- [x] `recommend_strategy(tolerance=...)` annotated with the contract's `Tolerance` literal.
- [x] Cross-boundary integration tests and Streamlit AppTest coverage of the hybrid flow.

## 1. Small WS2 items (no dependencies)

- [ ] **Multi-point frontier fixture.** `carbonopt-ai-docs/examples/README.md` asks for one for chart and dominance tests; the existing optimization fixtures have one and zero frontier points.
  - Do: save a small seeded real run (for example 256 evaluations) as `tests/fixtures/v1/optimization_multipoint.json`.
  - Tests: it validates with `validate_optimization_result` and is nondominated under `diagnostics.dominance_tolerances`.
  - Size: a full run serializes every candidate's strategy, so keep the evaluation budget small.
- [ ] **Engine-generated sample results** for the handoff (`python -m src.optimization.cli simulate --output …`), labelled `is_mock=true` because the baseline is a fixture.
- [ ] **Log optimizer termination** (`02_ACTIONS_OPTIMIZATION.md`): one INFO line per run with `run_id`, termination reason, evaluation counts, Pareto count and runtime; test it with `caplog`.

## 2. Reviews and sign-offs (need other people)

- [ ] **WS4/WS3 review of the shared contract changes** in handoff §5:
  - `ConstraintEvaluation.satisfied` and `RecommendationResult.diagnostics`;
  - strict assumption parsing;
  - null standard error only for an undefined target;
  - nonnegative optimizer seed;
  - `-0.0` identity normalization;
  - picklable errors;
  - the `pymoo` pin.

  Record approved changes in `carbonopt-ai-docs/docs/DECISIONS.md`.
- [ ] **WS4 decision on `pareto_rank = 1`** for feasible-but-dominated candidates (the docs define only 0 and −1).
- [ ] **C2 sign-off** (simulator, what-if, constraints): WS3 and WS4.
- [ ] **C3 sign-off** (optimizer, Pareto, infeasible payload, selection): WS4.

## 3. Blocked on other workstreams

- [ ] **WS1 baseline (C1), the replacement point.** WS1 publishes `src.forecasting.provider.create_forecast_provider()`; use the default integrated dashboard; rerun the suite and the CLI against the real baseline. Expect compatibility errors for zero activities with allocated emissions (handoff §4); fix them in the baseline or the assumptions, not by loosening checks.
- [ ] **WS3 risk (C5a).** Run Monte Carlo on `select_risk_pool(...)` through `apply_uncertainty_sample`; add a test with real WS3 output, including zero-uncertainty parity; confirm the three tolerances against real summaries.
- [ ] **Scenario comparison (C6, WS4)** on top of real risk.
- [ ] **All-real C4 run** with no mock provenance, then the `mvp-working` tag (WS4).

## 4. Later decisions (not blocking P0)

- [ ] **Validator performance (WS4 with WS2).** About 1.6 ms of each 2.5 ms simulation is `validate_baseline`; the pipeline re-validates every stored strategy (about 2.5 s at 2,048 candidates). Vectorizing the shared validators would bring dashboard Optimize from about 12 s to roughly 4–5 s without skipping any check.
- [ ] **Saved result size.** A full 2,048-candidate result is about 15 MB of JSON. A compact replay format would need a contract decision, because `validate_optimization_result` requires every candidate's strategy.
- [ ] **Calibrated assumptions.** A new `assumptions_id`/version, evidence and reviewer recorded per `DECISIONS.md`; strategy IDs change accordingly.
- [ ] **Performance on the declared demo machine** once WS4 names it (`python -m src.optimization.cli profile`).
- [ ] **36/60-month horizons.** The simulator handles them (depreciation cut-off tested on 60 months); they stay hidden until WS1 supports them.
- [ ] **Display-share helper.** `src/dashboard/presentation.resulting_share` restates the renewable/EV share formula for slider captions. A parity test pins it to `compute_action_breakdown`; WS4 may switch to calling the engine directly.
