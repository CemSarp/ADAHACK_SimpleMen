"""Shape stubs backed by tests/fixtures/v1 (provenance.is_mock = true).

They accept only the exact inputs their fixtures cover and raise
UnsupportedMockInput otherwise, so they never pretend to compute an arbitrary
request (docs/TESTING_AND_MOCKS.md section 2).
"""

from __future__ import annotations

from typing import Literal, Mapping

import pandas as pd

from src.contracts.errors import UnsupportedHorizon, UnsupportedMockInput
from src.contracts.protocols import SimulationFn
from src.contracts.types import (
    ActionAssumptions,
    ActionConfig,
    BacktestReport,
    BaselineBundle,
    BenchmarkResult,
    ConstraintConfig,
    ConstraintEvaluation,
    ExplanationResult,
    OptimizationResult,
    OptimizerConfig,
    ProviderInfo,
    RecommendationResult,
    RiskConfig,
    RiskResult,
    SimulationResult,
)

from . import fixtures

FIXTURE_COMPANY = "demo-company"
FIXTURE_BASELINE_ID = "baseline-demo-v1"


def _info(slot: str) -> ProviderInfo:
    return ProviderInfo(slot=slot, name=f"fixture-{slot}", version=fixtures.FIXTURE_REVISION, is_mock=True, kind="fixture")


def _require_fixture_baseline(baseline: BaselineBundle) -> None:
    if baseline.baseline_id != FIXTURE_BASELINE_ID:
        raise UnsupportedMockInput(f"fixture covers baseline {FIXTURE_BASELINE_ID!r} only, got {baseline.baseline_id!r}")


def _require_fixture_assumptions(assumptions: ActionAssumptions) -> None:
    ref = fixtures.assumptions()
    if (assumptions.assumptions_id, assumptions.version) != (ref.assumptions_id, ref.version):
        raise UnsupportedMockInput("fixture covers the demo-actions-v1 assumptions only")


class FixtureForecastProvider:
    supported_horizons: tuple[int, ...] = (12,)

    def __init__(self) -> None:
        self.info = _info("forecast")

    def _check_company(self, company_id: str) -> None:
        if company_id != FIXTURE_COMPANY:
            raise UnsupportedMockInput(f"fixture covers company {FIXTURE_COMPANY!r} only")

    def get_baseline(self, *, company_id: str, horizon_months: int) -> BaselineBundle:
        self._check_company(company_id)
        if horizon_months not in self.supported_horizons:
            raise UnsupportedHorizon(horizon_months, self.supported_horizons)
        return fixtures.baseline()

    def get_backtest(self, *, company_id: str) -> BacktestReport | None:
        self._check_company(company_id)
        return fixtures.backtest()

    def get_history(self, *, company_id: str) -> pd.DataFrame | None:
        self._check_company(company_id)
        return fixtures.history()


class FixtureSimulatorProvider:
    def __init__(self) -> None:
        self.info = _info("simulator")

    def get_assumptions(self) -> ActionAssumptions:
        return fixtures.assumptions()

    def simulate(self, baseline: BaselineBundle, config: ActionConfig, *, assumptions: ActionAssumptions) -> SimulationResult:
        _require_fixture_baseline(baseline)
        _require_fixture_assumptions(assumptions)
        for name in ("noop", "nonzero"):
            result = fixtures.simulation(name)
            if result.config == config:
                return result
        raise UnsupportedMockInput(
            "fixture simulator covers only the no-op and examples/action_config.json configs; "
            "use the behavioral mock or the real WS2 engine for other inputs"
        )


class FixtureOptimizerProvider:
    def __init__(self) -> None:
        self.info = _info("optimizer")

    def optimize(
        self,
        baseline: BaselineBundle,
        constraints: ConstraintConfig,
        *,
        assumptions: ActionAssumptions,
        config: OptimizerConfig,
        simulator: SimulationFn,
    ) -> OptimizationResult:
        _require_fixture_baseline(baseline)
        _require_fixture_assumptions(assumptions)
        for name in ("ok", "infeasible"):
            result = fixtures.optimization(name)
            if result.constraints == constraints:
                return result
        raise UnsupportedMockInput("fixture optimizer covers only the two fixture constraint sets")

    def evaluate_constraints(self, result: SimulationResult, constraints: ConstraintConfig) -> ConstraintEvaluation:
        for name in ("ok", "infeasible"):
            opt = fixtures.optimization(name)
            if opt.constraints == constraints:
                rows = opt.candidates[opt.candidates["strategy_id"] == result.strategy_id]
                if len(rows):
                    row = rows.iloc[0]
                    return ConstraintEvaluation(
                        g_budget=float(row["g_budget"]), g_profit=float(row["g_profit"]), g_target=float(row["g_target"]),
                        feasible=bool(row["feasible"]),
                        raw_violations=_fixture_raw_violations(result, constraints),
                    )
        raise UnsupportedMockInput("fixture constraint evaluation covers only fixture strategies and constraints")

    def recommend(
        self,
        optimization: OptimizationResult,
        *,
        risk_results: Mapping[str, RiskResult] | None = None,
        tolerance: Literal["conservative", "balanced", "aggressive"] = "balanced",
    ) -> RecommendationResult:
        ok = optimization.status == "ok"
        return RecommendationResult(
            schema_version=optimization.schema_version,
            run_id=f"fixture-recommendation-{optimization.run_id}",
            provenance=optimization.provenance,
            strategy_id=str(optimization.pareto["strategy_id"].iloc[0]) if ok else None,
            policy="fixture_single_point",
            tolerance=tolerance,
            score=0.0 if ok else None,
            risk_status="not_requested" if risk_results is None else "unavailable",
            reason=None if ok else "No feasible strategy in the fixture search.",
        )


def _fixture_raw_violations(result: SimulationResult, constraints: ConstraintConfig) -> dict[str, float]:
    m = result.metrics
    ratio = m["co2_reduction_ratio"] or 0.0
    return {
        "budget_gbp": max(0.0, float(m["total_cost_gbp"]) - constraints.budget_gbp),
        "profit_gbp": max(0.0, constraints.min_total_profit_gbp - float(m["total_profit_gbp"])),
        "reduction_ratio": max(0.0, constraints.min_co2_reduction_ratio - ratio),
    }


class FixtureRiskProvider:
    uncertainty_id = "illustrative-risk-v1"

    def __init__(self) -> None:
        self.info = _info("risk")

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
        _require_fixture_baseline(baseline)
        _require_fixture_assumptions(assumptions)
        if action_config != fixtures.action_config():
            raise UnsupportedMockInput("fixture risk summary covers only the examples/action_config.json strategy")
        return fixtures.risk()


class FixtureExplanationProvider:
    available_targets: tuple[str, ...] = ("total_co2e_tco2e", "operating_profit_gbp")

    def __init__(self) -> None:
        self.info = _info("shap")

    def explain(self, baseline: BaselineBundle) -> ExplanationResult:
        _require_fixture_baseline(baseline)
        return fixtures.explanation()


class FixtureBenchmarkProvider:
    def __init__(self) -> None:
        self.info = _info("benchmark")

    def benchmark(self, baseline: BaselineBundle) -> BenchmarkResult:
        _require_fixture_baseline(baseline)
        return fixtures.benchmark()
