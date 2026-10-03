"""WS2 optimization: shared constraints, NSGA-II search, Pareto frontier and recommendation.

Importing this package never imports pymoo: constraints, Pareto and recommendation are
pymoo-free, and the NSGA-II entry points load on first use. Mock-mode startup and
consumers that only need constraint badges therefore work without the solver installed.
"""

from typing import Any

from src.optimization.constraints import (
    CURRENCY_TOLERANCE_GBP,
    REDUCTION_RATIO_TOLERANCE,
    SOLVER_FEASIBILITY_TOLERANCE,
    WhatIfEvaluation,
    evaluate_constraints,
    evaluate_what_if,
)
from src.optimization.pareto import assign_pareto_ranks, compute_pareto_frontier
from src.optimization.recommendation import recommend_strategy, risk_pool_from_frontier, select_risk_pool

_LAZY = {"optimize_strategies", "default_seed_configs"}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        from src.optimization import optimizer

        return getattr(optimizer, name)
    raise AttributeError(f"module 'src.optimization' has no attribute {name!r}")


__all__ = [
    "CURRENCY_TOLERANCE_GBP",
    "REDUCTION_RATIO_TOLERANCE",
    "SOLVER_FEASIBILITY_TOLERANCE",
    "WhatIfEvaluation",
    "assign_pareto_ranks",
    "compute_pareto_frontier",
    "default_seed_configs",
    "evaluate_constraints",
    "evaluate_what_if",
    "optimize_strategies",
    "recommend_strategy",
    "risk_pool_from_frontier",
    "select_risk_pool",
]
