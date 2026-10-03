"""Public contract 1.0.0 surface: types, errors, protocols, validation and serialization.

Shared C0 foundation (WS4 steward). This package currently holds only the subset that
WS2 needs; other workstreams extend it through contract PRs rather than private schemas.
"""

from src.contracts.errors import ContractValidationError, OptimizationError
from src.contracts.protocols import SimulationFn
from src.contracts.types import (
    ACTION_NAMES,
    BASELINE_MONTHLY_COLUMNS,
    CANDIDATE_COLUMNS,
    SCHEMA_VERSION,
    SIMULATION_MONTHLY_COLUMNS,
    SUPPORTED_BASELINE_HORIZONS,
    ActionAssumptions,
    ActionConfig,
    ActionCost,
    ActionCosts,
    BaselineBundle,
    BaselineTotals,
    ConstraintConfig,
    ConstraintEvaluation,
    ConstraintSatisfaction,
    OptimizationResult,
    OptimizerConfig,
    Provenance,
    RawViolations,
    RecommendationResult,
    RiskResult,
    RiskSummary,
    SimulationMetrics,
    SimulationResult,
)

__all__ = [
    "ACTION_NAMES",
    "BASELINE_MONTHLY_COLUMNS",
    "CANDIDATE_COLUMNS",
    "SCHEMA_VERSION",
    "SIMULATION_MONTHLY_COLUMNS",
    "SUPPORTED_BASELINE_HORIZONS",
    "ActionAssumptions",
    "ActionConfig",
    "ActionCost",
    "ActionCosts",
    "BaselineBundle",
    "BaselineTotals",
    "ConstraintConfig",
    "ConstraintEvaluation",
    "ConstraintSatisfaction",
    "ContractValidationError",
    "OptimizationError",
    "OptimizationResult",
    "OptimizerConfig",
    "Provenance",
    "RawViolations",
    "RecommendationResult",
    "RiskResult",
    "RiskSummary",
    "SimulationFn",
    "SimulationMetrics",
    "SimulationResult",
]
