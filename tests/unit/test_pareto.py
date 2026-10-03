"""Feasible Pareto filtering with known feasible, infeasible, dominated and equivalent points."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.contracts.types import OPTIMIZATION_TABLE_COLUMNS
from src.contracts import ContractValidationError
from src.optimization.pareto import (
    PROFIT_ABS_TOLERANCE_GBP,
    assign_pareto_ranks,
    compute_pareto_frontier,
    dominance_tolerances,
    dominated_mask,
    dominates,
    objective_tolerances,
)
from tests.support import candidate_table, frames_identical, snapshot

EXPECTED_DTYPES = {
    "strategy_id": "object",
    "total_co2e_tco2e": "float64",
    "co2_reduction_ratio": "float64",
    "feasible": "bool",
    "pareto_rank": "int64",
}


def point(sid: str, emissions: float, profit: float, **extra):
    return {"strategy_id": sid, "total_co2e_tco2e": emissions, "total_profit_gbp": profit, **extra}


def infeasible(sid: str, emissions: float, profit: float, **extra):
    return point(sid, emissions, profit, feasible=False, g_budget=0.5, **extra)


def ids(frame: pd.DataFrame) -> list[str]:
    return frame["strategy_id"].tolist()


def ranks(frame: pd.DataFrame) -> dict[str, int]:
    return dict(zip(frame["strategy_id"], frame["pareto_rank"]))


def test_known_feasible_dominated_and_infeasible_points():
    table = candidate_table(
        point("strategy-a", 100.0, 1_000.0),
        point("strategy-b", 90.0, 900.0),  # trade-off with a
        point("strategy-c", 110.0, 950.0),  # dominated by a
        infeasible("strategy-d", 50.0, 5_000.0),  # would dominate everything, but infeasible
    )
    frontier = compute_pareto_frontier(table)
    assert ids(frontier) == ["strategy-b", "strategy-a"]  # sorted by emissions
    assert (frontier["pareto_rank"] == 0).all() and frontier["feasible"].all()
    assert ranks(assign_pareto_ranks(table)) == {"strategy-a": 0, "strategy-b": 0, "strategy-c": 1, "strategy-d": -1}


def test_equivalent_objectives_with_different_configs_are_kept():
    table = candidate_table(
        point("strategy-a", 100.0, 1_000.0),
        point("strategy-e", 100.0 + 5e-7, 1_000.0 + 0.005, ev_adoption=0.5),  # within both tolerances
    )
    assert ids(compute_pareto_frontier(table)) == ["strategy-a", "strategy-e"]


def test_tolerance_boundaries_decide_dominance():
    reference = point("strategy-a", 100.0, 1_000.0)
    materially_lower = candidate_table(reference, point("strategy-f", 100.0 - 1e-3, 1_000.0))
    assert ids(compute_pareto_frontier(materially_lower)) == ["strategy-f"]
    profit_noise = candidate_table(reference, point("strategy-g", 95.0, 1_000.0 - 0.005))
    assert ids(compute_pareto_frontier(profit_noise)) == ["strategy-g"]  # worse only within the 0.01 GBP tolerance
    material_tradeoff = candidate_table(reference, point("strategy-h", 95.0, 1_000.0 - 0.02))
    assert ids(compute_pareto_frontier(material_tradeoff)) == ["strategy-h", "strategy-a"]


def test_cost_does_not_participate_in_dominance():
    table = candidate_table(
        point("strategy-a", 100.0, 1_000.0, total_cost_gbp=10.0),
        point("strategy-b", 100.0, 1_000.0, total_cost_gbp=1e6),  # equivalent objectives, costlier
        point("strategy-c", 101.0, 999.0, total_cost_gbp=0.0),  # cheapest, but dominated
    )
    assert ids(compute_pareto_frontier(table)) == ["strategy-a", "strategy-b"]


def test_exact_duplicate_configs_collapse_to_the_smallest_id():
    same_config = {"renewable_energy": 0.25, "ev_adoption": 0.5}
    table = candidate_table(
        point("strategy-z", 100.0, 1_000.0, **same_config),
        point("strategy-m", 100.0, 1_000.0, **same_config),
        point("strategy-m", 100.0, 1_000.0, **same_config),
    )
    assert ids(compute_pareto_frontier(table)) == ["strategy-m"]


def test_conflicting_rows_for_one_strategy_id_are_rejected():
    table = candidate_table(point("strategy-a", 100.0, 1_000.0), point("strategy-a", 90.0, 1_000.0))
    with pytest.raises(ContractValidationError, match="conflicting"):
        compute_pareto_frontier(table)


def test_empty_and_all_infeasible_inputs_give_typed_empty_frames():
    empty = compute_pareto_frontier(candidate_table())
    all_infeasible = compute_pareto_frontier(candidate_table(infeasible("strategy-a", 1.0, 1.0)))
    for frame in (empty, all_infeasible):
        assert len(frame) == 0
        assert list(frame.columns) == list(OPTIMIZATION_TABLE_COLUMNS)
        for column, dtype in EXPECTED_DTYPES.items():
            assert str(frame[column].dtype) == dtype


def test_rows_marked_feasible_must_satisfy_normalized_constraints():
    table = candidate_table(point("strategy-a", 100.0, 1_000.0, g_target=0.1))
    with pytest.raises(ContractValidationError, match="marked feasible"):
        compute_pareto_frontier(table)


def test_reduction_ratio_must_be_null_for_all_rows_or_none():
    table = candidate_table(point("strategy-a", 100.0, 1_000.0), point("strategy-b", 90.0, 900.0, co2_reduction_ratio=None))
    with pytest.raises(ContractValidationError, match="co2_reduction_ratio"):
        compute_pareto_frontier(table)


def test_input_frame_is_not_mutated():
    table = candidate_table(point("strategy-a", 100.0, 1_000.0), point("strategy-c", 110.0, 950.0))
    before = snapshot(table)
    compute_pareto_frontier(table)
    assert frames_identical(table, before)


def test_dominance_semantics():
    tol = dict(emissions_tol=1e-6, profit_tol=PROFIT_ABS_TOLERANCE_GBP)
    assert not dominates(100.0, 1_000.0, 100.0, 1_000.0, **tol)  # never dominates itself
    assert dominates(99.0, 1_000.0, 100.0, 1_000.0, **tol)
    assert not dominates(99.0, 999.0, 100.0, 1_000.0, **tol)
    assert objective_tolerances(np.array([1_200.0, -5.0])) == pytest.approx((1e-6 + 1.2e-5, 0.01))


def test_frontier_is_nondominated_under_the_declared_candidate_tolerances():
    # A far, dominated feasible point sets the emissions scale (tolerance 1e-6 + 2e-5 t), so a and b
    # (1.5e-5 t apart, equal profit) are equivalent. A frontier-only scale would be tighter and
    # disagree, which is why checks must use the tolerances declared for the candidate set.
    table = candidate_table(
        point("strategy-a", 100.0, 1_000.0),
        point("strategy-b", 100.0 + 1.5e-5, 1_000.0),
        point("strategy-x", 2_000.0, 0.0),
    )
    frontier = compute_pareto_frontier(table)
    assert ids(frontier) == ["strategy-a", "strategy-b"]
    emissions, profits = frontier["total_co2e_tco2e"].to_numpy(), frontier["total_profit_gbp"].to_numpy()
    tol_e, tol_p = dominance_tolerances(table)
    assert tol_e == pytest.approx(1e-6 + 2e-5)
    assert not dominated_mask(emissions, profits, emissions_tol=tol_e, profit_tol=tol_p).any()
    narrow, _ = objective_tolerances(emissions)
    assert dominated_mask(emissions, profits, emissions_tol=narrow, profit_tol=tol_p).any()


def test_vectorized_ranks_match_brute_force_beyond_one_chunk():
    rng = np.random.default_rng(3)
    n = 1_300  # exceeds the 1,024-row chunk
    emissions = np.round(rng.uniform(400, 1_200, n), 1)  # coarse grid creates ties
    profits = np.round(1_300_000 - emissions * 100 + rng.normal(0, 5_000, n), 0)
    tol_e, tol_p = objective_tolerances(emissions)
    expected = np.array(
        [((emissions <= e + tol_e) & (profits >= p - tol_p) & ((emissions < e - tol_e) | (profits > p + tol_p))).any() for e, p in zip(emissions, profits)]
    )
    assert np.array_equal(dominated_mask(emissions, profits, emissions_tol=tol_e, profit_tol=tol_p), expected)
    sample = rng.choice(n, 60, replace=False)
    brute = [any(dominates(emissions[j], profits[j], emissions[i], profits[i], emissions_tol=tol_e, profit_tol=tol_p) for j in range(n)) for i in sample]
    assert brute == expected[sample].tolist()
