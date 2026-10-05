"""Development-only behavioral doubles (docs/TESTING_AND_MOCKS.md section 2).

BehavioralMockSimulator is the documented deterministic affine test double,
extended from two to all six actions with illustrative weights so every
dashboard slider responds. It is NOT the WS2 action model (docs/ACTION_MODEL.md):
it ignores scope buckets, energy interactions, savings and depreciation life.

BehavioralMockOptimizer is a seeded random search with the documented
constraint adapter and a plain nondominance filter. It is NOT NSGA-II and makes
no optimality claim. It evaluates candidates only through the injected
simulator, so it also works beside the real WS2 simulator.

All outputs carry provenance.is_mock = true. Never import this module from
production domain code.
"""

from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import Literal, Mapping

import numpy as np
import pandas as pd

from src.contracts.errors import ContractValidationError
from src.contracts.identity import canonical_hash, compute_strategy_id
from src.contracts.protocols import SimulationFn
from src.contracts.serialization import OPTIMIZATION_TABLE_SPEC, empty_frame
from src.contracts.types import (
    ACTION_NAMES,
    SCHEMA_VERSION,
    SIMULATION_MONTHLY_COLUMNS,
    ActionAssumptions,
    ActionConfig,
    BaselineBundle,
    ConstraintConfig,
    ConstraintEvaluation,
    OptimizationResult,
    OptimizerConfig,
    Provenance,
    ProviderInfo,
    RecommendationResult,
    RiskResult,
    SimulationResult,
)
from src.contracts.validation import (
    CURRENCY_ATOL_GBP,
    RATIO_ATOL,
    SOLVER_FEASIBILITY_TOL,
    validate_action_config,
    validate_assumptions,
    validate_constraints_for_baseline,
    validate_optimizer_config,
)

from . import fixtures

MOCK_VERSION = "behavioral-mock-v1"

# Illustrative whole-company emission reduction at full implementation.
EMISSION_WEIGHTS: Mapping[str, float] = {
    "renewable_energy": 0.20,
    "ev_adoption": 0.10,
    "building_efficiency": 0.06,
    "travel_reduction": 0.04,
    "cloud_efficiency": 0.03,
    "supplier_transition": 0.05,
}
PROFIT_COST_FACTOR = 0.01
MOCK_MAX_EVALUATIONS = 256


def _effectiveness(assumptions: ActionAssumptions, name: str) -> float:
    return {
        "renewable_energy": assumptions.renewable_effectiveness,
        "ev_adoption": assumptions.ev_effectiveness,
        "travel_reduction": assumptions.travel_effectiveness,
    }.get(name, 1.0)


