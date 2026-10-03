# Person C — Risk, external data and P0 validation

Read [CENTER.md](CENTER.md) first. This role maps PDF sections 7–8. Your P1 features depend on B's engine, so your early contribution is independent P0 validation and preparing the uncertainty interface—not waiting idle or creating a separate product.

## Your responsibility and boundary

Own `src/risk/monte_carlo.py`, `src/risk/recommendation.py`, `src/benchmarking/benchmark.py` and corresponding tests/fixtures. In P0, own independent integration/accounting tests with A/B's agreement. Do not edit their equations, model features or D's UI. Shared contract changes go through D.

## Work in order

### 0:00–2:00 — unblock and verify P0

1. Review the fixture and contracts for units, component reconciliation, investment/profit distinctions and baseline identity.
2. Create small independent expected-value cases for the shared engine and constraint outputs. Check arithmetic rather than copying B's implementation into tests.
3. Agree `effect_parameters` names with B. Document which intervention efficiencies, costs and BAU assumptions could vary; distinguish action uncertainty from forecast uncertainty.
4. Define a small explicit uncertainty specification with bounds and dependence assumptions. Label values illustrative until backed by evidence; avoid pretending arbitrary independent draws are calibrated risk.
5. Build your result schema/fixture so D can prepare risk panels that remain hidden or marked unavailable until real computation is connected.

**First handoff:** independent P0 checks, agreed parameter hook, risk output fixture and assumptions. Risk code is not yet a P0 dependency.

### 2:00–4:00 — prepare the risk harness while supporting integration

1. Implement seeded parameter sampling and call `simulate_strategy()` for each sampled scenario. Do not calculate carbon/action effects separately.
2. Reuse common sampled worlds when comparing strategies so differences are not dominated by different random draws.
3. Start with a small sample count for correctness and timing. Target the PDF's example 5,000 samples only when it fits; store and show the actual count.
4. Test zero-variance equivalence to deterministic simulation, repeated-seed reproducibility, bounded outcomes and conditional target probabilities.
5. Prioritise P0 bugs found during joint integration. Do not enable risk controls until the shared P0 gate passes.

### 4:00–5:30 — integrated risk and recommendation

1. Evaluate the feasible returned strategies or a transparently selected shortlist, not every NSGA-II evaluation. If shortlisted, show coverage and avoid claiming global risk optimisation.
2. Return mean carbon/profit, 2.5/97.5 percentiles, target-hit probabilities and a defined downside measure. State what uncertainty is included; do not call these empirically validated confidence intervals.
3. Implement `select_recommendation(candidates, risk_results, policy)`. Suggested concrete rule: conservative requires joint probability of meeting profit and carbon thresholds >=90%, balanced >=75%, aggressive ranks expected reduction among deterministic-feasible candidates. If no carbon target is set, reliability concerns the profit threshold alone. These are configurable demo policies, not learned risk preferences. If no candidate meets the required reliability, return “none qualifies,” not a silent threshold relaxation.
4. Verify policy changes can alter the recommendation on a labelled constructed fixture. Real data need not change the choice every time; display the applied rule even when unchanged.
5. Add a normalized benchmark only if a credible, compatible peer dataset is available. Capture source/date, sample size, peer definition, scope boundary, reporting period, currency basis and normalization. Return unavailable rather than inventing a percentile. Grid intensity may provide external context but cannot establish a company peer percentile.

**Second handoff:** real risk outputs and an operative recommendation policy. **Optional third:** sourced benchmark or explicit unavailable state.

## Acceptance checks

- Zero uncertainty matches B's simulator; same seed reproduces results.
- Scenario draws are bounded and their correlations/independence are documented.
- Probabilities are in [0,1], intervals ordered, labels reflect actual samples.
- Risk policy changes selection logic, not just chart colours.
- Candidates missing risk results do not silently receive perfect reliability.
- Synthetic peers cannot be presented as real industry rankings; zero revenue/employees prevents the relevant normalization.
- External API/data failure cannot break P0.

## Coding-agent iteration prompts

1. **C1:** “Read CENTER.md and this role file. Prepare independent contract/accounting tests and the uncertainty input/output contract. Use the shared fixture and coordinate effect_parameters with B. Do not implement a separate carbon calculator, benchmark percentile or UI. Help the P0 handoff pass.”
2. **C2:** “Implement seeded Monte Carlo by calling B's central engine with sampled parameters. Test zero-variance identity and common-world comparisons. Return actual sample count, conditional intervals/probabilities and assumptions. Keep this optional until P0 integration passes.”
3. **C3, gated:** “P0 is stable. Implement the documented conservative/balanced/aggressive selection rules over evaluated candidates, including none-qualifies and missing-risk states. Add sourced normalized benchmarking only if comparable data exists; otherwise report unavailable. Never generate an industry percentile from grid-intensity data.”

Final two hours: audit uncertainty/benchmark language and prepare a clear explanation of what the simulations do and do not establish.
