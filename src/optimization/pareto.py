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

from typing import Any

import numpy as np
import pandas as pd

from src.contracts import validation as val
from src.contracts.errors import ContractValidationError
from src.contracts.serialization import OPTIMIZATION_TABLE_SPEC, empty_frame
from src.contracts.types import ACTION_NAMES, OPTIMIZATION_TABLE_COLUMNS

__version__ = "ws2-pareto-1.1.0"

EMISSIONS_ABS_TOLERANCE_TCO2E = val.SCOPE_ATOL_TCO2E
EMISSIONS_REL_TOLERANCE = val.SCOPE_RTOL
PROFIT_ABS_TOLERANCE_GBP = val.CURRENCY_ATOL_GBP

RANK_FRONTIER = 0
RANK_DOMINATED = 1
RANK_INFEASIBLE = -1

_CHUNK = 1024
_FLOAT_COLUMNS = tuple(name for name, kind in OPTIMIZATION_TABLE_SPEC.items() if kind == "float")


def normalize_candidate_frame(frame: Any, field: str = "candidates", *, require_rank: bool = True) -> pd.DataFrame:
    """Validate a candidates/Pareto table and return a typed copy in canonical column order.

    ``pareto_rank`` may be omitted when ``require_rank`` is false (it is an output column).
    """
    required = [c for c in OPTIMIZATION_TABLE_COLUMNS if require_rank or c != "pareto_rank"]
    if not isinstance(frame, pd.DataFrame):
        raise ContractValidationError(field, "must be a pandas DataFrame")
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ContractValidationError(field, f"missing required columns {missing}")
    if len(frame) == 0:
        return empty_frame(OPTIMIZATION_TABLE_SPEC)
    ids = frame["strategy_id"].to_numpy(dtype=object)
    if not all(isinstance(v, str) and v.strip() for v in ids):
        raise ContractValidationError(f"{field}.strategy_id", "must contain nonempty strings")
    out: dict[str, Any] = {"strategy_id": pd.Series(ids, dtype=object)}
    for name in _FLOAT_COLUMNS:
        series = frame[name]
        if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            raise ContractValidationError(f"{field}.{name}", f"must be numeric, got dtype {series.dtype}")
        values = series.to_numpy(dtype=np.float64, copy=True)
        if not np.isfinite(values).all():
            raise ContractValidationError(f"{field}.{name}", "must be finite")
        out[name] = values
    actions = np.column_stack([out[name] for name in ACTION_NAMES])
    if ((actions < 0.0) | (actions > 1.0)).any():
        raise ContractValidationError(field, "action columns must be fractions within [0, 1]")
    if (out["total_cost_gbp"] < 0.0).any():
        raise ContractValidationError(f"{field}.total_cost_gbp", "must be >= 0")
    ratio = frame["co2_reduction_ratio"]
    if pd.api.types.is_bool_dtype(ratio) or not (
        pd.api.types.is_numeric_dtype(ratio) or ratio.map(lambda v: v is None or isinstance(v, (int, float))).all()
    ):
        raise ContractValidationError(f"{field}.co2_reduction_ratio", "must be numeric or null")
    ratio_values = pd.to_numeric(ratio).to_numpy(dtype=np.float64, na_value=np.nan)
    if np.isinf(ratio_values).any():
        raise ContractValidationError(f"{field}.co2_reduction_ratio", "must be finite or null")
    out["co2_reduction_ratio"] = ratio_values
    if not pd.api.types.is_bool_dtype(frame["feasible"]):
        raise ContractValidationError(f"{field}.feasible", f"must be bool, got dtype {frame['feasible'].dtype}")
    out["feasible"] = frame["feasible"].to_numpy(dtype=bool, copy=True)
    if require_rank:
        if not pd.api.types.is_integer_dtype(frame["pareto_rank"]):
            raise ContractValidationError(f"{field}.pareto_rank", f"must be int, got dtype {frame['pareto_rank'].dtype}")
        out["pareto_rank"] = frame["pareto_rank"].to_numpy(dtype=np.int64, copy=True)
    else:
        out["pareto_rank"] = np.full(len(frame), RANK_INFEASIBLE, dtype=np.int64)
    return pd.DataFrame({name: out[name] for name in OPTIMIZATION_TABLE_COLUMNS})


def objective_tolerances(emissions: np.ndarray) -> tuple[float, float]:
    """(emissions, profit) tolerances; one emissions scale per candidate set keeps dominance acyclic."""
    scale = float(np.max(np.abs(emissions))) if np.size(emissions) else 0.0
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
    inconsistent = feasible & (g > val.SOLVER_FEASIBILITY_TOL).any(axis=1)
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
    if len(frontier) == 0:
        return empty_frame(OPTIMIZATION_TABLE_SPEC)
    return frontier.sort_values(["total_co2e_tco2e", "strategy_id"], kind="mergesort").reset_index(drop=True)
