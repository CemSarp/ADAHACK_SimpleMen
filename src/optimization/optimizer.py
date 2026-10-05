"""Constrained two-objective NSGA-II search over the six-action space (pymoo).

Objectives, both minimized: ``F0 = total CO2e (t)`` and ``F1 = -total operating profit
(GBP)`` over the horizon. Cost is a constraint, never a third objective. The constraints are
the normalized ``g_budget``, ``g_profit`` and ``g_target`` from :func:`evaluate_constraints`.

Search protocol:

* The injected simulator is called through a registry keyed by the exact full-precision
  configuration, so every unique candidate is simulated once and retained for audit.
* Initialization evaluates the no-op first, then deterministic seed configurations, then
  a seeded Latin-hypercube fill. Every evaluation request, including initialization, counts
  against ``max_evaluations``; the last generation is truncated to fit the budget.
* Candidate repair policy: decision vectors are clipped to [0, 1] (reported as
  ``repaired_candidates``); public inputs are never clamped.
* Every published Pareto strategy is re-simulated from its stored exact config and must
  reproduce the stored outcome and pass raw constraint validation.
"""

from __future__ import annotations

import dataclasses
import math
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pymoo
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import Problem
from pymoo.core.repair import Repair

from src.actions.definitions import assign_strategy_id, assumptions_fingerprint, baseline_fingerprint, config_from_vector
from src.contracts import validation as val
from src.contracts.errors import ContractValidationError, OptimizationError
from src.contracts.identity import canonical_hash, strategy_id_from_identity, strategy_identity_payload
from src.contracts.protocols import SimulationFn
from src.contracts.types import (
    ACTION_NAMES,
    OPTIMIZATION_TABLE_COLUMNS,
    SCHEMA_VERSION,
    ActionAssumptions,
    ActionConfig,
    BaselineBundle,
    ConstraintConfig,
    ConstraintEvaluation,
    OptimizationResult,
    OptimizerConfig,
    Provenance,
    SimulationResult,
)
from src.optimization.constraints import (
    SOLVER_FEASIBILITY_TOLERANCE,
    evaluate_constraints,
    require_defined_ratio_target,
)
from src.optimization.pareto import (
    assign_pareto_ranks,
    compute_pareto_frontier,
    dominance_tolerances,
    dominated_mask,
)

__version__ = "ws2-nsga2-1.1.0"  # bump whenever outputs for the same inputs can change
PROVIDER = "nsga2-optimizer"
SOLVER = "pymoo.NSGA2"
REPAIR_POLICY = "clip_to_unit_interval"
#: Solver-side value for a constraint that passes the normalized test but fails a raw boundary.
_RAW_ONLY_VIOLATION = 1e-12
#: Independent stream for the Latin-hypercube fill (pymoo itself uses ``seed``).
_SAMPLING_STREAM = 1


def default_seed_configs() -> tuple[ActionConfig, ...]:
    """Deterministic configurations evaluated before random samples, in this order:
    no-op, each single action at full implementation (canonical order), all actions at
    full implementation, all actions at half implementation."""
    n = len(ACTION_NAMES)
    singles = tuple(config_from_vector([1.0 if j == i else 0.0 for j in range(n)]) for i in range(n))
    return (ActionConfig.noop(), *singles, config_from_vector([1.0] * n), config_from_vector([0.5] * n))


def objective_vector(result: SimulationResult) -> tuple[float, float]:
    """Minimization objectives: (total CO2e, negative total operating profit)."""
    return float(result.metrics["total_co2e_tco2e"]), -float(result.metrics["total_profit_gbp"])


def solver_constraint_vector(evaluation: ConstraintEvaluation) -> tuple[float, float, float]:
    """pymoo inequality values (feasible when <= 0), shifted by the solver tolerance.

    A constraint that passes the normalized test but fails its raw boundary stays strictly
    positive so the search agrees with the published feasibility flag.
    """
    values = (evaluation.g_budget, evaluation.g_profit, evaluation.g_target)
    flags = (evaluation.satisfied["budget"], evaluation.satisfied["profit"], evaluation.satisfied["target"])
    return tuple(
        g - SOLVER_FEASIBILITY_TOLERANCE if ok else max(g - SOLVER_FEASIBILITY_TOLERANCE, _RAW_ONLY_VIOLATION)
        for g, ok in zip(values, flags)
    )


@dataclass(frozen=True, eq=False)
class _Candidate:
    strategy_id: str
    canonical_id: str
    config: ActionConfig
    result: SimulationResult
    evaluation: ConstraintEvaluation


