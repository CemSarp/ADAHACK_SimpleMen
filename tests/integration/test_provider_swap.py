"""Provider registry: mock/real/hybrid substitution, overrides and real discovery.

Real WS1-WS3 modules do not exist yet, so discovery is exercised with stand-in
modules injected into sys.modules. The stand-ins wrap test doubles and only
prove wiring; they are not domain implementations.
"""

from __future__ import annotations

import json
import sys
import types
from dataclasses import replace

import pytest

from src.contracts import serialization as ser
from src.contracts.errors import ProviderConfigurationError
from src.contracts.types import ProviderInfo
from src.dashboard import charts
from src.integration import create_services, real_providers, run_analysis
from tests.mocks import fixtures
from tests.mocks.behavioral import BehavioralMockOptimizer, BehavioralMockSimulator, mock_evaluate_constraints
from tests.mocks.fixture_providers import FixtureForecastProvider


def _as_real(provider, slot: str):
    """Relabel a double as non-mock to exercise real-mode wiring only."""
    provider.info = ProviderInfo(slot=slot, name=f"stand-in-{slot}", version="test", is_mock=False, kind="custom")
    return provider


@pytest.fixture
def fake_ws2(monkeypatch, tmp_path):
    """Stand-in src.actions.engine / src.optimization.* modules + config file."""
    sim, opt = BehavioralMockSimulator(), BehavioralMockOptimizer()
    modules = {
        "src.actions": types.ModuleType("src.actions"),
        "src.actions.engine": types.ModuleType("src.actions.engine"),
        "src.optimization": types.ModuleType("src.optimization"),
        "src.optimization.optimizer": types.ModuleType("src.optimization.optimizer"),
        "src.optimization.constraints": types.ModuleType("src.optimization.constraints"),
        "src.optimization.recommendation": types.ModuleType("src.optimization.recommendation"),
    }
    modules["src.actions.engine"].simulate_strategy = lambda b, c, *, assumptions: sim.simulate(b, c, assumptions=assumptions)
    modules["src.actions.engine"].__version__ = "stand-in-0"
    modules["src.optimization.optimizer"].optimize_strategies = opt.optimize
    modules["src.optimization.constraints"].evaluate_constraints = mock_evaluate_constraints
    modules["src.optimization.recommendation"].recommend_strategy = opt.recommend
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "action_assumptions.json").write_text(json.dumps(fixtures.load_json("action_assumptions.json")))
    monkeypatch.setattr(real_providers, "REPO_ROOT", tmp_path)
    return modules


def test_real_mode_names_the_missing_ws1_forecast_provider():
    # WS2 publishes its simulator/optimizer; WS1's forecast factory does not exist yet.
    with pytest.raises(ProviderConfigurationError) as exc:
        create_services(mode="real")
    assert set(exc.value.missing) == {"forecast"}
    assert "src.forecasting.provider is not implemented yet" in str(exc.value)


def test_mode_and_override_validation():
    with pytest.raises(ProviderConfigurationError, match="hybrid mode requires"):
        create_services(mode="hybrid")
    with pytest.raises(ProviderConfigurationError, match="use hybrid"):
        create_services(mode="mock", provider_overrides={"simulator": "real"})
    with pytest.raises(ProviderConfigurationError, match="use hybrid"):
        create_services(mode="real", provider_overrides={"simulator": "mock"})
    with pytest.raises(ProviderConfigurationError, match="cannot bind mock provider"):
        create_services(mode="real", provider_overrides={"simulator": BehavioralMockSimulator()})
    with pytest.raises(ProviderConfigurationError, match="cannot be disabled"):
        create_services(mode="mock", provider_overrides={"optimizer": "disabled"})
    with pytest.raises(ProviderConfigurationError, match="unknown provider slots"):
        create_services(mode="mock", provider_overrides={"llm": "mock"})
    with pytest.raises(ProviderConfigurationError, match="does not implement"):
        create_services(mode="mock", provider_overrides={"simulator": object()})
    with pytest.raises(ProviderConfigurationError, match="unknown provider mode"):
        create_services(mode="production")


def test_mock_services_expose_capabilities_and_provenance(mock_services):
    caps = mock_services.capabilities
    assert caps.supported_horizons == (12,)
    assert caps.risk_available and caps.benchmark_available and caps.shap_available_targets
    assert not caps.narrative_available and not caps.scenario_compare_available
    assert all(caps.is_mock.values()) and mock_services.is_mock


