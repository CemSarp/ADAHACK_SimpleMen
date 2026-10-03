"""Shared pytest fixtures: WS4 provider/request fixtures and WS2 contract-object fixtures.

Both sets load from the same fixture kit (tests/fixtures/v1) through the shared
contract serializers and validators, so every test sees one schema definition.
"""

from __future__ import annotations

import os

# Every test (including subprocess and AppTest runs) uses the small WS1 walk-forward in
# tests/fixtures/integration/integration_test.json, never the production training config.
os.environ.setdefault("CARBONOPT_CONFIG", "tests/fixtures/integration/integration_test.json")

import pytest

from src.contracts.types import AnalysisRequest, ConstraintConfig, OptimizerConfig
from src.integration.services import create_services
from tests.mocks import fixtures


@pytest.fixture
def mock_services():
    return create_services(mode="mock")


@pytest.fixture
def fixture_services():
    """Strict shape stubs for every P0 slot."""
    return create_services(mode="mock", provider_overrides={"simulator": "fixture", "optimizer": "fixture"})


@pytest.fixture
def request_ok() -> AnalysisRequest:
    return AnalysisRequest(
        company_id="demo-company",
        horizon_months=12,
        constraints=fixtures.constraints(),
        optimizer_config=OptimizerConfig(seed=7, max_evaluations=96),
    )


@pytest.fixture
def request_infeasible(request_ok) -> AnalysisRequest:
    from dataclasses import replace

    return replace(request_ok, constraints=ConstraintConfig(budget_gbp=0.0, min_total_profit_gbp=1_000_000.0,
                                                              min_co2_reduction_ratio=0.2))


# ---- WS2 domain fixtures (fresh, validated objects per test) ----------------


@pytest.fixture
def baseline():
    return fixtures.baseline()


@pytest.fixture
def assumptions():
    return fixtures.assumptions()


@pytest.fixture
def example_config():
    return fixtures.action_config()


@pytest.fixture
def example_constraints():
    return fixtures.constraints()
