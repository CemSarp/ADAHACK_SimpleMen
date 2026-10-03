"""WS3 risk provider factory discovered by src.integration.real_providers.

The provider binds one UncertaintySpec and delegates to evaluate_strategy_risk.
`info.is_mock` is False (this is the implemented Monte Carlo); each RiskResult
still carries `provenance.is_mock` from the injected simulator.
"""

from __future__ import annotations

from pathlib import Path

from src.contracts.protocols import SimulationFn
from src.contracts.types import (
    ActionAssumptions,
    ActionConfig,
    BaselineBundle,
    ConstraintConfig,
    ProviderInfo,
    RiskConfig,
    RiskResult,
)

from .monte_carlo import DEFAULT_UNCERTAINTY_PATH, PROVIDER_NAME, UncertaintySpec, evaluate_strategy_risk, load_uncertainty

__version__ = "ws3-risk-1"


class MonteCarloRiskProvider:
    def __init__(self, uncertainty: UncertaintySpec) -> None:
        self._uncertainty = uncertainty
        self.uncertainty_id = uncertainty.uncertainty_id
        self.info = ProviderInfo(
            slot="risk",
            name=PROVIDER_NAME,
            # Content hash: any bound-uncertainty change invalidates cached analyses.
            version=f"{__version__}+{uncertainty.uncertainty_id}@{uncertainty.content_hash()[:16]}",
            is_mock=False,
            kind="real",
        )

    def evaluate(
        self,
        baseline: BaselineBundle,
        action_config: ActionConfig,
        *,
        constraints: ConstraintConfig,
        assumptions: ActionAssumptions,
        config: RiskConfig,
        simulator: SimulationFn,
    ) -> RiskResult:
        return evaluate_strategy_risk(
            baseline, action_config, constraints=constraints, assumptions=assumptions,
            uncertainty=self._uncertainty, config=config, simulator=simulator,
        )


def create_risk_provider(path: str | Path | None = None) -> MonteCarloRiskProvider:
    return MonteCarloRiskProvider(load_uncertainty(path or DEFAULT_UNCERTAINTY_PATH))