class BehavioralMockSimulator:
    """Affine SimulationFn double: emissions scale, cost = capex, profit -= 1% cost."""

    def __init__(self, assumptions: ActionAssumptions | None = None) -> None:
        self._assumptions = assumptions
        self.info = ProviderInfo(
            slot="simulator", name="behavioral-mock-simulator", version=MOCK_VERSION, is_mock=True, kind="behavioral-mock"
        )

    def get_assumptions(self) -> ActionAssumptions:
        return self._assumptions if self._assumptions is not None else fixtures.assumptions()

    def simulate(self, baseline: BaselineBundle, config: ActionConfig, *, assumptions: ActionAssumptions) -> SimulationResult:
        validate_action_config(config)
        validate_assumptions(assumptions)
        x = config.as_dict()
        multiplier = 1.0 - sum(EMISSION_WEIGHTS[n] * x[n] * _effectiveness(assumptions, n) for n in ACTION_NAMES)
        cost = float(sum(assumptions.costs[n].capex_at_full_gbp * x[n] for n in ACTION_NAMES))
        base = baseline.monthly
        horizon = len(base)
        capex = np.zeros(horizon)
        capex[0] = cost
        zeros = np.zeros(horizon)
        depreciation = np.full(horizon, PROFIT_COST_FACTOR * cost / horizon)
        scopes = {c: base[c].to_numpy(dtype="float64") * multiplier for c in ("scope1_tco2e", "scope2_tco2e", "scope3_tco2e")}
        monthly = pd.DataFrame(
            {
                "timestamp": base["timestamp"].to_numpy(),
                "revenue_gbp": base["revenue_gbp"].to_numpy(dtype="float64"),
                "operating_profit_gbp": base["operating_profit_gbp"].to_numpy(dtype="float64") - depreciation,
                **scopes,
                "total_co2e_tco2e": scopes["scope1_tco2e"] + scopes["scope2_tco2e"] + scopes["scope3_tco2e"],
                "capex_gbp": capex,
                "incremental_opex_gbp": zeros,
                "operating_savings_gbp": zeros,
                "depreciation_gbp": depreciation,
                "budget_cost_gbp": capex,
                "net_cash_impact_gbp": -capex,
            },
            columns=list(SIMULATION_MONTHLY_COLUMNS),
        )
        base_co2 = float(base["total_co2e_tco2e"].sum())
        base_profit = float(base["operating_profit_gbp"].sum())
        total_co2 = float(monthly["total_co2e_tco2e"].sum())
        total_profit = float(monthly["operating_profit_gbp"].sum())
        reduction = base_co2 - total_co2
        change = total_profit - base_profit
        metrics = {
            "baseline_total_co2e_tco2e": base_co2,
            "total_co2e_tco2e": total_co2,
            "co2_reduction_tco2e": reduction,
            "co2_reduction_ratio": None if base_co2 == 0 else reduction / base_co2,
            "baseline_total_profit_gbp": base_profit,
            "total_profit_gbp": total_profit,
            "profit_change_gbp": change,
            "profit_change_ratio": None if base_profit == 0 else change / abs(base_profit),
            "total_cost_gbp": cost,
            "total_capex_gbp": cost,
            "total_incremental_opex_gbp": 0.0,
            "total_operating_savings_gbp": 0.0,
            "net_cash_impact_gbp": -cost,
        }
        strategy_id = compute_strategy_id(baseline.baseline_id, config, assumptions.assumptions_id, assumptions.version)
        return SimulationResult(
            schema_version=SCHEMA_VERSION,
            run_id=f"mock-{strategy_id}",
            provenance=Provenance(
                provider=self.info.name,
                is_mock=True,
                seed=None,
                input_hash=canonical_hash(
                    [baseline.baseline_id, baseline.provenance.input_hash, config.as_dict(), assumptions.assumptions_id, assumptions.version]
                ),
                config_id=MOCK_VERSION,
                assumptions_id=assumptions.assumptions_id,
            ),
            baseline_id=baseline.baseline_id,
            strategy_id=strategy_id,
            config=config,
            monthly=monthly,
            metrics=metrics,
        )


def mock_evaluate_constraints(result: SimulationResult, constraints: ConstraintConfig) -> ConstraintEvaluation:
    """Constraint adapter from docs/ACTION_MODEL.md section 5 (test double of WS2's)."""
    m = result.metrics
    cost = float(m["total_cost_gbp"])
    profit = float(m["total_profit_gbp"])
    base_profit = float(m["baseline_total_profit_gbp"])
    ratio = m["co2_reduction_ratio"]
    if ratio is None:
        if constraints.min_co2_reduction_ratio > 0:
            raise ContractValidationError("constraints.min_co2_reduction_ratio", "undefined for zero baseline CO2")
        ratio, g_target = 0.0, 0.0
    else:
        g_target = constraints.min_co2_reduction_ratio - float(ratio)
    g_budget = (cost - constraints.budget_gbp) / max(constraints.budget_gbp, 1.0)
    g_profit = (constraints.min_total_profit_gbp - profit) / max(
        abs(constraints.min_total_profit_gbp), abs(base_profit), 1.0
    )
    raw = {
        "budget_gbp": max(0.0, cost - constraints.budget_gbp),
        "profit_gbp": max(0.0, constraints.min_total_profit_gbp - profit),
        "reduction_ratio": max(0.0, constraints.min_co2_reduction_ratio - float(ratio)),
    }
    feasible = (
        max(g_budget, g_profit, g_target) <= SOLVER_FEASIBILITY_TOL
        and raw["budget_gbp"] <= CURRENCY_ATOL_GBP
        and raw["profit_gbp"] <= CURRENCY_ATOL_GBP
        and raw["reduction_ratio"] <= RATIO_ATOL
    )
    return ConstraintEvaluation(g_budget=g_budget, g_profit=g_profit, g_target=g_target, feasible=feasible, raw_violations=raw)


