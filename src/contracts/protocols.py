"""Provider protocols bound by src/integration/services.py.

Domain signatures (simulate_strategy, optimize_strategies, ...) are fixed in
docs/SHARED_CONTRACTS.md. These protocols are the thin provider shape WS4 binds
around them so mock, fixture and real implementations are interchangeable.
Every provider exposes `info: ProviderInfo`; `info.version` must change whenever
outputs for the same inputs can change (model, assumptions, code revision).
"""

from __future__ import annotations

from typing import Literal, Mapping, Protocol, runtime_checkable

import pandas as pd

from .types import (
    ActionAssumptions,
    ActionConfig,
    BacktestReport,
    BaselineBundle,
    BenchmarkResult,
    ConstraintConfig,
    ConstraintEvaluation,
    ExplanationResult,
    OptimizationResult,
    OptimizerConfig,
    ProviderInfo,
    RecommendationResult,
    RiskConfig,
    RiskResult,
    SimulationResult,
)


class SimulationFn(Protocol):
    def __call__(
        self, baseline: BaselineBundle, config: ActionConfig, *, assumptions: ActionAssumptions
    ) -> SimulationResult: ...


@runtime_checkable
class ForecastProvider(Protocol):
    """WS1. Binds trusted model/history/driver policy; returns public objects only."""

    info: ProviderInfo
    supported_horizons: tuple[int, ...]

    def get_baseline(self, *, company_id: str, horizon_months: int) -> BaselineBundle: ...

    def get_backtest(self, *, company_id: str) -> BacktestReport | None: ...

    def get_history(self, *, company_id: str) -> pd.DataFrame | None: ...


@runtime_checkable
class SimulatorProvider(Protocol):
    """WS2. `simulate` conforms to SimulationFn and is the only action engine."""

    info: ProviderInfo

    def get_assumptions(self) -> ActionAssumptions: ...

    def simulate(
        self, baseline: BaselineBundle, config: ActionConfig, *, assumptions: ActionAssumptions
    ) -> SimulationResult: ...


@runtime_checkable
class OptimizerProvider(Protocol):
    """WS2. Search, shared constraint evaluation and recommendation policy."""

    info: ProviderInfo

    def optimize(
        self,
        baseline: BaselineBundle,
        constraints: ConstraintConfig,
        *,
        assumptions: ActionAssumptions,
        config: OptimizerConfig,
        simulator: SimulationFn,
    ) -> OptimizationResult: ...

    def evaluate_constraints(
        self, result: SimulationResult, constraints: ConstraintConfig
    ) -> ConstraintEvaluation: ...

    def recommend(
        self,
        optimization: OptimizationResult,
        *,
        risk_results: Mapping[str, RiskResult] | None = None,
        tolerance: Literal["conservative", "balanced", "aggressive"] = "balanced",
    ) -> RecommendationResult: ...


@runtime_checkable
class RiskProvider(Protocol):
    """WS3 (P1). Monte Carlo through the injected shared simulator."""

    info: ProviderInfo
    uncertainty_id: str

    def evaluate(
        self,
        baseline: BaselineBundle,
        action_config: ActionConfig,
        *,
        constraints: ConstraintConfig,
        assumptions: ActionAssumptions,
        config: RiskConfig,
        simulator: SimulationFn,
    ) -> RiskResult: ...


@runtime_checkable
class ExplanationProvider(Protocol):
    """WS1 (P1). Forecast SHAP in raw model output space."""

    info: ProviderInfo
    available_targets: tuple[str, ...]

    def explain(self, baseline: BaselineBundle) -> ExplanationResult: ...


@runtime_checkable
class BenchmarkProvider(Protocol):
    """WS3 (P1). Normalized compatible peers; failures return status=unavailable."""

    info: ProviderInfo

    def benchmark(self, baseline: BaselineBundle) -> BenchmarkResult: ...


@runtime_checkable
class NarrativeProvider(Protocol):
    """WS4 (P2, not implemented). Reserved slot so P2 needs no services rewrite."""

    info: ProviderInfo