class _Registry:
    """Evaluates configurations through the injected simulator, once per exact config."""

    def __init__(
        self,
        baseline: BaselineBundle,
        constraints: ConstraintConfig,
        assumptions: ActionAssumptions,
        simulator: SimulationFn,
    ) -> None:
        self.baseline = baseline
        self.constraints = constraints
        self.assumptions = assumptions
        self.simulator = simulator
        self.requests = 0
        self.by_key: dict[tuple[float, ...], _Candidate] = {}
        self.by_id: dict[str, _Candidate] = {}
        self.identities: dict[str, str] = {}

    def evaluate(self, config: ActionConfig, *, count_request: bool = True) -> _Candidate:
        if count_request:
            self.requests += 1
        key = config.as_vector()
        cached = self.by_key.get(key)
        if cached is not None:
            return cached
        result = self.simulator(self.baseline, config, assumptions=self.assumptions)
        val.validate_simulation_result(result, self.baseline)  # also checks baseline ID and dates
        if result.config.as_vector() != key:
            raise ContractValidationError("simulator.config", "simulator returned a different configuration")
        identity = strategy_identity_payload(
            self.baseline.baseline_id, config, self.assumptions.assumptions_id, self.assumptions.version
        )
        canonical_id = strategy_id_from_identity(identity)
        if result.strategy_id != canonical_id:
            raise ContractValidationError(
                "simulator.strategy_id", f"expected canonical identity {canonical_id}; got {result.strategy_id}"
            )
        strategy_id = assign_strategy_id(identity, self.identities)
        self.identities[strategy_id] = identity
        if strategy_id != canonical_id:  # truncated-hash collision: extend the published ID
            result = dataclasses.replace(result, strategy_id=strategy_id)
        candidate = _Candidate(strategy_id, canonical_id, config, result, evaluate_constraints(result, self.constraints))
        self.by_key[key] = candidate
        self.by_id[strategy_id] = candidate
        return candidate