def test_real_mode_binds_injected_non_mock_providers(request_ok):
    services = create_services(mode="real", provider_overrides={
        "forecast": _as_real(FixtureForecastProvider(), "forecast"),
        "simulator": _as_real(BehavioralMockSimulator(), "simulator"),
        "optimizer": _as_real(BehavioralMockOptimizer(), "optimizer"),
    })
    # Optional slots without real providers are disabled, never mocked. WS3 risk and benchmark now exist.
    assert services.shap is None
    assert "not implemented yet" in services.unavailable["shap"]
    assert services.capabilities.risk_available and services.providers["risk"].kind == "real"
    assert services.capabilities.benchmark_available and services.providers["benchmark"].kind == "real"
    bundle = run_analysis(replace(request_ok, risk_enabled=True), services=services)
    assert not services.is_mock and set(bundle.providers) == {"forecast", "simulator", "optimizer", "risk"}
    assert bundle.risk_results and not any("Risk is unavailable" in w for w in bundle.warnings)


def test_real_discovery_wraps_documented_ws2_signatures(fake_ws2, request_ok):
    services = create_services(mode="hybrid", provider_overrides={"simulator": "real", "optimizer": "real"})
    assert services.providers["simulator"].kind == "real"
    assert services.providers["simulator"].version == "stand-in-0+demo-actions-v1@1.0.0"
    assert services.providers["optimizer"].kind == "real"
    assert services.assumptions.assumptions_id == "demo-actions-v1"
    bundle = run_analysis(request_ok, services=services)
    # Forecast is still a fixture: the whole bundle stays labelled mock.
    assert bundle.provenance.is_mock
    assert {s: i.is_mock for s, i in bundle.providers.items()} == {"forecast": True, "simulator": False, "optimizer": False}


def test_swap_changes_provenance_not_consumer_code(fake_ws2, mock_services, request_ok):
    hybrid = create_services(mode="hybrid", provider_overrides={"simulator": "real"})
    a = run_analysis(request_ok, services=mock_services)
    b = run_analysis(request_ok, services=hybrid)
    for bundle in (a, b):
        # Identical consumer code paths: serialization and charts.
        ser.to_json(bundle)
        sid = bundle.recommendation.strategy_id
        charts.pareto_scatter(bundle.optimization, bundle.baseline, selected_id=sid, recommended_id=sid)
        charts.monthly_comparison(bundle.baseline, {"selected": bundle.optimization.strategies[sid]})
    assert a.providers["simulator"].kind == "behavioral-mock" and b.providers["simulator"].kind == "real"
    assert list(a.optimization.pareto.columns) == list(b.optimization.pareto.columns)


def test_missing_assumptions_file_is_a_configuration_error(fake_ws2, monkeypatch, tmp_path):
    (tmp_path / "config" / "action_assumptions.json").unlink()
    with pytest.raises(ProviderConfigurationError, match="action_assumptions.json is missing"):
        create_services(mode="hybrid", provider_overrides={"simulator": "real"})


def test_failed_real_p0_provider_never_falls_back_to_mock():
    # The WS1 forecast is the P0 slot without a real provider: asking for it must fail, not mock.
    with pytest.raises(ProviderConfigurationError, match="forecast"):
        create_services(mode="hybrid", provider_overrides={"forecast": "real", "simulator": "real", "optimizer": "real"})


def test_optional_real_provider_with_missing_dependency_is_disabled(monkeypatch):
    original = real_providers.importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "src.explainability.provider":
            raise ModuleNotFoundError("No module named 'shap'", name="shap")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(real_providers.importlib, "import_module", fake_import)
    services = create_services(mode="hybrid", provider_overrides={"shap": "real"})
    assert services.shap is None and services.capabilities.shap_available_targets == ()
    assert "missing dependency: shap" in services.unavailable["shap"]
    assert services.forecast is not None  # P0 unaffected


def test_real_factory_returning_mock_is_rejected(monkeypatch):
    module = types.ModuleType("src.benchmarking.provider")
    from tests.mocks.fixture_providers import FixtureBenchmarkProvider

    module.create_benchmark_provider = FixtureBenchmarkProvider
    monkeypatch.setitem(sys.modules, "src.benchmarking", types.ModuleType("src.benchmarking"))
    monkeypatch.setitem(sys.modules, "src.benchmarking.provider", module)
    services = create_services(mode="hybrid", provider_overrides={"benchmark": "real"})
    assert services.benchmark is None
    assert "returned a mock provider" in services.unavailable["benchmark"]
