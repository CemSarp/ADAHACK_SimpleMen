"""Company services: the domain providers bound to config/integration.json.

`overrides` replaces a slot with another provider instance (tests inject doubles this
way) or disables an optional slot with None. A required slot that cannot be built
raises; an optional one (risk, shap, benchmark) is disabled with the reason recorded
in `unavailable`. Nothing ever falls back to a mock.

When the forecast is overridden, the real simulator, risk and benchmark keep their
default config files, so a baseline is never paired with another company's assumptions.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from src.contracts import validation as val
from src.contracts.errors import ContractValidationError, ProviderConfigurationError
from src.contracts.identity import canonical_hash
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


def _domain_provider(slot: str, company: IntegrationConfig | None, forecast: object | None) -> object:
    # Imported on use: the forecasting stack imports src.integration.config (cycle), and
    # tests that override a slot never pay for building its real provider.
    if slot == "forecast":
        from src.forecasting.provider import WS1ForecastProvider

        return WS1ForecastProvider(company)
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
        from src.explainability.provider import WS1ShapProvider, create_explanation_provider
        from src.forecasting.provider import WS1ForecastProvider

        # Explain the bound forecast (e.g. an upload or another model), never a separately built one.
        return WS1ShapProvider(forecast) if isinstance(forecast, WS1ForecastProvider) else create_explanation_provider()
    from src.benchmarking.provider import create_benchmark_provider

    return create_benchmark_provider(company.benchmark if company else None)


def with_model(config: IntegrationConfig, model: str | None) -> IntegrationConfig:
    """The company config forecasting with `model` (None keeps the automatic choice)."""
    if model is None:
        return config
    return dataclasses.replace(config, ws1_modelling={**config.ws1_modelling, "model": model})


def create_services(overrides: Mapping[str, object | None] | None = None, *, model: str | None = None) -> Services:
    overrides = dict(overrides or {})
    unknown = set(overrides) - set(SLOTS)
    if unknown:
        raise ProviderConfigurationError(f"unknown provider slots {sorted(unknown)}; known: {list(SLOTS)}")
    company = None if "forecast" in overrides else with_model(IntegrationConfig.load(), model)

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
            bound[slot] = _domain_provider(slot, company, bound.get("forecast"))
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


def planning_defaults(history: pd.DataFrame) -> dict[str, float]:
    """Starting goals sized to the company, in the demo's proportions: a budget of about 8% of
    yearly revenue, a profit floor of about 80% of yearly profit and a 10% CO2 cut."""
    year = history.sort_values("timestamp").iloc[-12:]
    revenue, profit = float(year["revenue_gbp"].sum()), float(year["operating_profit_gbp"].sum())
    nice = lambda v: float(f"{v:.2g}")  # noqa: E731 - two significant figures read as a goal, not a forecast
    return {"budget_gbp": nice(0.08 * revenue), "min_total_profit_gbp": nice(0.8 * profit if profit > 0 else 1.2 * profit),
            "min_co2_reduction_ratio": 0.1, "optimizer_max_evaluations": 2048, "risk_trials": 1000}


def create_dataset_services(raw: pd.DataFrame, mapping: Mapping[str, Any], *, name: str, sha256: str,
                            model: str | None = None) -> Services:
    """Services for an uploaded table: its own forecast, and action assumptions rescaled to it.
    Risk and benchmark keep their default configuration."""
    from src.actions.calibrate import calibrate_assumptions
    from src.actions.definitions import load_action_assumptions
    from src.actions.provider import WS2SimulatorProvider
    from src.forecasting.history import ImportConfig, import_history
    from src.forecasting.provider import WS1ForecastProvider

    imported = import_history(raw, ImportConfig.from_dict(mapping), source=name, sha256=sha256)
    base = IntegrationConfig.load()
    key = canonical_hash([sha256, imported.import_config.content_hash()])[:12]
    config = with_model(dataclasses.replace(base, config_id=f"upload-{key}", input_csv=name,
                                            dashboard_defaults=planning_defaults(imported.history)), model)
    assumptions = calibrate_assumptions(imported.history, load_action_assumptions(REPO_ROOT / base.assumptions),
                                        f"upload-{key}")
    return create_services({"forecast": WS1ForecastProvider(config, imported),
                            "simulator": WS2SimulatorProvider(assumptions=assumptions)})
