from __future__ import annotations

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
