# Person B — Decision engine and optimisation

Read [CENTER.md](CENTER.md) first. This role maps PDF sections 5–6 and owns the central engineering rule: every action calculation passes through `simulate_strategy()`.

## Your responsibility and boundary

Own `src/actions/{definitions,engine}.py`, `src/optimization/{optimizer,constraints}.py` and related tests. Deliver deterministic manual simulation and pymoo/NSGA-II search. Do not implement your own forecast, risk formulas or dashboard. D owns shared types; C owns risk-based recommendation selection.

## Parallel starting point

Use A/D's labelled 12-month fixture from minute 30. You do not wait for model training. Agree with A which carbon components and activity fields the engine needs; zero config must exactly reproduce the supplied future baseline.

Publish the `simulate_strategy(baseline, config, *, effect_parameters=None)` signature immediately. The optional parameter bundle is C's future uncertainty hook; do not hard-code a second risk-only simulator.

## Work in order

### 0:00–2:00 — shared action engine

1. Define the six named intensities from the PDF: renewable energy, EV adoption, building efficiency, travel reduction, cloud efficiency and supplier transition.
2. Follow CENTER's remaining-transition interpretation, 0–1 bounds and zero-config identity. Put all coefficients, investment costs, recurring effects, asset-life assumptions and applicable limits in action definitions.
3. Apply actions to relevant components, then recalculate. For example, building efficiency changes electricity demand before evaluating a renewable transition; EV adoption reduces fuel activity and adds electricity demand. Document scope/accounting assumptions and avoid double counting.
4. Produce monthly and horizon outcomes, investment cost, changes versus BAU and action explanations. Keep capex cash separate from operating profit and its declared depreciation treatment.
5. Test manual inputs before optimisation: all-zero, each action separately, all-max, overlapping actions, invalid/NaN intensities, missing fields and baseline immutability.

**First handoff:** deterministic engine, definitions, worked arithmetic case and tests. D wires the real engine to manual sliders while you build optimisation.

### 2:00–3:30 — feasible Pareto candidates

1. Configure NSGA-II over six continuous decision variables in [0,1]. Minimise horizon CO2e and negative horizon operating profit.
2. Use CENTER's same-horizon budget, minimum-profit and optional carbon-reduction constraints. Explain sign conventions in one place and test each constraint independently.
3. Start with a small reproducible run, for example population 40 and 40 generations, and measure latency. Record seed, settings and approximate-search status; increase quality only within the demo time budget.
4. Every objective/constraint evaluation calls your engine. Re-evaluate returned configs, reject infeasible candidates with documented tolerances, remove dominated/duplicate candidates and give stable IDs to the remaining strategies.
5. Return `OptimizationResult` with configs, outcomes, constraint slacks, status and run settings. No feasible candidate must yield an explicit empty state rather than a fabricated recommendation.
6. Provide a transparent P0 selection policy: among feasible returned candidates choose greatest carbon reduction, break ties by higher profit and then lower investment. Label it a policy over an approximate candidate set, not a unique universal optimum. C can later replace selection with an explicit risk policy.

**Second handoff:** candidate set consumable by D, matched configs and independent feasibility checks.

### 4:00–5:30 — shared-engine support

Help C inject sampled parameters through `effect_parameters`; repeated default calls stay deterministic. Do not put stochastic sampling inside the ordinary optimiser by accident. Profile repeated evaluation and memoise only with complete baseline/config/parameter keys. Explain selected/rejected actions through actual simulated effects and constraints, not SHAP.

## Acceptance checks

- Exact zero-config identity and no baseline mutation.
- Same config gives the same result in manual mode, optimisation and deterministic risk replay.
- Investment/profit accounting is consistent; no emissions reduction counted twice.
- Constraint signs and units are independently checked; zero BAU carbon handled.
- Returned candidates are feasible and nondominated within the returned set; no claim of an exact complete frontier.
- Clicked candidate ID returns its actual six intensities, not the nearest plotted point.

## Coding-agent iteration prompts

1. **B1:** “Read CENTER.md and this role file. Implement only action definitions and simulate_strategy against the shared fixture. Own the intervention equations centrally, explain units/interactions, preserve zero-config identity, and expose effect_parameters for C. Add worked arithmetic/interaction tests. Stop before optimisation.”
2. **B2:** “Add pymoo NSGA-II using only the shared engine. Implement and test all constraint signs, seed/run metadata, final feasibility checks and candidate IDs. Return an approximate feasible nondominated set with original configs. Report actual measured runtime and no-solution behaviour.”
3. **B3:** “Support C's risk integration through parameter injection and fix confirmed engine/optimiser defects. Verify manual, optimiser and risk calls share the same equations. Do not add a parallel simulator, forecasting model or UI.”

Final two hours: independently audit the demo's chosen strategies and help explain why their constraints and trade-offs matter.
