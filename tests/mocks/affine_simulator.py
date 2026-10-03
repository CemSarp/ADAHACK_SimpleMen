"""Behavioral test double from docs/TESTING_AND_MOCKS.md §2 -- TEST-ONLY, NOT an action model.

Responds to the renewable and EV actions and to sampled effectiveness/capex assumptions so
optimizer and risk tests can use known objectives:

    emissions = baseline * (1 - 0.2*x_renewable*renewable_effectiveness - 0.1*x_ev*ev_effectiveness)
    cost      = renewable_capex_at_full*x_renewable + ev_capex_at_full*x_ev
    profit    = baseline_profit - 0.01*cost

Returns a schema-valid SimulationResult (monthly allocation with matching totals) labelled
``is_mock=True``. Production code must bind ``src.actions.engine.simulate_strategy``.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.actions.definitions import compute_strategy_id
from src.contracts.types import (
    SCHEMA_VERSION,
    ActionAssumptions,
    ActionConfig,
    BaselineBundle,
    Provenance,
    SimulationResult,
)

PROVIDER = "affine-test-double"


def affine_simulator(baseline: BaselineBundle, config: ActionConfig, *, assumptions: ActionAssumptions) -> SimulationResult:
    monthly = baseline.monthly
    n = len(monthly)
    factor = (
        1.0
        - 0.2 * config.renewable_energy * assumptions.renewable_effectiveness
        - 0.1 * config.ev_adoption * assumptions.ev_effectiveness
    )
    cost = (
        assumptions.costs["renewable_energy"].capex_at_full_gbp * config.renewable_energy
        + assumptions.costs["ev_adoption"].capex_at_full_gbp * config.ev_adoption
    )
    profit_charge = np.full(n, 0.01 * cost / n)
    capex = np.zeros(n)
    capex[0] = cost
    frame = pd.DataFrame(
        {
            "timestamp": monthly["timestamp"].to_numpy(dtype="datetime64[ns]", copy=True),
            "revenue_gbp": monthly["revenue_gbp"].to_numpy(dtype=float, copy=True),
            "operating_profit_gbp": monthly["operating_profit_gbp"].to_numpy(dtype=float) - profit_charge,
            "scope1_tco2e": monthly["scope1_tco2e"].to_numpy(dtype=float) * factor,
            "scope2_tco2e": monthly["scope2_tco2e"].to_numpy(dtype=float) * factor,
            "scope3_tco2e": monthly["scope3_tco2e"].to_numpy(dtype=float) * factor,
            "total_co2e_tco2e": monthly["total_co2e_tco2e"].to_numpy(dtype=float) * factor,
            "capex_gbp": capex,
            "incremental_opex_gbp": np.zeros(n),
            "operating_savings_gbp": np.zeros(n),
            "depreciation_gbp": profit_charge,
            "budget_cost_gbp": capex.copy(),
            "net_cash_impact_gbp": -capex,
        }
    )
    baseline_co2 = math.fsum(monthly["total_co2e_tco2e"])
    baseline_profit = math.fsum(monthly["operating_profit_gbp"])
    total_co2 = math.fsum(frame["total_co2e_tco2e"])
    total_profit = math.fsum(frame["operating_profit_gbp"])
    metrics = {
        "baseline_total_co2e_tco2e": baseline_co2,
        "total_co2e_tco2e": total_co2,
        "co2_reduction_tco2e": baseline_co2 - total_co2,
        "co2_reduction_ratio": None if baseline_co2 == 0 else (baseline_co2 - total_co2) / baseline_co2,
        "baseline_total_profit_gbp": baseline_profit,
        "total_profit_gbp": total_profit,
        "profit_change_gbp": total_profit - baseline_profit,
        "profit_change_ratio": None if baseline_profit == 0 else (total_profit - baseline_profit) / abs(baseline_profit),
        "total_cost_gbp": cost,
        "total_capex_gbp": cost,
        "total_incremental_opex_gbp": 0.0,
        "total_operating_savings_gbp": 0.0,
        "net_cash_impact_gbp": -cost,
    }
    strategy_id = compute_strategy_id(baseline.baseline_id, config, assumptions)
    return SimulationResult(
        schema_version=SCHEMA_VERSION,
        run_id=f"affine-{strategy_id}",
        provenance=Provenance(
            provider=PROVIDER,
            is_mock=True,
            seed=None,
            input_hash=f"affine-{strategy_id}",
            config_id=baseline.provenance.config_id,
            assumptions_id=assumptions.assumptions_id,
        ),
        baseline_id=baseline.baseline_id,
        strategy_id=strategy_id,
        config=config,
        monthly=frame,
        metrics=metrics,
    )
