"""Illustrative action assumptions for an imported company, scaled from the demo template.

Emission shares come from the company's own last 12 months: scope 1 splits into gas
(gas kWh x factor) and fleet, scope 3 into travel and cloud (activity x factor) and the
template's supplier/other split. An action whose activity the data does not report gets a
zero share and zero cost, so it changes nothing. Costs and supplier savings are the
template's, scaled by the company's yearly addressable activity over the demo company's.
Nothing here is calibrated; the dashboard labels the result illustrative.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from src.contracts import validation as val
from src.contracts.types import ActionAssumptions

# Yearly addressable activity of the demo company (last 12 months of data/synthetic_data.csv),
# the company config/action_assumptions_supply_chain.json was written for.
REFERENCE_ACTIVITY = {
    "renewable_energy": 12_793_277.0,      # non-renewable electricity, kWh
    "ev_adoption": 59_032_322.0,           # combustion-fleet km
    "building_efficiency": 34_822_092.0,   # electricity + gas, kWh
    "supplier_transition": 40_569.0,       # supplier scope 3, tCO2e
}
EF_GAS_TCO2E_PER_KWH = 0.000183    # natural gas, GOV.UK
EF_TRAVEL_TCO2E_PER_KM = 0.00015   # average business travel (illustrative)
EF_CLOUD_TCO2E_PER_HOUR = 0.0001   # per compute hour (illustrative)
GAS_GBP_PER_KWH, TRAVEL_GBP_PER_KM, CLOUD_GBP_PER_HOUR = 0.06, 0.20, 0.05
CLOUD_MAX_REDUCTION = 0.4
RUNNING_COST_SHARE = 0.2  # travel/cloud tools cost a fifth of the savings they unlock (illustrative)


def calibrate_assumptions(history: pd.DataFrame, template: ActionAssumptions, assumptions_id: str) -> ActionAssumptions:
    y = history.sort_values("timestamp").iloc[-12:]
    s1, s3 = float(y["scope1_tco2e"].sum()), float(y["scope3_tco2e"].sum())
    gas, km = float(y["gas_kwh"].sum()), float(y["fleet_km"].sum())
    travel, cloud = float(y["business_travel_km"].sum()), float(y["cloud_compute_hours"].sum())

    gas_share = min(1.0, gas * EF_GAS_TCO2E_PER_KWH / s1) if s1 > 0 and gas > 0 else 0.0
    ice_fleet_share = 1.0 - gas_share if s1 > 0 and km > 0 else 0.0  # any remainder is other scope 1
    travel_share = min(1.0, travel * EF_TRAVEL_TCO2E_PER_KM / s3) if s3 > 0 and travel > 0 else 0.0
    cloud_share = min(1.0 - travel_share, cloud * EF_CLOUD_TCO2E_PER_HOUR / s3) if s3 > 0 and cloud > 0 else 0.0
    rest = 1.0 - travel_share - cloud_share
    supplier_share = rest * template.supplier_share / (template.supplier_share + template.other_share) if s3 > 0 else 0.0

    activity = {
        "renewable_energy": float((y["electricity_kwh"] * (1.0 - y["renewable_energy_share"])).sum()),
        "ev_adoption": float((y["fleet_km"] * (1.0 - y["ev_share"])).sum()) if ice_fleet_share else 0.0,
        "building_efficiency": float((y["electricity_kwh"] + y["gas_kwh"]).sum()),
        "supplier_transition": s3 * supplier_share,
    }
    scale = {name: activity[name] / REFERENCE_ACTIVITY[name] for name in REFERENCE_ACTIVITY}
    costs = {name: replace(cost, capex_at_full_gbp=cost.capex_at_full_gbp * scale[name],
                           monthly_opex_at_full_gbp=cost.monthly_opex_at_full_gbp * scale[name])
             for name, cost in template.costs.items() if name in scale}
    travel_saving = travel / 12 * template.travel_effectiveness * TRAVEL_GBP_PER_KM
    cloud_saving = cloud / 12 * CLOUD_MAX_REDUCTION * CLOUD_GBP_PER_HOUR
    for name, saving in (("travel_reduction", travel_saving), ("cloud_efficiency", cloud_saving)):
        costs[name] = replace(template.costs[name], capex_at_full_gbp=0.0, monthly_opex_at_full_gbp=RUNNING_COST_SHARE * saving)

    return val.validate_assumptions(replace(
        template,
        assumptions_id=assumptions_id, version="1.0.0", is_calibrated=False,
        description=(f"ILLUSTRATIVE: {template.assumptions_id} rescaled to this company's activity. Emission shares "
                     "come from the company's own data; costs scale with each action's addressable activity."),
        gas_share=gas_share, ice_fleet_share=ice_fleet_share, travel_share=travel_share, cloud_share=cloud_share,
        supplier_share=supplier_share, other_share=rest - supplier_share,
        building_gas_share=template.building_electricity_share if gas > 0 else 0.0,
        cloud_max_reduction=CLOUD_MAX_REDUCTION if cloud > 0 else 0.0,
        gas_gbp_per_kwh=GAS_GBP_PER_KWH if gas > 0 else 0.0,
        travel_gbp_per_km=TRAVEL_GBP_PER_KM if travel > 0 else 0.0,
        cloud_gbp_per_hour=CLOUD_GBP_PER_HOUR if cloud > 0 else 0.0,
        supplier_monthly_savings_at_full_gbp=template.supplier_monthly_savings_at_full_gbp * scale["supplier_transition"],
        costs=costs,
    ))
