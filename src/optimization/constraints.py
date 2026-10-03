"""Shared constraint evaluation and the manual what-if boundary (docs/ACTION_MODEL.md §5).

``evaluate_constraints`` is the single implementation used by NSGA-II search, manual
what-if and UI badges. Normalized values are dimensionless and pass the solver test when
``g <= SOLVER_FEASIBILITY_TOLERANCE``. Raw horizon totals are checked independently with
the currency and reduction-ratio tolerances; ``feasible`` requires both, so the solver
epsilon is never permission to exceed a budget materially.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.contracts import validation as val
from src.contracts.errors import ContractValidationError
from src.contracts.protocols import SimulationFn
from src.contracts.types import (
    ActionAssumptions,
    ActionConfig,
    BaselineBundle,
    ConstraintConfig,
    ConstraintEvaluation,
    SimulationResult,
)

__version__ = "ws2-constraints-1.1.0"

#: Dimensionless solver feasibility tolerance on g_budget, g_profit and g_target.
SOLVER_FEASIBILITY_TOLERANCE = val.SOLVER_FEASIBILITY_TOL
#: Raw-boundary tolerance for budget and profit totals (GBP).
CURRENCY_TOLERANCE_GBP = val.CURRENCY_ATOL_GBP
#: Raw-boundary tolerance for the CO2e reduction ratio.
REDUCTION_RATIO_TOLERANCE = val.RATIO_ATOL


def require_defined_ratio_target(baseline_total_co2e_tco2e: float, constraints: ConstraintConfig) -> None:
    """A positive reduction-ratio target is undefined against a zero CO2e baseline."""
    if baseline_total_co2e_tco2e == 0.0 and constraints.min_co2_reduction_ratio > 0.0:
        raise ContractValidationError(
            "constraints.min_co2_reduction_ratio",
            "ratio target undefined: baseline CO2e is zero, so only a target of 0 is valid",
        )


def _metric(result: SimulationResult, name: str) -> float:
    try:
        return val.require_finite(f"result.metrics.{name}", result.metrics[name])
    except KeyError:
        raise ContractValidationError(f"result.metrics.{name}", "is required") from None


def evaluate_constraints(result: SimulationResult, constraints: ConstraintConfig) -> ConstraintEvaluation:
    """Normalized constraint values plus raw-boundary feasibility for one simulation.

    g_budget = (total_cost - budget) / max(budget, 1)
    g_profit = (min_profit - total_profit) / max(|min_profit|, |baseline_profit|, 1)
    g_target = min_ratio - reduction_ratio   (0 when baseline CO2e is zero and target is 0)
    """
    val.validate_constraints(constraints)
    if not isinstance(result, SimulationResult):
        raise ContractValidationError("result", f"expected SimulationResult; got {type(result).__name__}")
    baseline_co2 = _metric(result, "baseline_total_co2e_tco2e")
    total_cost = _metric(result, "total_cost_gbp")
    total_profit = _metric(result, "total_profit_gbp")
    baseline_profit = _metric(result, "baseline_total_profit_gbp")
    require_defined_ratio_target(baseline_co2, constraints)

    budget = constraints.budget_gbp
    min_profit = constraints.min_total_profit_gbp
    g_budget = (total_cost - budget) / max(budget, 1.0)
    g_profit = (min_profit - total_profit) / max(abs(min_profit), abs(baseline_profit), 1.0)
    if baseline_co2 == 0.0:
        g_target = 0.0
    else:
        ratio = result.metrics.get("co2_reduction_ratio")
        if ratio is None:
            raise ContractValidationError("result.metrics.co2_reduction_ratio", "must be set when baseline CO2e is positive")
        g_target = constraints.min_co2_reduction_ratio - val.require_finite("result.metrics.co2_reduction_ratio", ratio)

    raw = {
        "budget_gbp": max(0.0, total_cost - budget),
        "profit_gbp": max(0.0, min_profit - total_profit),
        "reduction_ratio": max(0.0, g_target),
    }
    satisfied = {
        "budget": g_budget <= SOLVER_FEASIBILITY_TOLERANCE and raw["budget_gbp"] <= CURRENCY_TOLERANCE_GBP,
        "profit": g_profit <= SOLVER_FEASIBILITY_TOLERANCE and raw["profit_gbp"] <= CURRENCY_TOLERANCE_GBP,
        "target": g_target <= SOLVER_FEASIBILITY_TOLERANCE and raw["reduction_ratio"] <= REDUCTION_RATIO_TOLERANCE,
    }
    return ConstraintEvaluation(
        g_budget=g_budget,
        g_profit=g_profit,
        g_target=g_target,
        feasible=all(satisfied.values()),
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
    simulator: SimulationFn | None = None,
) -> WhatIfEvaluation:
    """Manual what-if boundary used by sliders and chat tools.

    Calls the same simulator and constraint function as the optimizer, so a slider result
    for a stored Pareto config equals the stored strategy exactly. Never reruns training
    or optimization. ``simulator`` defaults to the canonical WS2 engine.
    """
    if constraints is not None:
        val.validate_constraints(constraints)
    if simulator is None:
        from src.actions.engine import simulate_strategy as simulator  # canonical engine
    simulation = simulator(baseline, config, assumptions=assumptions)
    evaluation = None if constraints is None else evaluate_constraints(simulation, constraints)
    return WhatIfEvaluation(simulation=simulation, constraints=evaluation)
