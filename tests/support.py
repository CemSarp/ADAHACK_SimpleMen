"""Shared test helpers: fixture loading and contract-valid baseline/assumption variants."""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np

from src.contracts import ActionAssumptions, ActionCosts, BaselineBundle
from src.contracts import serialization as ser

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "v1"
REPO_ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str) -> Any:
    return ser.load_json(FIXTURES / name)


def fixture_baseline() -> BaselineBundle:
    return ser.baseline_from_dict(load_fixture("baseline_12m.json"))


def fixture_assumptions() -> ActionAssumptions:
    return ser.action_assumptions_from_dict(load_fixture("action_assumptions.json"))


def make_baseline(
    *,
    months: int = 12,
    baseline_id: str = "baseline-demo-v1",
    is_mock: bool = True,
    row_fn: Callable[[int, dict[str, Any]], dict[str, Any]] | None = None,
    recompute_total: bool = True,
    **row_updates: Any,
) -> BaselineBundle:
    """Contract-valid baseline built from the fixture's first row.

    ``row_updates`` apply to every month; ``row_fn(i, row)`` may vary month ``i``. With
    ``recompute_total`` each row's total is the scope sum; the totals block is always
    recomputed from the rows.
    """
    data = load_fixture("baseline_12m.json")
    template = dict(data["monthly"][0], **row_updates)
    rows = []
    for i in range(months):
        row = dict(template)
        row["timestamp"] = dt.date(2027 + i // 12, i % 12 + 1, 1).isoformat()
        if row_fn is not None:
            row = row_fn(i, row)
        if recompute_total:
            row["total_co2e_tco2e"] = row["scope1_tco2e"] + row["scope2_tco2e"] + row["scope3_tco2e"]
        rows.append(row)
    data["monthly"] = rows
    data["horizon_months"] = months
    data["baseline_id"] = baseline_id
    data["provenance"] = dict(data["provenance"], is_mock=is_mock)
    data["totals"] = {
        "revenue_gbp": float(sum(r["revenue_gbp"] for r in rows)),
        "operating_profit_gbp": float(sum(r["operating_profit_gbp"] for r in rows)),
        "total_co2e_tco2e": float(sum(r["total_co2e_tco2e"] for r in rows)),
    }
    return ser.baseline_from_dict(json.loads(json.dumps(data)))


def assumptions_with(base: ActionAssumptions | None = None, **fields: Any) -> ActionAssumptions:
    """Variant with scalar fields replaced; a new ID keeps strategy identities distinct."""
    base = base or fixture_assumptions()
    fields.setdefault("assumptions_id", base.assumptions_id + "-variant")
    return dataclasses.replace(base, **fields)


def assumptions_with_cost(base: ActionAssumptions, action: str, **cost_fields: Any) -> ActionAssumptions:
    costs = {name: cost for name, cost in base.costs.items()}
    costs[action] = dataclasses.replace(costs[action], **cost_fields)
    return dataclasses.replace(base, assumptions_id=base.assumptions_id + f"-{action}-cost", costs=ActionCosts(**costs))


def candidate_table(*rows: dict[str, Any]):
    """Candidates/Pareto-schema frame from partial rows (feasible, distinct configs by default)."""
    import pandas as pd

    from src.contracts import ACTION_NAMES, CANDIDATE_COLUMNS

    defaults = {
        "total_cost_gbp": 1_000.0,
        "co2_reduction_ratio": 0.3,
        "g_budget": -0.5,
        "g_profit": -0.5,
        "g_target": -0.1,
        "feasible": True,
        "pareto_rank": -1,
    }
    records = []
    for i, row in enumerate(rows):
        record = {**dict.fromkeys(ACTION_NAMES, 0.0), **defaults, "renewable_energy": (i + 1) / 1_000, **row}
        records.append(record)
    frame = pd.DataFrame(records, columns=[name for name, _ in CANDIDATE_COLUMNS])
    frame["strategy_id"] = frame["strategy_id"].astype(object)
    return frame


def snapshot(obj: Any) -> Any:
    """Deep copy used to prove inputs are not mutated."""
    return copy.deepcopy(obj)


def frames_identical(left, right) -> bool:
    """Same columns, dtypes and bitwise-equal values (NaN-aware)."""
    if list(left.columns) != list(right.columns) or len(left) != len(right):
        return False
    for column in left.columns:
        a, b = left[column].to_numpy(), right[column].to_numpy()
        if a.dtype != b.dtype:
            return False
        if a.dtype.kind == "f":
            if not np.array_equal(a, b, equal_nan=True):
                return False
        elif not np.array_equal(a, b):
            return False
    return True


__all__ = [
    "FIXTURES",
    "REPO_ROOT",
    "assumptions_with",
    "assumptions_with_cost",
    "fixture_assumptions",
    "fixture_baseline",
    "frames_identical",
    "load_fixture",
    "make_baseline",
    "snapshot",
]
