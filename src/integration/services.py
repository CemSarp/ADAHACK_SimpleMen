"""Company services: the domain providers bound to config/integration.json.

`overrides` replaces a slot with another provider instance (tests inject doubles this
way) or disables an optional slot with None. A required slot that cannot be built
raises; an optional one (risk, shap, benchmark) is disabled with the reason recorded
in `unavailable`. Nothing ever falls back to a mock.

When the forecast is overridden, the real simulator, risk and benchmark keep their
default config files, so a baseline is never paired with another company's assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.contracts import validation as val
from src.contracts.errors import ContractValidationError, ProviderConfigurationError
from src.contracts.protocols import (
    BenchmarkProvider,
    ExplanationProvider,
    ForecastProvider,
    OptimizerProvider,
    RiskProvider,
    SimulatorProvider,
)
from src.contracts.types import (
    ActionAssumptions,
    ActionConfig,
    BaselineBundle,
    Capabilities,
    ProviderInfo,
    SimulationResult,
)

from .config import REPO_ROOT, IntegrationConfig

REQUIRED_SLOTS: tuple[str, ...] = ("forecast", "simulator", "optimizer")
OPTIONAL_SLOTS: tuple[str, ...] = ("risk", "shap", "benchmark")
SLOTS: tuple[str, ...] = REQUIRED_SLOTS + OPTIONAL_SLOTS


@dataclass(frozen=True, eq=False)
class Services:
    forecast: ForecastProvider
    simulator: SimulatorProvider
    optimizer: OptimizerProvider
    risk: RiskProvider | None
    shap: ExplanationProvider | None
    benchmark: BenchmarkProvider | None
    assumptions: ActionAssumptions
    capabilities: Capabilities
    providers: Mapping[str, ProviderInfo]
    unavailable: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_mock(self) -> bool:
        return any(info.is_mock for info in self.providers.values())

    @property
    def mocked_slots(self) -> tuple[str, ...]:
        return tuple(slot for slot, info in self.providers.items() if info.is_mock)

    def simulate(self, baseline: BaselineBundle, config: ActionConfig) -> SimulationResult:
        """Manual what-if: the bound simulator, called directly (no training/optimization)."""
        return self.simulator.simulate(baseline, config, assumptions=self.assumptions)


def _domain_provider(slot: str, company: IntegrationConfig | None) -> object:
    # Imported on use: the forecasting stack imports src.integration.config (cycle), and
    # tests that override a slot never pay for building its real provider.
    if slot == "forecast":
        from src.forecasting.provider import create_forecast_provider

        return create_forecast_provider()
    if slot == "simulator":
        from src.actions.provider import WS2SimulatorProvider

        return WS2SimulatorProvider(REPO_ROOT / company.assumptions if company else None)
    if slot == "optimizer":
        from src.optimization.provider import WS2OptimizerProvider

        return WS2OptimizerProvider()
    if slot == "risk":
        from src.risk.provider import create_risk_provider

        return create_risk_provider(REPO_ROOT / company.uncertainty if company else None)
    if slot == "shap":
        from src.explainability.provider import create_explanation_provider

        return create_explanation_provider()
    from src.benchmarking.provider import create_benchmark_provider

    return create_benchmark_provider(company.benchmark if company else None)


def create_services(overrides: Mapping[str, object | None] | None = None) -> Services:
    overrides = dict(overrides or {})
    unknown = set(overrides) - set(SLOTS)
    if unknown:
        raise ProviderConfigurationError(f"unknown provider slots {sorted(unknown)}; known: {list(SLOTS)}")
    company = None if "forecast" in overrides else IntegrationConfig.load()

    bound: dict[str, Any] = {}
    unavailable: dict[str, str] = {}
    for slot in SLOTS:
        if slot in overrides:
            bound[slot] = overrides[slot]
            if bound[slot] is None:
                if slot in REQUIRED_SLOTS:
                    raise ProviderConfigurationError(f"required slot {slot!r} cannot be disabled")
                unavailable[slot] = "disabled by configuration"
            continue
        try:
            bound[slot] = _domain_provider(slot, company)
        except (ContractValidationError, ImportError) as exc:
            if slot in REQUIRED_SLOTS:
                raise
            bound[slot] = None
            unavailable[slot] = str(exc)

    assumptions = val.validate_assumptions(bound["simulator"].get_assumptions())
    providers = {slot: p.info for slot, p in bound.items() if p is not None}
    shap = bound["shap"]
    capabilities = Capabilities(
        supported_horizons=tuple(bound["forecast"].supported_horizons),
        risk_available=bound["risk"] is not None,
        shap_available_targets=tuple(shap.available_targets) if shap is not None else (),
        benchmark_available=bound["benchmark"] is not None,
        # The three tolerance policies need a risk provider and WS2's real recommendation
        # policy (test-double optimizers ignore risk results).
        scenario_compare_available=bound["risk"] is not None and providers["optimizer"].kind == "real",
        is_mock={slot: info.is_mock for slot, info in providers.items()},
    )
    if not capabilities.scenario_compare_available:
        unavailable.setdefault("scenario_compare", "needs a risk provider and WS2's real recommendation policy")
    return Services(**{slot: bound[slot] for slot in SLOTS}, assumptions=assumptions, capabilities=capabilities,
                    providers=providers, unavailable=unavailable)
