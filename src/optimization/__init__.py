"""WS2 optimization: shared constraints, NSGA-II search, Pareto frontier and recommendation."""

from src.optimization.constraints import (
    CURRENCY_TOLERANCE_GBP,
    REDUCTION_RATIO_TOLERANCE,
    SOLVER_FEASIBILITY_TOLERANCE,
    WhatIfEvaluation,
    evaluate_constraints,
    evaluate_what_if,
)
from src.optimization.optimizer import default_seed_configs, optimize_strategies
from src.optimization.pareto import assign_pareto_ranks, compute_pareto_frontier
from src.optimization.recommendation import recommend_strategy, select_risk_pool

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
    "select_risk_pool",
]
