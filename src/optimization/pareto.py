"""Feasible Pareto frontier for (minimize total CO2e, maximize total profit) (ACTION_MODEL.md §6).

Infeasible rows are filtered before any dominance test, and cost does not take part in
dominance. ``a`` dominates ``b`` when it is no worse in either objective beyond the numerical
tolerance and strictly better in at least one beyond it. Objective-equivalent strategies
with different configurations are all kept (their risk may differ); exact duplicate
configurations are collapsed onto the lexicographically smallest strategy ID.

``pareto_rank`` semantics: 0 = feasible and nondominated, 1 = feasible but dominated,
-1 = infeasible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.contracts import ACTION_NAMES, ContractValidationError
from src.contracts.validation import normalize_candidate_frame
from src.optimization.constraints import SOLVER_FEASIBILITY_TOLERANCE

EMISSIONS_ABS_TOLERANCE_TCO2E = 1e-6
EMISSIONS_REL_TOLERANCE = 1e-8
PROFIT_ABS_TOLERANCE_GBP = 0.01

RANK_FRONTIER = 0
RANK_DOMINATED = 1
RANK_INFEASIBLE = -1

_CHUNK = 1024


def objective_tolerances(emissions: np.ndarray) -> tuple[float, float]:
    """(emissions, profit) tolerances; one emissions scale per candidate set keeps dominance acyclic."""
    scale = float(np.max(np.abs(emissions))) if emissions.size else 0.0
    return EMISSIONS_ABS_TOLERANCE_TCO2E + EMISSIONS_REL_TOLERANCE * scale, PROFIT_ABS_TOLERANCE_GBP


def dominance_tolerances(candidates: pd.DataFrame) -> tuple[float, float]:
    """Tolerances used for every dominance test over ``candidates``: the emissions scale is the
    largest |CO2e| among feasible rows, so ranking, frontier extraction and any later
    nondominance check of that frontier agree exactly."""
    frame = normalize_candidate_frame(candidates, require_rank=False)
    return objective_tolerances(frame.loc[frame["feasible"].to_numpy(), "total_co2e_tco2e"].to_numpy())


def dominates(
    a_emissions: float, a_profit: float, b_emissions: float, b_profit: float, *, emissions_tol: float, profit_tol: float
) -> bool:
    no_worse = a_emissions <= b_emissions + emissions_tol and a_profit >= b_profit - profit_tol
    strictly_better = a_emissions < b_emissions - emissions_tol or a_profit > b_profit + profit_tol
    return no_worse and strictly_better


def dominated_mask(
    emissions: np.ndarray, profits: np.ndarray, *, emissions_tol: float, profit_tol: float
) -> np.ndarray:
    """Boolean mask of points dominated by at least one other point (chunked O(n^2))."""
    emissions = np.asarray(emissions, dtype=np.float64)
    profits = np.asarray(profits, dtype=np.float64)
    dominated = np.zeros(emissions.shape[0], dtype=bool)
    for start in range(0, emissions.shape[0], _CHUNK):
        e = emissions[start : start + _CHUNK, None]
        p = profits[start : start + _CHUNK, None]
        no_worse = (e <= emissions[None, :] + emissions_tol) & (p >= profits[None, :] - profit_tol)
        strictly_better = (e < emissions[None, :] - emissions_tol) | (p > profits[None, :] + profit_tol)
        dominated |= (no_worse & strictly_better).any(axis=0)
    return dominated


def _check_feasible_rows(frame: pd.DataFrame) -> None:
    feasible = frame["feasible"].to_numpy()
    g = frame.loc[:, ["g_budget", "g_profit", "g_target"]].to_numpy()
    inconsistent = feasible & (g > SOLVER_FEASIBILITY_TOLERANCE).any(axis=1)
    if inconsistent.any():
        sid = frame["strategy_id"].iloc[int(np.flatnonzero(inconsistent)[0])]
        raise ContractValidationError("candidates.feasible", f"{sid} is marked feasible but violates a normalized constraint")
    ratio = frame["co2_reduction_ratio"].to_numpy()
    if np.isnan(ratio).any() and not np.isnan(ratio).all():
        raise ContractValidationError("candidates.co2_reduction_ratio", "must be null for all rows or none (one baseline)")


def _check_unique_identities(frame: pd.DataFrame) -> None:
    exact = frame.drop_duplicates()
    if exact["strategy_id"].duplicated().any():
        sid = exact.loc[exact["strategy_id"].duplicated(), "strategy_id"].iloc[0]
        raise ContractValidationError("candidates.strategy_id", f"{sid} appears with conflicting values")


def _drop_exact_duplicates(frame: pd.DataFrame) -> pd.DataFrame:
    exact = frame.sort_values("strategy_id", kind="mergesort").drop_duplicates()
    return exact.loc[~exact.duplicated(subset=list(ACTION_NAMES), keep="first")]


def assign_pareto_ranks(candidates: pd.DataFrame) -> pd.DataFrame:
    """Typed copy of ``candidates`` with ``pareto_rank`` computed (input left unchanged)."""
    frame = normalize_candidate_frame(candidates, require_rank=False)
    _check_unique_identities(frame)
    _check_feasible_rows(frame)
    ranks = np.full(len(frame), RANK_INFEASIBLE, dtype=np.int64)
    feasible = frame["feasible"].to_numpy()
    if feasible.any():
        emissions = frame.loc[feasible, "total_co2e_tco2e"].to_numpy()
        profits = frame.loc[feasible, "total_profit_gbp"].to_numpy()
        emissions_tol, profit_tol = objective_tolerances(emissions)
        dominated = dominated_mask(emissions, profits, emissions_tol=emissions_tol, profit_tol=profit_tol)
        ranks[feasible] = np.where(dominated, RANK_DOMINATED, RANK_FRONTIER)
    frame["pareto_rank"] = ranks
    return frame


def compute_pareto_frontier(candidates: pd.DataFrame) -> pd.DataFrame:
    """Feasible nondominated rows (``pareto_rank == 0``), duplicate configs removed.

    Sorted by total CO2e then strategy ID for deterministic presentation. An empty result
    keeps the canonical columns and dtypes.
    """
    ranked = assign_pareto_ranks(candidates)
    frontier = _drop_exact_duplicates(ranked.loc[ranked["pareto_rank"] == RANK_FRONTIER])
    return frontier.sort_values(["total_co2e_tco2e", "strategy_id"], kind="mergesort").reset_index(drop=True)
