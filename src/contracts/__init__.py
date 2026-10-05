"""Public contracts (version 1.0.0). Consumers import from here.

Importing this package must not require Streamlit, optional libraries, model
files or network access.
"""

from .errors import (
    CapabilityUnavailable,
    CarbonOptError,
    ContractValidationError,
    ForecastError,
    OptimizationError,
    ProviderConfigurationError,
    ProviderError,
    RiskError,
    SimulationError,
    UnsupportedHorizon,
    UnsupportedMockInput,
)
from .identity import canonical_hash, compute_strategy_id, config_from_row
from .protocols import (
    BenchmarkProvider,
    ExplanationProvider,
    ForecastProvider,
    OptimizerProvider,
    RiskProvider,
    SimulationFn,
    SimulatorProvider,
)
from .types import (
    ACTION_NAMES,
    SCHEMA_VERSION,
    ActionAssumptions,
    ActionConfig,
    ActionCost,
    AnalysisBundle,
    AnalysisRequest,
    BacktestReport,
    BaselineBundle,
    BenchmarkResult,
    Capabilities,
    ConstraintConfig,
    ConstraintEvaluation,
    ExplanationResult,
    OptimizationResult,
    OptimizerConfig,
    Provenance,
    ProviderInfo,
    RecommendationResult,
    RiskConfig,
    RiskResult,
    SimulationResult,
    ToolResult,
)

__all__ = [name for name in dir() if not name.startswith("_")]
