"""Company service registry, defaulting to the integrated domain implementations.

Explicit mock/hybrid wiring below is retained for regression tests and dependency
injection. There are no product presets or environment-selected modes.

Modes (docs/INTEGRATION_GUIDE.md section 2):
  mock    every slot bound to a development/test double from tests/mocks.
  real    every slot bound to a real domain provider. A missing P0 provider
          (forecast, simulator, optimizer) raises ProviderConfigurationError;
          a missing optional provider disables that capability. Mock providers
          are rejected.
  hybrid  mock defaults plus explicit per-slot overrides; provenance shows
          exactly which outputs are mocked. Requires at least one override.

Override values per slot: "real", "mock" (default mock variant), a named mock
variant ("fixture", "behavioral"), "disabled" (optional slots only), or a
provider instance satisfying the slot protocol. Nothing ever falls back from
real to mock silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from src.contracts import validation as val
from src.contracts.errors import ProviderConfigurationError
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

from .real_providers import ProviderUnavailable, create_real_provider

P0_SLOTS: tuple[str, ...] = ("forecast", "simulator", "optimizer")
OPTIONAL_SLOTS: tuple[str, ...] = ("risk", "shap", "benchmark", "narrative")
ALL_SLOTS: tuple[str, ...] = P0_SLOTS + OPTIONAL_SLOTS
SLOT_PROTOCOLS: Mapping[str, type] = {
    "forecast": ForecastProvider,
    "simulator": SimulatorProvider,
    "optimizer": OptimizerProvider,
    "risk": RiskProvider,
    "shap": ExplanationProvider,
    "benchmark": BenchmarkProvider,
}
MOCK_VARIANT_NAMES: tuple[str, ...] = ("mock", "fixture", "behavioral")

Mode = Literal["mock", "real", "hybrid"]

#: Human-readable owner/kind labels for the provenance line ("Baseline: fixture · Simulator: WS2 ...").
SLOT_LABELS: Mapping[str, str] = {
    "forecast": "Baseline",
    "simulator": "Simulator",
    "optimizer": "Optimizer",
    "risk": "Risk",
    "shap": "SHAP",
    "benchmark": "Benchmark",
}
REAL_OWNERS: Mapping[str, str] = {
    "forecast": "WS1", "simulator": "WS2", "optimizer": "WS2", "risk": "WS3", "shap": "WS1", "benchmark": "WS3",
}


@dataclass(frozen=True, eq=False)
class Services:
    mode: str
    forecast: Any
    simulator: Any
    optimizer: Any
    risk: Any | None
    shap: Any | None
    benchmark: Any | None
    narrative: Any | None
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

    def provenance_summary(self) -> str:
        """One line naming every provider's source, e.g.
        "Baseline: fixture · Simulator: WS2 · Optimizer: WS2 · Risk: unavailable · ..."."""
        parts = []
        for slot, label in SLOT_LABELS.items():
            info = self.providers.get(slot)
            if info is None:
                parts.append(f"{label}: unavailable")
            elif info.is_mock:
                parts.append(f"{label}: {'fixture' if info.kind == 'fixture' else 'mock (' + info.kind + ')'}")
            else:
                parts.append(f"{label}: {REAL_OWNERS.get(slot, 'real') if info.kind == 'real' else info.kind}")
        return " · ".join(parts)

    def simulate(self, baseline: BaselineBundle, config: ActionConfig) -> SimulationResult:
        """Manual what-if: the bound simulator, called directly (no training/optimization)."""
        return self.simulator.simulate(baseline, config, assumptions=self.assumptions)


def _bind_mock(slot: str, variant: str) -> object:
    try:
        from tests.mocks import create_mock_provider  # development doubles; never used in real mode
    except ImportError as exc:  # pragma: no cover - only when tests/ is not shipped
        raise ProviderConfigurationError(f"mock providers are unavailable: {exc}") from exc
    try:
        return create_mock_provider(slot, None if variant == "mock" else variant)
    except KeyError as exc:
        raise ProviderConfigurationError(str(exc.args[0])) from exc


def _check_instance(slot: str, provider: object, mode: str) -> object:
    protocol = SLOT_PROTOCOLS.get(slot)
    if protocol is not None and not isinstance(provider, protocol):
        raise ProviderConfigurationError(f"override for {slot!r} does not implement {protocol.__name__}")
    info = getattr(provider, "info", None)
    if not isinstance(info, ProviderInfo):
        raise ProviderConfigurationError(f"override for {slot!r} must expose info: ProviderInfo")
    if mode == "real" and info.is_mock:
        raise ProviderConfigurationError(f"real mode cannot bind mock provider {info.name!r} to {slot!r}; use hybrid mode")
    return provider


def create_services(*, mode: Mode = "real", provider_overrides: Mapping[str, object] | None = None) -> Services:
    """Bind the company's domain services by default.

    Explicit modes and overrides remain a regression-test injection seam; the
    application does not expose or read a mode setting.
    """
    if mode not in ("mock", "real", "hybrid"):
        raise ProviderConfigurationError(f"unknown provider mode {mode!r}; use mock, real or hybrid")
    overrides = dict(provider_overrides or {})
    unknown = set(overrides) - set(ALL_SLOTS)
    if unknown:
        raise ProviderConfigurationError(f"unknown provider slots {sorted(unknown)}; known: {list(ALL_SLOTS)}")
    if mode == "hybrid" and not overrides:
        raise ProviderConfigurationError("hybrid mode requires explicit provider_overrides")

    bound: dict[str, object | None] = {}
    unavailable: dict[str, str] = {}
    missing_p0: list[str] = []
    # The real WS1 forecast is the CSV company; its real WS2/WS3 partners must use that company's files.
    company_bound = overrides.get("forecast", "real" if mode == "real" else "mock") == "real"
    for slot in ALL_SLOTS:
        choice = overrides.get(slot, "real" if mode == "real" else "mock")
        if slot == "narrative":
            # P2 narrative provider is not implemented; only an explicit instance binds.
            bound[slot] = choice if not isinstance(choice, str) else None
            if bound[slot] is None:
                unavailable[slot] = "P2 narrative/chat is not implemented in this release"
            continue
        if not isinstance(choice, str):
            bound[slot] = _check_instance(slot, choice, mode)
            continue
        if choice == "disabled":
            if slot in P0_SLOTS:
                raise ProviderConfigurationError(f"P0 slot {slot!r} cannot be disabled")
            bound[slot] = None
            unavailable[slot] = "disabled by configuration"
        elif choice == "real":
            if mode == "mock":
                raise ProviderConfigurationError(f"mock mode cannot bind real provider for {slot!r}; use hybrid mode")
            try:
                bound[slot] = _check_instance(slot, create_real_provider(slot, company_bound=company_bound), mode)
            except ProviderUnavailable as exc:
                bound[slot] = None
                unavailable[slot] = str(exc)
                if slot in P0_SLOTS:
                    missing_p0.append(f"{slot}: {exc}")
        elif choice in MOCK_VARIANT_NAMES:
            if mode == "real":
                raise ProviderConfigurationError(f"real mode cannot bind a mock for {slot!r}; use hybrid mode")
            bound[slot] = _check_instance(slot, _bind_mock(slot, choice), mode)
        else:
            raise ProviderConfigurationError(f"unknown provider choice {choice!r} for slot {slot!r}")

    if missing_p0:
        raise ProviderConfigurationError(
            "required P0 providers are not available in "
            f"{mode} mode: " + "; ".join(missing_p0) + ". Use mode='mock' for development or "
            "mode='hybrid' with explicit overrides.",
            missing=tuple(s.split(":", 1)[0] for s in missing_p0),
        )

    assumptions = val.validate_assumptions(bound["simulator"].get_assumptions())
    providers = {slot: p.info for slot, p in bound.items() if p is not None}
    forecast = bound["forecast"]
    shap = bound["shap"]
    capabilities = Capabilities(
        supported_horizons=tuple(forecast.supported_horizons),
        risk_available=bound["risk"] is not None,
        shap_available_targets=tuple(shap.available_targets) if shap is not None else (),
        benchmark_available=bound["benchmark"] is not None,
        narrative_available=bound["narrative"] is not None,
        # C6: the three tolerance policies need a bound risk provider and an optimizer whose
        # recommendation policy consumes risk results (WS2's real policy; the mock ignores risk).
        scenario_compare_available=bound["risk"] is not None and providers["optimizer"].kind == "real",
        is_mock={slot: info.is_mock for slot, info in providers.items()},
    )
    if not capabilities.scenario_compare_available:
        unavailable.setdefault("scenario_compare", "needs a risk provider and WS2's real recommendation policy "
                               "(the mock optimizer ignores risk results)")
    return Services(
        mode=mode,
        forecast=forecast,
        simulator=bound["simulator"],
        optimizer=bound["optimizer"],
        risk=bound["risk"],
        shap=shap,
        benchmark=bound["benchmark"],
        narrative=bound["narrative"],
        assumptions=assumptions,
        capabilities=capabilities,
        providers=providers,
        unavailable=unavailable,
    )
