"""Deterministic six-action monthly simulator (docs/ACTION_MODEL.md §3, §4, §7).

``simulate_strategy`` is the single numerical engine used by manual what-if, optimizer
evaluations, risk trials, scenario comparison and chat tools. It has no randomness, global
state, I/O, model access or UI dependency, and never mutates its inputs.

Numerical form: each scope is computed as ``baseline_scope * (1 - reduction_fraction)``,
which is algebraically identical to the documented bucket equations because each bucket
partition sums to one. The literal bucket sum (``scope1*gas_share + scope1*ice_fleet_share``)
does not round back to ``scope1`` for arbitrary floats, which would break the exact no-op
invariant on real baselines; the factored form returns every baseline value bit for bit
when all actions are zero, and each remaining-fraction factor stays within [0, 1].
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.actions.definitions import (
    assumptions_fingerprint,
    baseline_fingerprint,
    canonical_config,
    compute_strategy_id,
)
from src.contracts import (
    ACTION_NAMES,
    SCHEMA_VERSION,
    ActionAssumptions,
    ActionConfig,
    BaselineBundle,
    ContractValidationError,
    Provenance,
    SimulationResult,
)
from src.contracts import validation as val
from src.contracts.identity import canonical_hash

__version__ = "ws2-engine-1.1.0"  # bump whenever outputs for the same inputs can change
PROVIDER = "action-engine"

_BASELINE_FIELDS = (
    "revenue_gbp",
    "operating_profit_gbp",
    "electricity_kwh",
    "gas_kwh",
    "renewable_energy_share",
    "ev_share",
    "fleet_km",
    "business_travel_km",
    "cloud_compute_hours",
    "scope1_tco2e",
    "scope2_tco2e",
    "scope3_tco2e",
    "total_co2e_tco2e",
)


@dataclass(frozen=True)
class _Baseline:
    """Private float64 copies of the baseline columns the model reads."""

    timestamps: np.ndarray
    revenue: np.ndarray
    profit: np.ndarray
    electricity: np.ndarray
    gas: np.ndarray
    renewable_share: np.ndarray
    ev_share: np.ndarray
    fleet_km: np.ndarray
    travel_km: np.ndarray
    cloud_hours: np.ndarray
    scope1: np.ndarray
    scope2: np.ndarray
    scope3: np.ndarray
    total: np.ndarray


def _baseline_arrays(baseline: BaselineBundle) -> _Baseline:
    monthly = baseline.monthly
    block = np.ascontiguousarray(monthly.loc[:, list(_BASELINE_FIELDS)].to_numpy(dtype=np.float64, copy=True).T)
    return _Baseline(monthly["timestamp"].to_numpy(dtype="datetime64[ns]", copy=True), *block)


def _check_compatibility(b: _Baseline, a: ActionAssumptions) -> None:
    """Reject positive allocated emissions without the activity that drives them (§2)."""
    months = b.timestamps.astype("datetime64[M]")

    def reject(column: str, mask: np.ndarray, reason: str) -> None:
        if mask.any():
            month = months[int(np.flatnonzero(mask)[0])]
            raise ContractValidationError(f"baseline.monthly.{column}", f"{month}: {reason}")

    reject(
        "fleet_km",
        (b.scope1 * a.ice_fleet_share > 0.0) & (b.fleet_km * (1.0 - b.ev_share) <= 0.0),
        "ICE-fleet scope1 is allocated (scope1 * ice_fleet_share > 0) but no ICE km remain "
        "(fleet_km * (1 - ev_share) = 0)",
    )
    reject("gas_kwh", (b.scope1 * a.gas_share > 0.0) & (b.gas <= 0.0), "gas scope1 is allocated but gas_kwh = 0")
    reject("electricity_kwh", (b.scope2 > 0.0) & (b.electricity <= 0.0), "scope2 is positive but electricity_kwh = 0")
    reject(
        "scope2_tco2e",
        (b.scope2 > 0.0) & (b.renewable_share >= 1.0),
        "scope2 must be 0 when renewable_energy_share = 1 (P0 market-based demonstration assumption)",
    )
    reject(
        "business_travel_km",
        (b.scope3 * a.travel_share > 0.0) & (b.travel_km <= 0.0),
        "travel scope3 is allocated but business_travel_km = 0",
    )
    reject(
        "cloud_compute_hours",
        (b.scope3 * a.cloud_share > 0.0) & (b.cloud_hours <= 0.0),
        "cloud scope3 is allocated but cloud_compute_hours = 0",
    )


@dataclass(frozen=True)
class _Outcome:
    columns: dict[str, np.ndarray]
    breakdown: dict[str, np.ndarray]


def _transform(b: _Baseline, config: ActionConfig, a: ActionAssumptions) -> _Outcome:
    x_renewable, x_ev, x_building, x_travel, x_cloud, x_supplier = config.as_vector()
    n = b.revenue.shape[0]

    renewable_fraction = x_renewable * a.renewable_effectiveness
    ev_fraction = x_ev * a.ev_effectiveness
    building_fraction = a.building_max_reduction * x_building  # "b" in ACTION_MODEL.md §3
    travel_fraction = x_travel * a.travel_effectiveness
    cloud_fraction = a.cloud_max_reduction * x_cloud
    supplier_fraction = a.supplier_max_reduction * x_supplier
    electricity_cut = a.building_electricity_share * building_fraction
    gas_cut = a.building_gas_share * building_fraction

    # 1. Allocate scope1 to gas/ICE-fleet and scope3 to travel/cloud/supplier/other buckets.
    gas_bucket = b.scope1 * a.gas_share
    fleet_bucket = b.scope1 * a.ice_fleet_share
    travel_bucket = b.scope3 * a.travel_share
    cloud_bucket = b.scope3 * a.cloud_share
    supplier_bucket = b.scope3 * a.supplier_share

    # 2. Building efficiency applies to baseline building load only (never to added EV load).
    electricity_saved = b.electricity * electricity_cut
    gas_saved = b.gas * gas_cut

    # 3. Convert remaining ICE fleet to EV: removes fleet scope1, adds electricity demand.
    remaining_ice = 1.0 - b.ev_share
    ev_converted_km = b.fleet_km * remaining_ice * ev_fraction
    ev_extra_kwh = ev_converted_km * a.ev_kwh_per_km
    electricity_new = b.electricity - electricity_saved + ev_extra_kwh
    gas_new = b.gas - gas_saved

    # 4. Renewable coverage applies to the resulting electricity demand.
    nonrenewable = 1.0 - b.renewable_share
    renewable_uplift = nonrenewable * renewable_fraction  # r_new - r without cancellation
    nonrenewable_new = nonrenewable * (1.0 - renewable_fraction)  # 1 - r_new, >= 0

    scope1 = b.scope1 * max(0.0, 1.0 - (a.gas_share * gas_cut + a.ice_fleet_share * ev_fraction))
    # (1 - electricity_saved/E) * (1 - r_new)/(1 - r) == (1 - electricity_cut) * (1 - renewable_fraction)
    existing_scope2 = b.scope2 * ((1.0 - electricity_cut) * (1.0 - renewable_fraction))
    ev_scope2 = ev_extra_kwh * a.grid_tco2e_per_kwh * nonrenewable_new  # may raise scope2: never clamped
    scope2 = existing_scope2 + ev_scope2

    # 5. Travel, cloud and supplier act on their distinct scope3 buckets; "other" is untouched.
    scope3_reduction = (
        a.travel_share * travel_fraction + a.cloud_share * cloud_fraction + a.supplier_share * supplier_fraction
    )
    scope3 = b.scope3 * max(0.0, 1.0 - scope3_reduction)
    # Total moves by the scope deltas, preserving the baseline's own reconciliation exactly.
    total = np.maximum(b.total + ((scope1 - b.scope1) + (scope2 - b.scope2) + (scope3 - b.scope3)), 0.0)

    # 6. Accounting (ACTION_MODEL.md §4): capex is cash in month 1; depreciation hits profit.
    action_values = config.as_vector()
    costs = [a.costs[name] for name in ACTION_NAMES]
    capex_by_action = [cost.capex_at_full_gbp * x for cost, x in zip(costs, action_values)]
    month_index = np.arange(n)
    depreciation = np.zeros(n)
    for cost, action_capex in zip(costs, capex_by_action):
        if action_capex > 0.0:
            monthly_charge = action_capex / cost.asset_life_months
            depreciation = depreciation + np.where(month_index < cost.asset_life_months, monthly_charge, 0.0)
    capex = np.zeros(n)
    capex[0] = math.fsum(capex_by_action)

    fixed_opex = np.full(n, math.fsum(cost.monthly_opex_at_full_gbp * x for cost, x in zip(costs, action_values)))
    ev_electricity_cost = ev_extra_kwh * a.electricity_gbp_per_kwh
    renewable_premium = electricity_new * renewable_uplift * a.renewable_premium_gbp_per_kwh
    incremental_opex = fixed_opex + ev_electricity_cost + renewable_premium
    operating_savings = (
        electricity_saved * a.electricity_gbp_per_kwh
        + gas_saved * a.gas_gbp_per_kwh
        + ev_converted_km * a.ice_fuel_gbp_per_km
        + b.travel_km * travel_fraction * a.travel_gbp_per_km
        + b.cloud_hours * cloud_fraction * a.cloud_gbp_per_hour
        + a.supplier_monthly_savings_at_full_gbp * x_supplier
    )
    operating_profit = b.profit + operating_savings - incremental_opex - depreciation  # capex not subtracted
    budget_cost = capex + incremental_opex  # gross outlay: savings never reduce it
    net_cash_impact = operating_savings - incremental_opex - capex

    columns = {
        "revenue_gbp": b.revenue,
        "operating_profit_gbp": operating_profit,
        "scope1_tco2e": scope1,
        "scope2_tco2e": scope2,
        "scope3_tco2e": scope3,
        "total_co2e_tco2e": total,
        "capex_gbp": capex,
        "incremental_opex_gbp": incremental_opex,
        "operating_savings_gbp": operating_savings,
        "depreciation_gbp": depreciation,
        "budget_cost_gbp": budget_cost,
        "net_cash_impact_gbp": net_cash_impact,
    }
    breakdown = {
        "renewable_energy_share": np.minimum(b.renewable_share + renewable_uplift, 1.0),
        "ev_share": np.minimum(b.ev_share + remaining_ice * ev_fraction, 1.0),
        "electricity_kwh": electricity_new,
        "gas_kwh": gas_new,
        "electricity_saved_kwh": electricity_saved,
        "gas_saved_kwh": gas_saved,
        "ev_converted_km": ev_converted_km,
        "ev_extra_kwh": ev_extra_kwh,
        "gas_baseline_tco2e": gas_bucket,
        "gas_tco2e": gas_bucket * (1.0 - gas_cut),
        "ice_fleet_baseline_tco2e": fleet_bucket,
        "ice_fleet_tco2e": fleet_bucket * (1.0 - ev_fraction),
        "existing_scope2_tco2e": existing_scope2,
        "ev_scope2_tco2e": ev_scope2,
        "travel_baseline_tco2e": travel_bucket,
        "travel_tco2e": travel_bucket * (1.0 - travel_fraction),
        "cloud_baseline_tco2e": cloud_bucket,
        "cloud_tco2e": cloud_bucket * (1.0 - cloud_fraction),
        "supplier_baseline_tco2e": supplier_bucket,
        "supplier_tco2e": supplier_bucket * (1.0 - supplier_fraction),
        "other_tco2e": b.scope3 * a.other_share,
        "fixed_opex_gbp": fixed_opex,
        "ev_electricity_cost_gbp": ev_electricity_cost,
        "renewable_premium_gbp": renewable_premium,
    }
    for name, values in {**columns, **breakdown}.items():
        if not np.isfinite(values).all():
            raise ContractValidationError(f"simulation.{name}", "inputs produce non-finite outcomes; check units and magnitudes")
    return _Outcome(columns=columns, breakdown=breakdown)


def _prepare(
    baseline: BaselineBundle, config: ActionConfig, assumptions: ActionAssumptions
) -> tuple[_Baseline, ActionConfig, _Outcome]:
    val.validate_baseline(baseline)
    config = canonical_config(config)
    val.validate_assumptions(assumptions)
    arrays = _baseline_arrays(baseline)
    _check_compatibility(arrays, assumptions)
    return arrays, config, _transform(arrays, config, assumptions)


def simulate_strategy(
    baseline: BaselineBundle, config: ActionConfig, *, assumptions: ActionAssumptions
) -> SimulationResult:
    """Simulate one strategy over the baseline horizon (the canonical ``SimulationFn``).

    Returns complete monthly outcomes and reconciled horizon metrics. The all-zero config
    reproduces every baseline emission and profit value exactly with zero costs. Profit
    may be negative and EV adoption may increase scope2 or total emissions; neither is
    clamped. Raises ContractValidationError for invalid or model-incompatible inputs.
    """
    arrays, config, outcome = _prepare(baseline, config, assumptions)
    monthly = pd.DataFrame({"timestamp": arrays.timestamps, **outcome.columns})

    baseline_co2 = math.fsum(arrays.total)
    total_co2 = math.fsum(outcome.columns["total_co2e_tco2e"])
    reduction = baseline_co2 - total_co2
    baseline_profit = math.fsum(arrays.profit)
    total_profit = math.fsum(outcome.columns["operating_profit_gbp"])
    profit_change = total_profit - baseline_profit
    # Keys and order follow SIMULATION_METRIC_FIELDS; ratios are None for zero baselines.
    metrics: dict[str, float | None] = {
        "baseline_total_co2e_tco2e": baseline_co2,
        "total_co2e_tco2e": total_co2,
        "co2_reduction_tco2e": reduction,
        "co2_reduction_ratio": None if baseline_co2 == 0.0 else reduction / baseline_co2,
        "baseline_total_profit_gbp": baseline_profit,
        "total_profit_gbp": total_profit,
        "profit_change_gbp": profit_change,
        "profit_change_ratio": None if baseline_profit == 0.0 else profit_change / abs(baseline_profit),
        "total_cost_gbp": math.fsum(outcome.columns["budget_cost_gbp"]),
        "total_capex_gbp": math.fsum(outcome.columns["capex_gbp"]),
        "total_incremental_opex_gbp": math.fsum(outcome.columns["incremental_opex_gbp"]),
        "total_operating_savings_gbp": math.fsum(outcome.columns["operating_savings_gbp"]),
        "net_cash_impact_gbp": math.fsum(outcome.columns["net_cash_impact_gbp"]),
    }

    input_hash = canonical_hash(
        {
            "baseline": baseline_fingerprint(baseline),
            "config": config.as_dict(),
            "assumptions": assumptions_fingerprint(assumptions),
        }
    )
    return SimulationResult(
        schema_version=SCHEMA_VERSION,
        run_id=f"simulation-{input_hash[:16]}",
        provenance=Provenance(
            provider=PROVIDER,
            is_mock=baseline.provenance.is_mock,
            seed=None,
            input_hash=input_hash,
            config_id=baseline.provenance.config_id,
            assumptions_id=assumptions.assumptions_id,
        ),
        baseline_id=baseline.baseline_id,
        strategy_id=compute_strategy_id(baseline.baseline_id, config, assumptions),
        config=config,
        monthly=monthly,
        metrics=metrics,
    )


def compute_action_breakdown(
    baseline: BaselineBundle, config: ActionConfig, *, assumptions: ActionAssumptions
) -> pd.DataFrame:
    """Monthly intermediate quantities from the same transform as ``simulate_strategy``.

    Includes resulting renewable/EV shares (for UI display next to the implementation
    fraction), activity changes, and baseline/scenario emission buckets. The scope columns
    of the SimulationResult remain authoritative; bucket columns reconcile to them within
    the documented emissions tolerance.
    """
    arrays, _, outcome = _prepare(baseline, config, assumptions)
    return pd.DataFrame({"timestamp": arrays.timestamps, **outcome.breakdown})