def _nondominated(co2: np.ndarray, profit: np.ndarray, tol: float = 1e-9) -> np.ndarray:
    keep = np.ones(len(co2), dtype=bool)
    for i in range(len(co2)):
        no_worse = (co2 <= co2[i] + tol) & (profit >= profit[i] - tol)
        strictly = (co2 < co2[i] - tol) | (profit > profit[i] + tol)
        if np.any(no_worse & strictly):
            keep[i] = False
    return keep


class BehavioralMockOptimizer:
    def __init__(self) -> None:
        self.info = ProviderInfo(
            slot="optimizer", name="behavioral-mock-optimizer", version=MOCK_VERSION, is_mock=True, kind="behavioral-mock"
        )

    def evaluate_constraints(self, result: SimulationResult, constraints: ConstraintConfig) -> ConstraintEvaluation:
        return mock_evaluate_constraints(result, constraints)

    def _candidate_configs(self, config: OptimizerConfig) -> list[ActionConfig]:
        fixed = [ActionConfig.noop()]
        for name in ACTION_NAMES:
            fixed.append(replace(ActionConfig.noop(), **{name: 1.0}))
        fixed.append(ActionConfig(*([1.0] * 6)))
        fixed.append(ActionConfig(*([0.5] * 6)))
        n_random = max(0, min(config.max_evaluations, MOCK_MAX_EVALUATIONS) - len(fixed))
        rng = np.random.default_rng(config.seed)
        draws = rng.uniform(0.0, 1.0, size=(n_random, len(ACTION_NAMES)))
        return fixed + [ActionConfig(*map(float, row)) for row in draws]

    def optimize(
        self,
        baseline: BaselineBundle,
        constraints: ConstraintConfig,
        *,
        assumptions: ActionAssumptions,
        config: OptimizerConfig,
        simulator: SimulationFn,
    ) -> OptimizationResult:
        validate_constraints_for_baseline(constraints, baseline)
        validate_optimizer_config(config)
        started = time.perf_counter()
        strategies: dict[str, SimulationResult] = {}
        rows = []
        configs = self._candidate_configs(config)
        for cfg in configs:
            result = simulator(baseline, cfg, assumptions=assumptions)
            if result.strategy_id in strategies:
                continue
            strategies[result.strategy_id] = result
            ev = self.evaluate_constraints(result, constraints)
            rows.append({
                "strategy_id": result.strategy_id,
                **result.config.as_dict(),
                "total_co2e_tco2e": float(result.metrics["total_co2e_tco2e"]),
                "total_profit_gbp": float(result.metrics["total_profit_gbp"]),
                "total_cost_gbp": float(result.metrics["total_cost_gbp"]),
                "co2_reduction_ratio": result.metrics["co2_reduction_ratio"],
                "g_budget": ev.g_budget, "g_profit": ev.g_profit, "g_target": ev.g_target,
                "feasible": ev.feasible, "pareto_rank": -1,
            })
        candidates = pd.DataFrame(rows, columns=list(OPTIMIZATION_TABLE_SPEC)).astype(
            {"feasible": "bool", "pareto_rank": "int64", "co2_reduction_ratio": "float64"}
        )
        feasible = candidates["feasible"].to_numpy()
        if feasible.any():
            idx = np.flatnonzero(feasible)
            front = _nondominated(
                candidates.loc[idx, "total_co2e_tco2e"].to_numpy(), candidates.loc[idx, "total_profit_gbp"].to_numpy()
            )
            candidates.loc[idx, "pareto_rank"] = np.where(front, 0, 1)
        pareto = candidates[candidates["pareto_rank"] == 0].sort_values(["total_co2e_tco2e", "strategy_id"]).reset_index(drop=True)
        if len(pareto) == 0:
            pareto = empty_frame(OPTIMIZATION_TABLE_SPEC)
        violations = candidates[["g_budget", "g_profit", "g_target"]].clip(lower=0.0).min()
        noop_id = compute_strategy_id(baseline.baseline_id, ActionConfig.noop(), assumptions.assumptions_id, assumptions.version)
        return OptimizationResult(
            schema_version=SCHEMA_VERSION,
            run_id=f"mock-optimization-{canonical_hash([baseline.baseline_id, constraints.__dict__, config.__dict__])[:12]}",
            provenance=Provenance(
                provider=self.info.name,
                is_mock=True,
                seed=config.seed,
                input_hash=canonical_hash(
                    [baseline.baseline_id, baseline.provenance.input_hash, constraints.__dict__, config.__dict__,
                     assumptions.assumptions_id, assumptions.version]
                ),
                config_id=MOCK_VERSION,
                assumptions_id=assumptions.assumptions_id,
            ),
            baseline_id=baseline.baseline_id,
            status="ok" if len(pareto) else "infeasible",
            constraints=constraints,
            strategies=strategies,
            candidates=candidates,
            pareto=pareto,
            diagnostics={
                "evaluated_count": len(configs),
                "unique_count": len(strategies),
                "seed": config.seed,
                "runtime_seconds": time.perf_counter() - started,
                "termination_reason": "behavioral_mock_random_search",
                "minimum_normalized_violations": {
                    "budget": float(violations["g_budget"]),
                    "profit": float(violations["g_profit"]),
                    "target": float(violations["g_target"]),
                },
                "tested_noop_strategy_id": noop_id,
                "warning": "Behavioral mock: seeded random search over an affine test double; not NSGA-II.",
            },
        )

    def recommend(
        self,
        optimization: OptimizationResult,
        *,
        risk_results: Mapping[str, RiskResult] | None = None,
        tolerance: Literal["conservative", "balanced", "aggressive"] = "balanced",
    ) -> RecommendationResult:
        common = dict(
            schema_version=SCHEMA_VERSION,
            run_id=f"mock-recommendation-{optimization.run_id}",
            provenance=replace(optimization.provenance, provider=self.info.name),
            policy="deterministic_equal_weight",
            tolerance=tolerance,
            risk_status="not_requested" if risk_results is None else "unavailable",
        )
        if optimization.status != "ok":
            return RecommendationResult(strategy_id=None, score=None, reason="No feasible strategy found within the search budget.", **common)
        front = optimization.pareto
        co2 = front["total_co2e_tco2e"].to_numpy()
        neg_profit = -front["total_profit_gbp"].to_numpy()

        def norm(v: np.ndarray) -> np.ndarray:
            span = v.max() - v.min()
            return np.zeros_like(v) if span == 0 else (v - v.min()) / span

        scores = 0.5 * norm(co2) + 0.5 * norm(neg_profit)
        order = sorted(range(len(front)), key=lambda i: (scores[i], front["strategy_id"].iloc[i]))
        best = order[0]
        reason = "Equal-weight normalized emissions and profit over the feasible frontier (mock policy)."
        if risk_results is not None:
            reason += " Risk-aware selection is not implemented by the behavioral mock."
        return RecommendationResult(
            strategy_id=str(front["strategy_id"].iloc[best]), score=float(scores[best]) if math.isfinite(scores[best]) else None,
            reason=reason, **common,
        )
