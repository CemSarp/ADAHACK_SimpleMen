"""WS2 optimizer provider: NSGA-II search, shared constraint evaluation and recommendation policy."""

from __future__ import annotations

from typing import Mapping

from src.contracts.protocols import SimulationFn
from src.contracts.types import (
    ActionAssumptions,
    BaselineBundle,
    ConstraintConfig,
    ConstraintEvaluation,
    OptimizationResult,
    OptimizerConfig,
    ProviderInfo,
    RecommendationResult,
    RiskResult,
    SimulationResult,
    Tolerance,
)

from . import constraints, optimizer, recommendation


class WS2OptimizerProvider:
    def __init__(self) -> None:
        version = "+".join(m.__version__ for m in (optimizer, constraints, recommendation))
        self.info = ProviderInfo(slot="optimizer", name="ws2-optimize_strategies", version=version, is_mock=False, kind="real")

    def optimize(self, baseline: BaselineBundle, constraints_: ConstraintConfig, *, assumptions: ActionAssumptions,
                 config: OptimizerConfig, simulator: SimulationFn) -> OptimizationResult:
        return optimizer.optimize_strategies(baseline, constraints_, assumptions=assumptions, config=config, simulator=simulator)

    def evaluate_constraints(self, result: SimulationResult, constraints_: ConstraintConfig) -> ConstraintEvaluation:
        return constraints.evaluate_constraints(result, constraints_)

    def recommend(self, optimization: OptimizationResult, *, risk_results: Mapping[str, RiskResult] | None = None,
                  tolerance: Tolerance = "balanced") -> RecommendationResult:
        return recommendation.recommend_strategy(optimization, risk_results=risk_results, tolerance=tolerance)
