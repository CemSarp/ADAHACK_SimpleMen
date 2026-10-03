"""Strategy recommendation over a validated frontier (ACTION_MODEL.md §6, RISK_AND_BENCHMARK_SPEC.md §2).

P0: equal-weight min-max score of total CO2e and negative total profit across the feasible
Pareto strategies, with stable strategy-ID tie-breaking. P1: tolerance policies over WS3
risk results for a bounded selection pool. Selection only ever returns an existing feasible
Pareto strategy; it never interpolates a configuration, and it never runs a risk engine.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.contracts import (
    SCHEMA_VERSION,
    ContractValidationError,
    OptimizationResult,
    Provenance,
    RecommendationResult,
    RiskResult,
)
from src.contracts.serialization import canonical_json, sha256_hex
from src.contracts.types import RISK_TOLERANCES
from src.contracts.validation import normalize_candidate_frame, validate_risk_result
from src.optimization.pareto import RANK_FRONTIER, objective_tolerances

PROVIDER = "recommendation-service"
DETERMINISTIC_POLICY = "deterministic_equal_weight"
RISK_POLICIES = {
    "conservative": "risk_conservative",
    "balanced": "risk_balanced",
    "aggressive": "risk_aggressive",
}
#: Maximum number of frontier strategies sent to Monte Carlo for policy selection.
RISK_POOL_MAX_SIZE = 20
#: Minimum joint feasibility probability preferred by each tolerance (None: no threshold).
JOINT_PROBABILITY_THRESHOLDS: dict[str, float | None] = {"conservative": 0.90, "balanced": 0.75, "aggressive": None}
#: Policy objectives: (CO2e summary field, profit summary field, CO2e weight).
_POLICY_FIELDS = {
    "conservative": ("co2_p95_tco2e", "profit_p05_gbp", 0.5),
    "balanced": ("co2_mean_tco2e", "profit_mean_gbp", 0.5),
    "aggressive": ("co2_mean_tco2e", "profit_mean_gbp", 0.75),
}
SCORE_TIE_TOLERANCE = 1e-12


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def normalized_score(
    emissions: Sequence[float], profits: Sequence[float], *, emissions_weight: float = 0.5
) -> np.ndarray:
    """Weighted min-max score of emissions and negative profit (lower is better).

    An objective whose range is within its numerical tolerance is treated as constant and
    contributes zero, so noise is never amplified into a preference.
    """
    e = np.asarray(emissions, dtype=np.float64)
    neg_p = -np.asarray(profits, dtype=np.float64)
    emissions_tol, profit_tol = objective_tolerances(e)

    def scaled(values: np.ndarray, tolerance: float) -> np.ndarray:
        span = float(values.max() - values.min()) if values.size else 0.0
        return np.zeros_like(values) if span <= tolerance else (values - values.min()) / span

    return emissions_weight * scaled(e, emissions_tol) + (1.0 - emissions_weight) * scaled(neg_p, profit_tol)


def _pick_lowest(ids: Sequence[str], scores: np.ndarray) -> int:
    """Index of the lowest score; scores within SCORE_TIE_TOLERANCE tie and the smallest ID wins."""
    best = float(scores.min())
    tied = [i for i, score in enumerate(scores) if score <= best + SCORE_TIE_TOLERANCE]
    return min(tied, key=lambda i: ids[i])


def _validated_frontier(optimization: OptimizationResult) -> pd.DataFrame:
    if not isinstance(optimization, OptimizationResult):
        raise ContractValidationError("optimization", f"expected OptimizationResult; got {type(optimization).__name__}")
    pareto = normalize_candidate_frame(optimization.pareto, "optimization.pareto")
    if optimization.status == "infeasible":
        if len(pareto):
            raise ContractValidationError("optimization.pareto", "must be empty when status is 'infeasible'")
        return pareto
    if optimization.status != "ok":
        raise ContractValidationError("optimization.status", f"must be 'ok' or 'infeasible'; got {optimization.status!r}")
    if not len(pareto):
        raise ContractValidationError("optimization.pareto", "status 'ok' requires at least one Pareto strategy")
    if not pareto["feasible"].all() or (pareto["pareto_rank"] != RANK_FRONTIER).any():
        raise ContractValidationError("optimization.pareto", "must contain feasible rank-0 strategies only")
    missing = [sid for sid in pareto["strategy_id"] if sid not in optimization.strategies]
    if missing:
        raise ContractValidationError("optimization.strategies", f"missing Pareto strategies {missing[:3]}")
    if pareto["strategy_id"].duplicated().any():
        raise ContractValidationError("optimization.pareto", "strategy IDs must be unique")
    return pareto.sort_values(["total_co2e_tco2e", "strategy_id"], kind="mergesort").reset_index(drop=True)


def select_risk_pool(optimization: OptimizationResult, *, max_size: int = RISK_POOL_MAX_SIZE) -> tuple[str, ...]:
    """Bounded frontier pool for Monte Carlo selection (RISK_AND_BENCHMARK_SPEC.md §2).

    Orders the frontier by total CO2e (then strategy ID), keeps both objective endpoints
    and samples the remainder evenly by that order. Returns every strategy when the
    frontier has at most ``max_size`` points; empty when no feasible strategy exists.
    """
    if isinstance(max_size, bool) or not isinstance(max_size, int) or max_size < 2:
        raise ContractValidationError("max_size", "must be an integer >= 2 (both endpoints are kept)")
    ids = _validated_frontier(optimization)["strategy_id"].tolist()
    if len(ids) <= max_size:
        return tuple(ids)
    positions = np.rint(np.linspace(0, len(ids) - 1, max_size)).astype(int)
    return tuple(ids[i] for i in positions)


def _provenance(optimization: OptimizationResult, extra: Mapping[str, Any], is_mock: bool) -> tuple[str, Provenance]:
    input_hash = sha256_hex(
        canonical_json({"optimization": optimization.provenance.input_hash, "run_id": optimization.run_id, **extra})
    )
    provenance = Provenance(
        provider=PROVIDER,
        is_mock=is_mock,
        seed=optimization.provenance.seed,
        input_hash=input_hash,
        config_id=optimization.provenance.config_id,
        assumptions_id=optimization.provenance.assumptions_id,
    )
    return f"recommendation-{input_hash[:16]}", provenance


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------


def recommend_strategy(
    optimization: OptimizationResult,
    *,
    risk_results: Mapping[str, RiskResult] | None = None,
    tolerance: str = "balanced",
) -> RecommendationResult:
    """Recommend one feasible Pareto strategy, or ``None`` when the search found none.

    Without ``risk_results`` the P0 deterministic equal-weight policy applies
    (``risk_status="not_requested"``). With them, the P1 tolerance policy ranks the risk
    pool from :func:`select_risk_pool`; missing or invalid results are excluded and
    reported, and an empty usable pool falls back to the deterministic policy with
    ``risk_status="unavailable"`` (never claiming risk-aware selection).
    """
    if tolerance not in RISK_TOLERANCES:
        raise ContractValidationError("tolerance", f"must be one of {list(RISK_TOLERANCES)}; got {tolerance!r}")
    if risk_results is not None and not isinstance(risk_results, Mapping):
        raise ContractValidationError("risk_results", "must be a mapping of strategy_id to RiskResult, or None")
    frontier = _validated_frontier(optimization)
    risk_requested = risk_results is not None

    if not len(frontier):
        run_id, provenance = _provenance(optimization, {"tolerance": tolerance}, optimization.provenance.is_mock)
        return RecommendationResult(
            schema_version=SCHEMA_VERSION,
            run_id=run_id,
            provenance=provenance,
            strategy_id=None,
            policy=DETERMINISTIC_POLICY,
            tolerance=tolerance,
            score=None,
            risk_status="unavailable" if risk_requested else "not_requested",
            reason="No feasible strategy was found within the search budget, so nothing is recommended "
            "(this is not a proof that no feasible strategy exists).",
            diagnostics={"pareto_count": 0},
        )

    ids = frontier["strategy_id"].tolist()
    emissions = frontier["total_co2e_tco2e"].to_numpy()
    profits = frontier["total_profit_gbp"].to_numpy()
    scores = normalized_score(emissions, profits)
    chosen = _pick_lowest(ids, scores)
    deterministic = {
        "pareto_count": len(ids),
        "emissions_range_tco2e": [float(emissions.min()), float(emissions.max())],
        "profit_range_gbp": [float(profits.min()), float(profits.max())],
        "deterministic_strategy_id": ids[chosen],
        "deterministic_score": float(scores[chosen]),
    }
    base_reason = (
        f"Equal-weight min-max score over {len(ids)} feasible Pareto strategies (total CO2e and negative "
        "operating profit); ties broken by strategy ID."
    )
    if not risk_requested:
        run_id, provenance = _provenance(optimization, {"tolerance": tolerance}, optimization.provenance.is_mock)
        return RecommendationResult(
            schema_version=SCHEMA_VERSION,
            run_id=run_id,
            provenance=provenance,
            strategy_id=ids[chosen],
            policy=DETERMINISTIC_POLICY,
            tolerance=tolerance,
            score=float(scores[chosen]),
            risk_status="not_requested",
            reason=base_reason,
            diagnostics=deterministic,
        )
    return _risk_recommendation(optimization, risk_results, tolerance, ids[chosen], float(scores[chosen]), deterministic, base_reason)


def _usable_risk_results(
    pool: Sequence[str], risk_results: Mapping[str, RiskResult], baseline_id: str, tolerance: str
) -> tuple[dict[str, RiskResult], dict[str, str]]:
    co2_field, profit_field, _ = _POLICY_FIELDS[tolerance]
    needs_joint = JOINT_PROBABILITY_THRESHOLDS[tolerance] is not None
    usable: dict[str, RiskResult] = {}
    excluded: dict[str, str] = {}
    for sid in pool:
        result = risk_results.get(sid)
        if result is None:
            excluded[sid] = "missing"
            continue
        try:
            validate_risk_result(result, f"risk_results.{sid}")
        except ContractValidationError as exc:
            excluded[sid] = f"invalid: {exc}"
            continue
        if result.strategy_id != sid:
            excluded[sid] = f"invalid: keyed under {sid} but reports {result.strategy_id}"
        elif result.baseline_id != baseline_id:
            excluded[sid] = f"invalid: baseline {result.baseline_id} differs from {baseline_id}"
        elif needs_joint and result.summary.joint_feasibility_probability is None:
            excluded[sid] = "invalid: joint_feasibility_probability is null"
        elif getattr(result.summary, co2_field) is None or getattr(result.summary, profit_field) is None:
            excluded[sid] = "invalid: policy objective is null"
        else:
            usable[sid] = result
    return usable, excluded


def _risk_recommendation(
    optimization: OptimizationResult,
    risk_results: Mapping[str, RiskResult],
    tolerance: str,
    fallback_id: str,
    fallback_score: float,
    deterministic: dict[str, Any],
    base_reason: str,
) -> RecommendationResult:
    pool = select_risk_pool(optimization)
    usable, excluded = _usable_risk_results(pool, risk_results, optimization.baseline_id, tolerance)
    coverage = {
        "pool_strategy_ids": list(pool),
        "pool_size": len(pool),
        "evaluated_strategy_ids": [sid for sid in pool if sid in usable],
        "excluded_strategy_ids": excluded,
        "ignored_outside_pool": sorted(set(risk_results) - set(pool)),
        "coverage": "full" if len(usable) == len(pool) else "partial",
    }
    if not usable:
        run_id, provenance = _provenance(optimization, {"tolerance": tolerance, "risk": []}, optimization.provenance.is_mock)
        return RecommendationResult(
            schema_version=SCHEMA_VERSION,
            run_id=run_id,
            provenance=provenance,
            strategy_id=fallback_id,
            policy=DETERMINISTIC_POLICY,
            tolerance=tolerance,
            score=fallback_score,
            risk_status="unavailable",
            reason=f"No usable risk results for the {len(pool)}-strategy selection pool; deterministic fallback "
            f"applied and no {tolerance} risk selection is claimed. {base_reason}",
            diagnostics={**deterministic, **coverage},
        )

    trial_sets = {(r.uncertainty_id, r.n_simulations, r.provenance.seed) for r in usable.values()}
    if len(trial_sets) != 1:
        raise ContractValidationError(
            "risk_results", f"pool strategies must share one trial set (uncertainty_id, n_simulations, seed); got {sorted(map(str, trial_sets))}"
        )
    uncertainty_id, n_simulations, risk_seed = next(iter(trial_sets))

    ids = list(usable)
    co2_field, profit_field, co2_weight = _POLICY_FIELDS[tolerance]
    co2 = np.array([getattr(usable[sid].summary, co2_field) for sid in ids])
    profit = np.array([getattr(usable[sid].summary, profit_field) for sid in ids])
    threshold = JOINT_PROBABILITY_THRESHOLDS[tolerance]
    joint = np.array(
        [np.nan if usable[sid].summary.joint_feasibility_probability is None else usable[sid].summary.joint_feasibility_probability for sid in ids]
    )

    threshold_unmet = False
    if threshold is None:
        eligible = list(range(len(ids)))
    else:
        eligible = [i for i in range(len(ids)) if joint[i] >= threshold]
        threshold_unmet = not eligible
    if threshold_unmet:
        scores = normalized_score(co2, profit, emissions_weight=co2_weight)
        best_joint = float(np.max(joint))
        candidates = [i for i in range(len(ids)) if joint[i] == best_joint]
        chosen = candidates[_pick_lowest([ids[i] for i in candidates], scores[candidates])]
        score = float(scores[chosen])
    else:
        sub_scores = normalized_score(co2[eligible], profit[eligible], emissions_weight=co2_weight)
        local = _pick_lowest([ids[i] for i in eligible], sub_scores)
        chosen = eligible[local]
        score = float(sub_scores[local])

    selected = ids[chosen]
    chosen_joint = None if np.isnan(joint[chosen]) else float(joint[chosen])
    if threshold_unmet:
        risk_status = "threshold_unmet"
    else:
        risk_status = "partial" if coverage["coverage"] == "partial" else "evaluated"
    details = {
        **coverage,
        "eligible_count": 0 if threshold_unmet else len(eligible),
        "joint_probability_threshold": threshold,
        "selected_joint_feasibility_probability": chosen_joint,
        "shortfall": None if not threshold_unmet else threshold - chosen_joint,
        "policy_objectives": [co2_field, profit_field],
        "co2_weight": co2_weight,
        "uncertainty_id": uncertainty_id,
        "n_simulations": n_simulations,
        "deterministic_strategy_id": deterministic["deterministic_strategy_id"],
    }
    if threshold_unmet:
        reason = (
            f"No evaluated pool strategy reached joint feasibility probability {threshold:.2f}; selected the highest "
            f"({chosen_joint:.3f}, shortfall {threshold - chosen_joint:.3f}), then the best {tolerance} score."
        )
    elif threshold is None:
        reason = (
            f"Aggressive policy over {len(ids)} risk-evaluated pool strategies: 0.75 x normalized mean CO2e "
            "+ 0.25 x normalized negative mean profit; ties broken by strategy ID."
        )
    else:
        reason = (
            f"{tolerance.capitalize()} policy: {len(eligible)} of {len(ids)} risk-evaluated pool strategies have joint "
            f"feasibility probability >= {threshold:.2f}; minimized equal-weight normalized {co2_field} and "
            f"negative {profit_field}; ties broken by strategy ID."
        )
    if coverage["coverage"] == "partial":
        reason += f" Risk coverage is partial: {len(usable)} of {len(pool)} pool strategies have usable results."

    risk_inputs = sorted((sid, usable[sid].run_id, usable[sid].provenance.input_hash) for sid in ids)
    is_mock = optimization.provenance.is_mock or any(r.provenance.is_mock for r in usable.values())
    run_id, provenance = _provenance(optimization, {"tolerance": tolerance, "risk": risk_inputs, "seed": risk_seed}, is_mock)
    return RecommendationResult(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        provenance=provenance,
        strategy_id=selected,
        policy=RISK_POLICIES[tolerance],
        tolerance=tolerance,
        score=score,
        risk_status=risk_status,
        reason=reason,
        diagnostics=details,
    )
