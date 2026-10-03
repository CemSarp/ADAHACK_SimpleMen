"""Adapters that bind real WS1-WS3 implementations to provider protocols.

Discovery is lazy: nothing here imports a domain module until real or hybrid
wiring asks for it. A missing module or dependency yields ProviderUnavailable
with a reason; services.py turns that into a configuration error for P0 slots
or a disabled capability for optional ones. There is never a mock fallback.

Entry points (repo-relative modules):
  simulator  src.actions.engine.simulate_strategy  + config/action_assumptions.json
  optimizer  src.optimization.optimizer.optimize_strategies
             src.optimization.constraints.evaluate_constraints
             src.optimization.recommendation.recommend_strategy
  forecast   src.forecasting.provider.create_forecast_provider()   (WS1 ml_core via CSV import adapter)
  risk       src.risk.provider.create_risk_provider(path)          (WS3)
  benchmark  src.benchmarking.provider.create_benchmark_provider(path) (WS3)
  shap       src.explainability.provider.create_explanation_provider() (WS1 trees via shap)

Company binding: when the forecast slot is the real CSV-backed WS1 provider,
the simulator, risk and benchmark providers load the company-specific files
named in config/integration.json (assumptions, uncertainty, benchmark). With a
fixture forecast they keep the demo files, so a baseline is never paired with
another company's assumptions.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from src.contracts import serialization as ser
from src.contracts import validation as val
from src.contracts.errors import ContractValidationError
from src.contracts.types import (
    ActionAssumptions,
    ActionConfig,
    BaselineBundle,
    ConstraintConfig,
    ConstraintEvaluation,
    OptimizationResult,
    OptimizerConfig,
    ProviderInfo,
    RecommendationResult,
    RiskResult,
    SimulationResult,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_ASSUMPTIONS_PATH = Path("config") / "action_assumptions.json"


class ProviderUnavailable(Exception):
    """A real provider cannot be bound. Carries a human-readable reason."""


def _load_attr(module_name: str, attr: str) -> Any:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and (module_name == exc.name or module_name.startswith(exc.name + ".")):
            raise ProviderUnavailable(f"{module_name} is not implemented yet") from exc
        raise ProviderUnavailable(f"{module_name} needs a missing dependency: {exc.name}") from exc
    except ImportError as exc:
        raise ProviderUnavailable(f"{module_name} failed to import: {exc}") from exc
    if not hasattr(module, attr):
        raise ProviderUnavailable(f"{module_name} does not define {attr}()")
    return getattr(module, attr)


def _module_version(module_name: str) -> str:
    module = importlib.import_module(module_name)
    return str(getattr(module, "__version__", "unversioned"))


def load_action_assumptions(path: Path | None = None) -> ActionAssumptions:
    target = REPO_ROOT / (path or ACTION_ASSUMPTIONS_PATH)
    if not target.exists():
        raise ProviderUnavailable(f"{(path or ACTION_ASSUMPTIONS_PATH).as_posix()} is missing (WS2 owns this file)")
    data = json.loads(target.read_text())
    return val.validate_assumptions(ser.assumptions_from_dict(data))


class RealSimulatorProvider:
    MODULE = "src.actions.engine"

    def __init__(self, assumptions_path: Path | None = None) -> None:
        self._simulate: Callable[..., SimulationResult] = _load_attr(self.MODULE, "simulate_strategy")
        self._assumptions = load_action_assumptions(assumptions_path)
        a = self._assumptions
        self.info = ProviderInfo(
            slot="simulator",
            name="ws2-simulate_strategy",
            version=f"{_module_version(self.MODULE)}+{a.assumptions_id}@{a.version}",
            is_mock=False,
            kind="real",
        )

    def get_assumptions(self) -> ActionAssumptions:
        return self._assumptions

    def simulate(self, baseline: BaselineBundle, config: ActionConfig, *, assumptions: ActionAssumptions) -> SimulationResult:
        return self._simulate(baseline, config, assumptions=assumptions)


class RealOptimizerProvider:
    def __init__(self) -> None:
        self._optimize = _load_attr("src.optimization.optimizer", "optimize_strategies")
        self._constraints = _load_attr("src.optimization.constraints", "evaluate_constraints")
        self._recommend = _load_attr("src.optimization.recommendation", "recommend_strategy")
        version = "+".join(
            _module_version(m)
            for m in ("src.optimization.optimizer", "src.optimization.constraints", "src.optimization.recommendation")
        )
        self.info = ProviderInfo(slot="optimizer", name="ws2-optimize_strategies", version=version, is_mock=False, kind="real")

    def optimize(
        self,
        baseline: BaselineBundle,
        constraints: ConstraintConfig,
        *,
        assumptions: ActionAssumptions,
        config: OptimizerConfig,
        simulator: Callable[..., SimulationResult],
    ) -> OptimizationResult:
        return self._optimize(baseline, constraints, assumptions=assumptions, config=config, simulator=simulator)

    def evaluate_constraints(self, result: SimulationResult, constraints: ConstraintConfig) -> ConstraintEvaluation:
        return self._constraints(result, constraints)

    def recommend(
        self,
        optimization: OptimizationResult,
        *,
        risk_results: Mapping[str, RiskResult] | None = None,
        tolerance: Literal["conservative", "balanced", "aggressive"] = "balanced",
    ) -> RecommendationResult:
        return self._recommend(optimization, risk_results=risk_results, tolerance=tolerance)


def _factory_provider(module_name: str, factory: str, *args: Any) -> object:
    create = _load_attr(module_name, factory)
    try:
        provider = create(*args)
    except ContractValidationError as exc:  # defined config failure only; other errors surface
        raise ProviderUnavailable(f"{module_name}.{factory}() configuration is invalid: {exc}") from exc
    info = getattr(provider, "info", None)
    if not isinstance(info, ProviderInfo):
        raise ProviderUnavailable(f"{module_name}.{factory}() must return a provider with info: ProviderInfo")
    if info.is_mock:
        raise ProviderUnavailable(f"{module_name}.{factory}() returned a mock provider; real mode never binds mocks")
    return provider


def _company_config() -> Any:
    from .config import IntegrationConfig

    try:
        return IntegrationConfig.load()
    except ContractValidationError as exc:
        raise ProviderUnavailable(f"integration config is invalid: {exc}") from exc


def create_real_provider(slot: str, *, company_bound: bool = False) -> object:
    """Bind the real provider for `slot`; `company_bound` selects the CSV company's files."""
    company = _company_config() if company_bound else None
    if slot == "forecast":
        return _factory_provider("src.forecasting.provider", "create_forecast_provider")
    if slot == "simulator":
        return RealSimulatorProvider(Path(company.assumptions) if company else None)
    if slot == "optimizer":
        return RealOptimizerProvider()
    if slot == "risk":
        # WS3's loader resolves relative paths against the working directory; pass a repo-rooted path.
        return _factory_provider("src.risk.provider", "create_risk_provider",
                                 *([REPO_ROOT / company.uncertainty] if company else []))
    if slot == "shap":
        return _factory_provider("src.explainability.provider", "create_explanation_provider")
    if slot == "benchmark":
        return _factory_provider("src.benchmarking.provider", "create_benchmark_provider",
                                 *([company.benchmark] if company else []))
    raise ProviderUnavailable(f"no real provider is defined for slot {slot!r}")
