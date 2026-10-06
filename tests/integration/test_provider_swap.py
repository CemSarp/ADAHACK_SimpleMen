"""Services binding: per-slot overrides, required vs optional slots, no mock fallback."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.actions import engine
from src.contracts import serialization as ser
from src.contracts.errors import ContractValidationError, ProviderConfigurationError
from src.contracts.types import ProviderInfo
from src.dashboard import charts
from src.integration import create_services, run_analysis
from tests.mocks import make_services
from tests.mocks.behavioral import BehavioralMockOptimizer, BehavioralMockSimulator
from tests.mocks.fixture_providers import FixtureForecastProvider


def _as_real(provider, slot: str):
    """Relabel a double as non-mock to exercise real-provider wiring only."""
    provider.info = ProviderInfo(slot=slot, name=f"stand-in-{slot}", version="test", is_mock=False, kind="custom")
    return provider


def test_override_validation():
    with pytest.raises(ProviderConfigurationError, match="unknown provider slots"):
        create_services({"llm": object()})
    with pytest.raises(ProviderConfigurationError, match="cannot be disabled"):
        create_services({"forecast": FixtureForecastProvider(), "optimizer": None})


def test_invalid_company_config_stops_startup(monkeypatch):
    monkeypatch.setenv("CARBONOPT_CONFIG", "config/does-not-exist.json")
    with pytest.raises(ContractValidationError, match="integration_config"):
        create_services()


def test_mock_services_expose_capabilities_and_provenance(mock_services):
    caps = mock_services.capabilities
    assert caps.supported_horizons == (12,)
    assert caps.risk_available and caps.benchmark_available and caps.shap_available_targets
    assert not caps.scenario_compare_available
    assert all(caps.is_mock.values()) and mock_services.is_mock


def test_injected_required_providers_bind_with_real_optional_ones(request_ok):
    services = create_services({
        "forecast": _as_real(FixtureForecastProvider(), "forecast"),
        "simulator": _as_real(BehavioralMockSimulator(), "simulator"),
        "optimizer": _as_real(BehavioralMockOptimizer(), "optimizer"),
    })
    # SHAP is WS1's tree explainer: bound, and it refuses to explain a baseline that was not
    # produced by its own trained model (checked before any training).
    assert services.providers["shap"].kind == "real"
    assert services.capabilities.risk_available and services.providers["risk"].kind == "real"
    assert services.capabilities.benchmark_available and services.providers["benchmark"].kind == "real"
    bundle = run_analysis(replace(request_ok, risk_enabled=True), services=services)
    assert not services.is_mock and set(bundle.providers) == {"forecast", "simulator", "optimizer", "risk"}
    assert bundle.risk_results and not any("Risk is unavailable" in w for w in bundle.warnings)
    explained = run_analysis(replace(request_ok, explanation_enabled=True), services=services)
    assert explained.explanation is None and any("is not the explained WS1 model" in w for w in explained.warnings)


def test_domain_ws2_providers_use_demo_assumptions_beside_a_fixture_forecast(request_ok):
    services = make_services({"simulator": "real", "optimizer": "real"})
    assert services.providers["simulator"].version == f"{engine.__version__}+demo-actions-v1@1.0.0"
    assert services.providers["optimizer"].kind == "real"
    assert services.assumptions.assumptions_id == "demo-actions-v1"
    bundle = run_analysis(request_ok, services=services)
    # Forecast is still a fixture: the whole bundle stays labelled mock.
    assert bundle.provenance.is_mock
    assert {s: i.is_mock for s, i in bundle.providers.items()} == {"forecast": True, "simulator": False, "optimizer": False}


def test_swap_changes_provenance_not_consumer_code(mock_services, request_ok):
    a = run_analysis(request_ok, services=mock_services)
    b = run_analysis(request_ok, services=make_services({"simulator": "real"}))
    for bundle in (a, b):
        # Identical consumer code paths: serialization and charts.
        ser.to_json(bundle)
        sid = bundle.recommendation.strategy_id
        charts.pareto_scatter(bundle.optimization, bundle.baseline, selected_id=sid, recommended_id=sid)
        charts.scope_totals(bundle.baseline, {"selected": bundle.optimization.strategies[sid]})
    assert a.providers["simulator"].kind == "behavioral-mock" and b.providers["simulator"].kind == "real"
    assert list(a.optimization.pareto.columns) == list(b.optimization.pareto.columns)


def test_missing_assumptions_file_stops_startup(monkeypatch, tmp_path):
    from src.actions import definitions

    monkeypatch.setattr(definitions, "DEFAULT_ASSUMPTIONS_PATH", tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        make_services({"simulator": "real"})


def test_optional_provider_that_cannot_bind_is_disabled(monkeypatch):
    import src.explainability.provider as shap_provider

    def missing(*args, **kwargs):
        raise ImportError("No module named 'shap'")

    monkeypatch.setattr(shap_provider, "create_explanation_provider", missing)
    services = make_services({"shap": "real"})
    assert services.shap is None and services.capabilities.shap_available_targets == ()
    assert "shap" in services.unavailable["shap"]
    assert services.forecast is not None  # required slots unaffected
