"""WS2 optimization: shared constraints, NSGA-II search, Pareto frontier and recommendation."""

from src.optimization.constraints import (
    CURRENCY_TOLERANCE_GBP,
    REDUCTION_RATIO_TOLERANCE,
    SOLVER_FEASIBILITY_TOLERANCE,
    evaluate_constraints,
    relaxation_hints,
)
from src.optimization.optimizer import default_seed_configs, inactive_actions, optimize_strategies
from src.optimization.pareto import assign_pareto_ranks, compute_pareto_frontier
from src.optimization.recommendation import recommend_strategy, risk_pool_from_frontier, select_risk_pool

__all__ = [
    "CURRENCY_TOLERANCE_GBP",
    "REDUCTION_RATIO_TOLERANCE",
    "SOLVER_FEASIBILITY_TOLERANCE",
    "assign_pareto_ranks",
    "compute_pareto_frontier",
    "default_seed_configs",
    "evaluate_constraints",
    "inactive_actions",
    "optimize_strategies",
    "recommend_strategy",
    "relaxation_hints",
    "risk_pool_from_frontier",
    "select_risk_pool",
]