class _SearchProblem(Problem):
    def __init__(self, registry: _Registry) -> None:
        super().__init__(n_var=len(ACTION_NAMES), n_obj=2, n_ieq_constr=3, xl=0.0, xu=1.0)
        self._registry = registry

    def _evaluate(self, X: np.ndarray, out: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        F = np.empty((len(X), 2))
        G = np.empty((len(X), 3))
        for i, row in enumerate(np.asarray(X, dtype=np.float64)):
            try:
                config = config_from_vector(row)
            except ContractValidationError as exc:
                raise OptimizationError(f"solver proposed an invalid decision vector {row.tolist()}: {exc}") from exc
            candidate = self._registry.evaluate(config)
            F[i] = objective_vector(candidate.result)
            G[i] = solver_constraint_vector(candidate.evaluation)
        out["F"] = F
        out["G"] = G


class _UnitIntervalRepair(Repair):
    """Explicit candidate repair: clip solver vectors to [0, 1] and count repaired rows."""

    def __init__(self) -> None:
        super().__init__()
        self.repaired_rows = 0

    def _do(self, problem: Problem, X: np.ndarray, **kwargs: Any) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        clipped = np.clip(X, 0.0, 1.0)
        self.repaired_rows += int(np.count_nonzero((clipped != X).any(axis=1)))
        return clipped


def _latin_hypercube(rng: np.random.Generator, n: int, dims: int) -> np.ndarray:
    strata = rng.permuted(np.tile(np.arange(n), (dims, 1)), axis=1).T
    return (strata + rng.random((n, dims))) / n


def _initial_population(config: OptimizerConfig) -> np.ndarray:
    seeds = np.array([seed.as_vector() for seed in default_seed_configs()], dtype=np.float64)
    size = min(config.population_size, config.max_evaluations)
    if size <= len(seeds):
        return seeds[:size]
    rng = np.random.default_rng([config.seed, _SAMPLING_STREAM])
    return np.vstack([seeds, _latin_hypercube(rng, size - len(seeds), len(ACTION_NAMES))])


def _run_search(
    algorithm: NSGA2, problem: _SearchProblem, registry: _Registry, config: OptimizerConfig
) -> tuple[str, int]:
    """Ask/tell loop that never exceeds ``max_evaluations`` (initialization included)."""
    generations = 0
    budget_bound = False
    while generations < config.generations:
        remaining = config.max_evaluations - registry.requests
        if remaining <= 0:
            budget_bound = True
            break
        infills = algorithm.ask()
        if infills is None or len(infills) == 0:
            return "no_new_offspring", generations
        if len(infills) > remaining:
            infills = infills[:remaining]
            budget_bound = True
        algorithm.evaluator.eval(problem, infills)
        algorithm.tell(infills=infills)
        generations += 1
    return ("max_evaluations" if budget_bound else "max_generations"), generations


def _candidate_frame(registry: _Registry) -> pd.DataFrame:
    rows = []
    for candidate in registry.by_id.values():
        metrics = candidate.result.metrics
        evaluation = candidate.evaluation
        ratio = metrics["co2_reduction_ratio"]
        rows.append(
            {
                "strategy_id": candidate.strategy_id,
                **candidate.config.as_dict(),
                "total_co2e_tco2e": float(metrics["total_co2e_tco2e"]),
                "total_profit_gbp": float(metrics["total_profit_gbp"]),
                "total_cost_gbp": float(metrics["total_cost_gbp"]),
                "co2_reduction_ratio": np.nan if ratio is None else float(ratio),
                "g_budget": evaluation.g_budget,
                "g_profit": evaluation.g_profit,
                "g_target": evaluation.g_target,
                "feasible": evaluation.feasible,
                "pareto_rank": -1,
            }
        )
    frame = pd.DataFrame(rows, columns=list(OPTIMIZATION_TABLE_COLUMNS))
    frame["strategy_id"] = frame["strategy_id"].astype(object)
    return frame


def _same_outcome(a: SimulationResult, b: SimulationResult) -> bool:
    if a.metrics != b.metrics or list(a.monthly.columns) != list(b.monthly.columns) or len(a.monthly) != len(b.monthly):
        return False
    for column in a.monthly.columns:
        left, right = a.monthly[column].to_numpy(), b.monthly[column].to_numpy()
        if left.dtype != right.dtype or not np.array_equal(left, right):
            return False
    return True


def _revalidate_frontier(pareto: pd.DataFrame, registry: _Registry, tolerances: tuple[float, float]) -> int:
    """Re-simulate each published strategy from its exact stored config and re-check it."""
    for strategy_id in pareto["strategy_id"]:
        candidate = registry.by_id[strategy_id]
        fresh = registry.simulator(registry.baseline, candidate.config, assumptions=registry.assumptions)
        val.validate_simulation_result(fresh, registry.baseline)
        if (
            fresh.strategy_id != candidate.canonical_id
            or fresh.config.as_vector() != candidate.config.as_vector()
            or not _same_outcome(fresh, candidate.result)
        ):
            raise OptimizationError(f"re-evaluating {strategy_id} did not reproduce the stored outcome; simulator is not deterministic")
        if not evaluate_constraints(fresh, registry.constraints).feasible:
            raise OptimizationError(f"published Pareto strategy {strategy_id} fails raw constraint validation")
    emissions_tol, profit_tol = tolerances
    emissions = pareto["total_co2e_tco2e"].to_numpy()
    profits = pareto["total_profit_gbp"].to_numpy()
    if dominated_mask(emissions, profits, emissions_tol=emissions_tol, profit_tol=profit_tol).any():
        raise OptimizationError("published frontier contains a dominated strategy")
    return len(pareto)


def _violation_diagnostics(candidates: pd.DataFrame) -> dict[str, Any]:
    g = np.maximum(candidates.loc[:, ["g_budget", "g_profit", "g_target"]].to_numpy(), 0.0)
    total = g.sum(axis=1)
    order = np.lexsort((candidates["strategy_id"].to_numpy(dtype=str), total))
    return {
        "minimum_normalized_violations": {
            "budget": float(g[:, 0].min()),
            "profit": float(g[:, 1].min()),
            "target": float(g[:, 2].min()),
        },
        "minimum_total_normalized_violation": float(total[order[0]]),
        "least_violating_strategy_id": str(candidates["strategy_id"].iloc[order[0]]),
    }


def optimize_strategies(
    baseline: BaselineBundle,
    constraints: ConstraintConfig,
    *,
    assumptions: ActionAssumptions,
    config: OptimizerConfig,
    simulator: SimulationFn,
) -> OptimizationResult:
    """Seeded, budget-bounded NSGA-II search returning audited candidates and a validated frontier.

    Production callers bind ``simulator=simulate_strategy``; test doubles are for isolated
    solver tests only. Returns ``status="infeasible"`` with an empty typed Pareto table when
    no evaluated candidate is feasible (not a proof of global infeasibility). Raises
    ContractValidationError for invalid inputs and OptimizationError for unexpected solver
    failures.
    """
    started = time.perf_counter()
    val.validate_baseline(baseline)
    val.validate_constraints(constraints)
    val.validate_assumptions(assumptions)
    val.validate_optimizer_config(config)
    if not callable(simulator):
        raise ContractValidationError("simulator", "must be a callable SimulationFn")
    require_defined_ratio_target(math.fsum(baseline.monthly["total_co2e_tco2e"].to_numpy(dtype=np.float64)), constraints)

    registry = _Registry(baseline, constraints, assumptions, simulator)
    problem = _SearchProblem(registry)
    repair = _UnitIntervalRepair()
    initial = _initial_population(config)
    try:
        # The no-op is simulated before any solver work; it is counted when the initial population requests it.
        noop = registry.evaluate(ActionConfig.noop(), count_request=False)
        algorithm = NSGA2(pop_size=config.population_size, sampling=initial, eliminate_duplicates=True, repair=repair)
        algorithm.setup(problem, seed=config.seed, verbose=False)
        termination_reason, generations_completed = _run_search(algorithm, problem, registry, config)
        # The registry holds one row per exact config, so frontier rows and rank-0 candidates coincide.
        candidates = assign_pareto_ranks(_candidate_frame(registry))
        pareto = compute_pareto_frontier(candidates)
        tolerances = dominance_tolerances(candidates)
        revalidated = _revalidate_frontier(pareto, registry, tolerances)
    except (ContractValidationError, OptimizationError):
        raise
    except Exception as exc:  # unexpected solver/simulator failure: typed error, original chained
        raise OptimizationError(f"optimization failed: {type(exc).__name__}: {exc}") from exc
    status = "ok" if len(pareto) else "infeasible"

    is_mock = baseline.provenance.is_mock or any(c.result.provenance.is_mock for c in registry.by_id.values())
    diagnostics: dict[str, Any] = {
        "solver": SOLVER,
        "solver_version": pymoo.__version__,
        "seed": config.seed,
        "population_size": config.population_size,
        "generations": config.generations,
        "max_evaluations": config.max_evaluations,
        "generations_completed": generations_completed,
        "evaluated_count": registry.requests,
        "unique_count": len(registry.by_id),
        "revalidated_pareto_count": revalidated,
        "seed_configuration_count": int(min(len(default_seed_configs()), len(initial))),
        "runtime_seconds": time.perf_counter() - started,
        "termination_reason": termination_reason,
        "feasible_count": int(candidates["feasible"].sum()),
        "pareto_count": len(pareto),
        **_violation_diagnostics(candidates),
        "tested_noop_strategy_id": noop.strategy_id,
        "noop_feasible": noop.evaluation.feasible,
        "repair_policy": REPAIR_POLICY,
        "repaired_candidates": repair.repaired_rows,
        "solver_feasibility_tolerance": SOLVER_FEASIBILITY_TOLERANCE,
        "dominance_tolerances": {"emissions_tco2e": tolerances[0], "profit_gbp": tolerances[1]},
        "objectives": ["minimize total_co2e_tco2e", "minimize -total_profit_gbp"],
        "simulator_providers": sorted({c.result.provenance.provider for c in registry.by_id.values()}),
    }
    warnings = []
    if status == "infeasible":
        warnings.append("No feasible candidate was found within the evaluation budget; this is not a proof of global infeasibility.")
    if is_mock:
        warnings.append("Inputs or simulator outputs carry mock provenance; not an accepted P0 domain result.")
    if warnings:
        diagnostics["warning"] = " ".join(warnings)

    input_hash = canonical_hash(
        {
            "baseline": baseline_fingerprint(baseline),
            "constraints": dataclasses.asdict(constraints),
            "assumptions": assumptions_fingerprint(assumptions),
            "optimizer": dataclasses.asdict(config),
            "solver": [SOLVER, pymoo.__version__, __version__],
        }
    )
    return OptimizationResult(
        schema_version=SCHEMA_VERSION,
        run_id=f"optimization-{input_hash[:16]}",
        provenance=Provenance(
            provider=PROVIDER,
            is_mock=is_mock,
            seed=config.seed,
            input_hash=input_hash,
            config_id=baseline.provenance.config_id,
            assumptions_id=assumptions.assumptions_id,
        ),
        status=status,
        baseline_id=baseline.baseline_id,
        constraints=constraints,
        strategies={sid: candidate.result for sid, candidate in registry.by_id.items()},
        candidates=candidates,
        pareto=pareto,
        diagnostics=diagnostics,
    )
