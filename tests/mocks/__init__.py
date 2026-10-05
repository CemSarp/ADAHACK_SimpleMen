"""Test doubles and `make_services`, the one way tests bind them into Services."""

from __future__ import annotations

from typing import Callable, Mapping

from src.integration.services import SLOTS, create_services

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


def make_services(overrides: Mapping[str, object] | None = None):
    """Services with every slot mocked unless overridden. Per slot: a provider instance,
    "mock" (default variant), a variant name ("fixture", "behavioral"), "real" for the
    domain provider, or "disabled"."""
    overrides = dict(overrides or {})
    resolved: dict[str, object | None] = {}
    for slot in (*SLOTS, *(s for s in overrides if s not in SLOTS)):
        choice = overrides.get(slot, "mock")
        if choice == "real":
            continue
        if choice == "disabled":
            resolved[slot] = None
        elif isinstance(choice, str):
            resolved[slot] = create_mock_provider(slot, None if choice == "mock" else choice)
        else:
            resolved[slot] = choice
    return create_services(resolved)


# Regression-test wiring for the fixture company and domain engines.
FIXTURE_DOMAIN_OVERRIDES = {
    "forecast": "fixture", "simulator": "real", "optimizer": "real",
    "risk": "real", "shap": "disabled", "benchmark": "real",
}
