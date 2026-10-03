"""Shared constraint evaluation and the manual what-if boundary (docs/ACTION_MODEL.md §5).

``evaluate_constraints`` is the single implementation used by NSGA-II search, manual
what-if and UI badges. Normalized values are dimensionless and pass the solver test when
``g <= SOLVER_FEASIBILITY_TOLERANCE``. Raw horizon totals are checked independently with
the currency and reduction-ratio tolerances; ``feasible`` requires both, so the solver
epsilon is never permission to exceed a budget materially.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.actions.engine import simulate_strategy
from src.contracts import (
    ActionAssumptions,
    ActionConfig,
    BaselineBundle,
    ConstraintConfig,
    ConstraintEvaluation,
    ConstraintSatisfaction,
    ContractValidationError,
    RawViolations,
    SimulationFn,
    SimulationMetrics,
    SimulationResult,
)
from src.contracts.validation import validate_constraint_config

#: Dimensionless solver feasibility tolerance on g_budget, g_profit and g_target.
SOLVER_FEASIBILITY_TOLERANCE = 1e-8
#: Raw-boundary tolerance for budget and profit totals (GBP).
CURRENCY_TOLERANCE_GBP = 0.01
#: Raw-boundary tolerance for the CO2e reduction ratio.
REDUCTION_RATIO_TOLERANCE = 1e-8


def require_defined_ratio_target(baseline_total_co2e_tco2e: float, constraints: ConstraintConfig) -> None:
    """A positive reduction-ratio target is undefined against a zero CO2e baseline."""
    if baseline_total_co2e_tco2e == 0.0 and constraints.min_co2_reduction_ratio > 0.0:
        raise ContractValidationError(
            "constraints.min_co2_reduction_ratio",
            "ratio target undefined: baseline CO2e is zero, so only a target of 0 is valid",
        )


def evaluate_constraints(result: SimulationResult, constraints: ConstraintConfig) -> ConstraintEvaluation:
    """Normalized constraint values plus raw-boundary feasibility for one simulation.

    g_budget = (total_cost - budget) / max(budget, 1)
    g_profit = (min_profit - total_profit) / max(|min_profit|, |baseline_profit|, 1)
    g_target = min_ratio - reduction_ratio   (0 when baseline CO2e is zero and target is 0)
    """
    validate_constraint_config(constraints)
    if not isinstance(result, SimulationResult):
        raise ContractValidationError("result", f"expected SimulationResult; got {type(result).__name__}")
    metrics = result.metrics
    if not isinstance(metrics, SimulationMetrics):
        raise ContractValidationError("result.metrics", "expected SimulationMetrics")
    require_defined_ratio_target(metrics.baseline_total_co2e_tco2e, constraints)

    budget = constraints.budget_gbp
    min_profit = constraints.min_total_profit_gbp
    g_budget = (metrics.total_cost_gbp - budget) / max(budget, 1.0)
    profit_scale = max(abs(min_profit), abs(metrics.baseline_total_profit_gbp), 1.0)
    g_profit = (min_profit - metrics.total_profit_gbp) / profit_scale
    if metrics.baseline_total_co2e_tco2e == 0.0:
        g_target = 0.0
    else:
        if metrics.co2_reduction_ratio is None:
            raise ContractValidationError("result.metrics.co2_reduction_ratio", "must be set when baseline CO2e is positive")
        g_target = constraints.min_co2_reduction_ratio - metrics.co2_reduction_ratio

    raw = RawViolations(
        budget_gbp=max(0.0, metrics.total_cost_gbp - budget),
        profit_gbp=max(0.0, min_profit - metrics.total_profit_gbp),
        reduction_ratio=max(0.0, g_target),
    )
    satisfied = ConstraintSatisfaction(
        budget=g_budget <= SOLVER_FEASIBILITY_TOLERANCE and raw.budget_gbp <= CURRENCY_TOLERANCE_GBP,
        profit=g_profit <= SOLVER_FEASIBILITY_TOLERANCE and raw.profit_gbp <= CURRENCY_TOLERANCE_GBP,
        target=g_target <= SOLVER_FEASIBILITY_TOLERANCE and raw.reduction_ratio <= REDUCTION_RATIO_TOLERANCE,
    )
    return ConstraintEvaluation(
        g_budget=g_budget,
        g_profit=g_profit,
        g_target=g_target,
        feasible=satisfied.budget and satisfied.profit and satisfied.target,
        raw_violations=raw,
        satisfied=satisfied,
    )


@dataclass(frozen=True, eq=False)
class WhatIfEvaluation:
    """Manual what-if outcome: the canonical simulation and, optionally, its constraint badges."""

    simulation: SimulationResult
    constraints: ConstraintEvaluation | None


def evaluate_what_if(
    baseline: BaselineBundle,
    config: ActionConfig,
    *,
    assumptions: ActionAssumptions,
    constraints: ConstraintConfig | None = None,
    simulator: SimulationFn = simulate_strategy,
) -> WhatIfEvaluation:
    """Manual what-if boundary used by sliders and chat tools.

    Calls the same simulator and constraint function as the optimizer, so a slider result
    for a stored Pareto config equals the stored strategy exactly. Never reruns training
    or optimization.
    """
    if constraints is not None:
        validate_constraint_config(constraints)
    simulation = simulator(baseline, config, assumptions=assumptions)
    evaluation = None if constraints is None else evaluate_constraints(simulation, constraints)
    return WhatIfEvaluation(simulation=simulation, constraints=evaluation)
