"""Development/test doubles. Imported by src/integration/services.py only in
mock or hybrid mode; real mode never imports this package."""

from __future__ import annotations

from typing import Callable

from .behavioral import BehavioralMockOptimizer, BehavioralMockSimulator
from .fixture_providers import (
    FixtureBenchmarkProvider,
    FixtureExplanationProvider,
    FixtureForecastProvider,
    FixtureOptimizerProvider,
    FixtureRiskProvider,
    FixtureSimulatorProvider,
)

# slot -> variant -> factory. The first variant listed is the default for "mock".
MOCK_FACTORIES: dict[str, dict[str, Callable[[], object]]] = {
    "forecast": {"fixture": FixtureForecastProvider},
    "simulator": {"behavioral": BehavioralMockSimulator, "fixture": FixtureSimulatorProvider},
    "optimizer": {"behavioral": BehavioralMockOptimizer, "fixture": FixtureOptimizerProvider},
    "risk": {"fixture": FixtureRiskProvider},
    "shap": {"fixture": FixtureExplanationProvider},
    "benchmark": {"fixture": FixtureBenchmarkProvider},
}


def create_mock_provider(slot: str, variant: str | None = None) -> object:
    variants = MOCK_FACTORIES.get(slot)
    if not variants:
        raise KeyError(f"no mock provider for slot {slot!r}")
    if variant is None:
        variant = next(iter(variants))
    if variant not in variants:
        raise KeyError(f"no {variant!r} mock for slot {slot!r}; available: {sorted(variants)}")
    return variants[variant]()
