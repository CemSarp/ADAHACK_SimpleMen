# Workstream 2 — Action Engine, Multi-objective Optimization and Pareto

Developer 2 owns the numerical decision engine. Consumers: WS3 risk and WS4 manual what-if/dashboard/chat tools.

## Read first

Read [contracts](../SHARED_CONTRACTS.md), [schemas](../DATA_SCHEMAS.md), [action model](../ACTION_MODEL.md), and [risk recommendation policy](../RISK_AND_BENCHMARK_SPEC.md). Use the baseline fixture immediately; do not wait for trained forecasts.

## Ownership

Source: `src/actions/definitions.py`, `src/actions/engine.py`, `src/optimization/constraints.py`, `src/optimization/optimizer.py`, `src/optimization/pareto.py`, `src/optimization/recommendation.py`.

Configuration: `config/action_assumptions.json`. Tests: `tests/unit/test_actions.py`, `test_accounting.py`, `test_constraints.py`, `test_optimizer.py`, `test_pareto.py`, `test_recommendation.py` within `tests/unit/`.

WS2 owns intervention and financial assumptions. WS3 owns their uncertainty distributions but cannot independently change deterministic accounting.

## Inputs and outputs

Consumes BaselineBundle, ActionConfig, ActionAssumptions, ConstraintConfig, OptimizerConfig and injected simulator. Publishes SimulationResult, ConstraintEvaluation, OptimizationResult and RecommendationResult.

Every consumer calls the same public `simulate_strategy`. No solver object or private cost function crosses the boundary. Return both horizon totals and monthly records; the dashboard and risk engine must not reconstruct profit from a separate formula.

## Exact local implementation order

| Step | Priority | Task | Evidence |
|---:|---|---|---|
| 1 | P0 | Assumption types/validator; fixed action vector order | Config serialization and bounds tests |
| 2 | P0 | No-op simulator and monthly accounting | Exact golden no-op; inputs not mutated |
| 3 | P0 | Individual actions and interactions | Renewable/building/EV tests; bucket conservation |
| 4 | P0 | Publish what-if function and constraints | UI/direct call numerical equality |
| 5 | P0 | Toy constrained optimizer adapter | Objective signs and constraint direction |
| 6 | P0 | Real NSGA-II using injected canonical simulator | Bounded seeded search and full audit table |
| 7 | P0 | Pareto validation and deterministic recommendation | Dominance, feasibility, stable IDs |
| 8 | P1 | Risk-aware selection on evaluated frontier pool | Same constraints; policy-specific selection |

## Start without waiting

Use `examples/baseline_12m.json` with the documented illustrative assumption object. Start simulator and Pareto tests in parallel inside the workstream using hand-computed points. The toy optimizer uses an injected function with known objectives/constraints, not a second production emissions engine.

Keep the action assumption fields required by P1 sampling available at C0, defaulting renewable/EV/travel effectiveness to 1. The Monte Carlo developer can immediately pass alternative assumption objects.

## Numerical implementation guidance

Use vectorized monthly arithmetic. Apply the fixed transformation order, distinct scope buckets and gross-outlay budget. Normalize solver constraints; retain raw validation separately. Profit can be negative and EV can increase emissions.

Six decision variables follow the exact ActionConfig order. Bound all in [0,1]; reject out-of-bound public input rather than silently clamp. The solver's candidate repair policy, if used internally, is explicit and reported.

Always evaluate no-op. Respect maximum evaluations and log termination. Return a typed infeasible result when no feasible point is found. Re-evaluate returned frontier points using canonical inputs, full precision, and the same assumptions.

Stable identity includes baseline and assumptions. A UI percentage rounded for display must never overwrite actual stored values. Keep objective-equivalent strategies available for risk differences.

## Test requirements

No-op, action bounds, single-action direction, residual-bucket floors, renewable/efficiency multiplicative interaction, EV load transfer, capex once, depreciation cutoff, profit/cash distinction, and budget excluding savings are mandatory.

Constraint tests include budget zero, negative profit floor, target zero, impossible targets, zero baseline with positive ratio target, and epsilon-boundary values.

Pareto tests use known feasible/infeasible/dominated/equivalent points; random search is not an oracle for global optimality. Seeded NSGA-II tests require reproducible behavior and valid feasible output, not an assertion that a stochastic solver finds an exact global optimum.

Risk recommendation tests use hand-authored means/quantiles/probabilities that produce distinct tolerance choices. Failed risk results are excluded or trigger explicit fallback.

## Handoffs and done

C2 delivers assumptions, no-op/nonzero results, public simulator, constraints and tests to WS3/WS4. C3 delivers optimization result with ID joins and empty/infeasible case; WS4 reviews selection.

P0 done: manual and optimizer evaluations match, no-op is exact, all returned Pareto points satisfy raw constraints and nondominance, and UI never uses a different cost/emissions calculation.

P1 done: selected strategy is from the tested risk pool and labels missing/partial/threshold-unmet risk.

Reference branches: `feat/ws2-actions` then `feat/ws2-optimizer`. Keep action-engine acceptance ahead of optimizer/Pareto acceptance.
