"""Shared constraint evaluation (docs/ACTION_MODEL.md §5).

``evaluate_constraints`` is the single implementation used by NSGA-II search, manual
what-if and UI badges. Normalized values are dimensionless and pass the solver test when
``g <= SOLVER_FEASIBILITY_TOLERANCE``. Raw horizon totals are checked independently with
the currency and reduction-ratio tolerances; ``feasible`` requires both, so the solver
epsilon is never permission to exceed a budget materially.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import validation as val
from src.contracts.errors import ContractValidationError
from src.contracts.types import ConstraintConfig, ConstraintEvaluation, SimulationResult

if TYPE_CHECKING:
    import pandas as pd

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


def relaxation_hints(candidates: pd.DataFrame, constraints: ConstraintConfig) -> dict[str, float | None]:
    """What the mixes already tried say about loosening one goal while keeping the other two.

    Reads the optimizer's candidate table (``total_cost_gbp``, ``total_profit_gbp``,
    ``co2_reduction_ratio``); a value is None when no tried mix gets there. These are
    observed outcomes, not guarantees: a new search with the loosened goal explores again.
    """
    cost, profit = candidates["total_cost_gbp"], candidates["total_profit_gbp"]
    cut = candidates["co2_reduction_ratio"].fillna(0.0)
    fits = cost <= constraints.budget_gbp + CURRENCY_TOLERANCE_GBP
    floor = profit >= constraints.min_total_profit_gbp - CURRENCY_TOLERANCE_GBP
    target = cut >= constraints.min_co2_reduction_ratio - REDUCTION_RATIO_TOLERANCE
    pick = lambda values, mask, best: float(getattr(values[mask], best)()) if mask.any() else None  # noqa: E731
    return {
        "budget_gbp": pick(cost, floor & target, "min"),
        "min_total_profit_gbp": pick(profit, fits & target, "max"),
        "min_co2_reduction_ratio": pick(cut, fits & floor, "max"),
        "max_reduction_ratio": float(cut.max()) if len(cut) else None,
    }
