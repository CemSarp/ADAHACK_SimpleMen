"""Read-only data views for the chat assistant.

Every number is computed here from the bound history, baseline, simulator or public snapshots and rounded
for quoting, so a small local model never has to do arithmetic or guess. Labels say what each number is
(reported history, forecast, simulation, assumption, or the separate Wincanton reference).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.actions.definitions import ACTION_DEFINITIONS
from src.contracts import validation as val
from src.contracts.types import ActionAssumptions, ActionConfig, BaselineBundle, SCOPE_COLUMNS
from src.dashboard.presentation import ACTION_LABELS
from src.data_sources.public_data import calculate_electricity_scenario, load_company_reference, load_factors
from src.integration.services import Services

ACTIVITY_COLUMNS = {
    "electricity_kwh": "electricity (kWh)",
    "gas_kwh": "gas (kWh)",
    "fleet_km": "fleet distance (km)",
    "business_travel_km": "business travel (km)",
    "cloud_compute_hours": "cloud compute (hours)",
}
PLAIN_ACTIONS = {
    "renewable_energy": "Switch purchased electricity to renewable supply; cuts Scope 2 (electricity) emissions.",
    "ev_adoption": "Replace diesel fleet vehicles with electric ones; cuts Scope 1 fleet fuel but adds some electricity use.",
    "building_efficiency": "Make sites use less electricity and gas (lighting, heating, equipment).",
    "travel_reduction": "Cut business travel; affects the Scope 3 travel share.",
    "cloud_efficiency": "Use less cloud computing; affects the Scope 3 cloud share.",
    "supplier_transition": "Move purchasing to lower-carbon suppliers; cuts the Scope 3 supplier share.",
}
SCOPES_EXPLAINED = {
    "scope1": "Fuel the company burns itself, e.g. diesel in its trucks.",
    "scope2": "Electricity it buys; the power station burns the fuel, the company uses the power.",
    "scope3": "Its wider supply chain, e.g. suppliers, subcontractors, business travel and cloud services.",
    "note": "Scope 1 + 2 is what a company directly controls; Scope 3 is reported separately.",
}


def _r(value: float, digits: int = 1) -> float:
    return round(float(value), digits)


def _pct(part: float, whole: float) -> float | None:
    return None if not whole else _r(100.0 * part / whole)


def _change_pct(new: float, old: float) -> float | None:
    return None if not old else _r(100.0 * (new - old) / abs(old))


def _period(timestamps: pd.Series) -> str:
    return f"{timestamps.iloc[0]:%b %Y} to {timestamps.iloc[-1]:%b %Y}"


def _emissions(frame: pd.DataFrame) -> dict[str, Any]:
    total = float(frame["total_co2e_tco2e"].sum())
    scopes = {c.split("_")[0]: float(frame[c].sum()) for c in SCOPE_COLUMNS}
    return {"total_tco2e": _r(total), **{f"{k}_tco2e": _r(v) for k, v in scopes.items()},
            "share_pct": {k: _pct(v, total) for k, v in scopes.items()}}


def _window(frame: pd.DataFrame) -> dict[str, Any]:
    revenue = float(frame["revenue_gbp"].sum())
    profit = float(frame["operating_profit_gbp"].sum())
    total = float(frame["total_co2e_tco2e"].sum())
    scope12 = float(frame["scope1_tco2e"].sum() + frame["scope2_tco2e"].sum())  # comparable with company disclosures
    last = frame.iloc[-1]
    return {
        "period": _period(frame["timestamp"]),
        "emissions": _emissions(frame),
        "revenue_gbp": round(revenue),
        "operating_profit_gbp": round(profit),
        "operating_margin_pct": _pct(profit, revenue),
        "tco2e_per_gbp_million_revenue": None if not revenue else _r(total / (revenue / 1e6), 2),
        "scope1_2_tco2e": _r(scope12),
        "scope1_2_tco2e_per_gbp_million_revenue": None if not revenue else _r(scope12 / (revenue / 1e6)),
        "activity": {label: round(float(frame[col].sum())) for col, label in ACTIVITY_COLUMNS.items()
                     if float(frame[col].abs().sum()) > 0},
        "latest_month": {
            "renewable_electricity_share_pct": _r(100 * float(last["renewable_energy_share"])),
            "ev_fleet_share_pct": _r(100 * float(last["ev_share"])),
            "fleet_size": int(last["fleet_size"]),
        },
    }


def company_profile(history: pd.DataFrame | None, baseline: BaselineBundle, assumptions: ActionAssumptions) -> dict:
    a = assumptions
    out: dict[str, Any] = {
        "kind": "company_profile",
        "company_id": baseline.company_id,
        "data_kind": baseline.data_kind,
        "data_note": ("Synthetic, illustrative company data (not a real company's records)."
                      if baseline.data_kind == "synthetic" else "The company's own uploaded figures."),
        "what_the_scopes_contain": {
            "scope1": {"fleet_fuel_pct": _r(100 * a.ice_fleet_share), "building_gas_pct": _r(100 * a.gas_share)},
            "scope2": "purchased electricity",
            "scope3": {"suppliers_pct": _r(100 * a.supplier_share), "business_travel_pct": _r(100 * a.travel_share),
                       "cloud_pct": _r(100 * a.cloud_share), "other_pct": _r(100 * a.other_share)},
            "basis": "allocation assumptions used by the simulator, not measured splits",
        },
    }
    forecast = baseline.monthly
    out["baseline_forecast"] = {
        "label": "business-as-usual forecast, no new actions",
        "period": _period(forecast["timestamp"]),
        "horizon_months": baseline.horizon_months,
        "emissions": _emissions(forecast),
        "revenue_gbp": round(float(forecast["revenue_gbp"].sum())),
        "operating_profit_gbp": round(float(forecast["operating_profit_gbp"].sum())),
    }
    if history is None or len(history) < 12:
        out["history"] = None
        out["history_note"] = "No company history is available in this session."
        return out
    h = history.sort_values("timestamp")
    last12 = h.tail(12)
    hist: dict[str, Any] = {"covers": _period(h["timestamp"]), "months": len(h), "last_12_months": _window(last12)}
    if len(h) >= 24:
        prev = h.iloc[-24:-12]
        hist["previous_12_months"] = {
            "period": _period(prev["timestamp"]),
            "total_tco2e": _r(prev["total_co2e_tco2e"].sum()),
            "revenue_gbp": round(float(prev["revenue_gbp"].sum())),
            "operating_profit_gbp": round(float(prev["operating_profit_gbp"].sum())),
        }
        hist["change_last_12_vs_previous_12_pct"] = {
            col: _change_pct(float(last12[col].sum()), float(prev[col].sum()))
            for col in ("total_co2e_tco2e", "revenue_gbp", "operating_profit_gbp")
        }
    not_reported = [label for col, label in ACTIVITY_COLUMNS.items() if float(last12[col].abs().sum()) == 0]
    if int(last12["employees"].abs().sum()) == 0:
        not_reported.append("employees")
    not_reported += [f"scope {c[5]} emissions" for c in SCOPE_COLUMNS if float(last12[c].abs().sum()) == 0]
    hist["not_reported_in_data"] = not_reported
    out["history"] = hist
    out["forecast_vs_last_12_months_pct"] = {
        "total_emissions": _change_pct(float(forecast["total_co2e_tco2e"].sum()), float(last12["total_co2e_tco2e"].sum())),
        "operating_profit": _change_pct(float(forecast["operating_profit_gbp"].sum()),
                                        float(last12["operating_profit_gbp"].sum())),
    }
    return out


def compare_actions(baseline: BaselineBundle, services: Services) -> dict:
    """Each action alone at full adoption (value 1.0) through the bound simulator, ranked by CO2 cut."""
    a = services.assumptions
    first = baseline.monthly.iloc[0]
    rows, is_mock = [], False
    for d in ACTION_DEFINITIONS:
        config = val.validate_action_config(ActionConfig.from_mapping({**ActionConfig.noop().as_dict(), d.name: 1.0}))
        sim = val.validate_simulation_result(services.simulate(baseline, config), baseline)
        is_mock = is_mock or sim.provenance.is_mock
        m = sim.metrics
        cut, outlay = float(m["co2_reduction_tco2e"]), float(m["total_cost_gbp"])
        cost = a.costs[d.name]
        rows.append({
            "action": d.name,
            "label": ACTION_LABELS[d.name],  # the same names as the dashboard
            "what_it_does": PLAIN_ACTIONS[d.name],
            "has_effect_for_this_company": cut > 1e-6,
            "alone_at_full_adoption_over_horizon": {
                "co2_cut_tco2e": _r(cut),
                "co2_cut_pct_of_total_baseline": _r(100 * float(m["co2_reduction_ratio"] or 0.0)),
                "operating_profit_change_gbp": round(float(m["profit_change_gbp"])),
                "gross_outlay_gbp": round(outlay),
                "outlay_per_tonne_cut_gbp": round(outlay / cut) if cut > 1e-6 else None,
            },
            "cost_assumption_at_full": {"capex_gbp": round(cost.capex_at_full_gbp),
                                        "monthly_opex_gbp": round(cost.monthly_opex_at_full_gbp),
                                        "asset_life_months": cost.asset_life_months},
        })
    rows.sort(key=lambda r: r["alone_at_full_adoption_over_horizon"]["co2_cut_tco2e"], reverse=True)
    effective = [r for r in rows if r["has_effect_for_this_company"]]
    return {
        "kind": "action_comparison",
        "horizon_months": baseline.horizon_months,
        "current_shares_pct": {"renewable_electricity": _r(100 * float(first["renewable_energy_share"])),
                               "ev_fleet": _r(100 * float(first["ev_share"]))},
        "ranked_by_co2_cut": [r["action"] for r in effective],
        "lowest_outlay_per_tonne": min(effective, key=lambda r: r["alone_at_full_adoption_over_horizon"]["outlay_per_tonne_cut_gbp"]
                                  or float("inf"))["action"] if effective else None,
        "no_effect_for_this_company": [r["action"] for r in rows if not r["has_effect_for_this_company"]],
        "actions": rows,
        "assumptions_id": a.assumptions_id,
        "assumptions_calibrated": a.is_calibrated,
        "how_to_read": ("Each action alone, fully adopted (value 1.0 = all of its remaining opportunity), over the "
                        "forecast horizon. Profit change already includes operating savings; gross outlay is capex plus "
                        "extra running costs. Combined actions are not additive: use simulate_strategy for a mix and "
                        "optimize_strategies for the best mix within the constraints."),
        "is_mock": is_mock,
    }


def public_reference(electricity_reduction_ratio: float | None = None) -> dict:
    """Wincanton FY2024 disclosure (separate real company) plus the optional GOV.UK-factor scenario."""
    ref, factor = load_company_reference(), load_factors()["uk_electricity"]
    rows = ref["values"]
    v = {k: float(r["value"]) for k, r in rows.items()}
    s12 = v["emissions_scope1_and_2_total"]
    out: dict[str, Any] = {
        "kind": "public_reference",
        "relationship": ("Separate real company used only as a public reference. It is NOT the dashboard company, "
                         "and the optimizer never uses these figures."),
        "company": ref["company"],
        "about": "UK logistics company (warehouses and a truck fleet), operations in the UK and Ireland.",
        "period": f"{ref['period_start']} to {ref['period_end']} (financial year 2023/24)",
        "data_kind": "reported_historical",
        "source": {"title": ref["title"], "url": ref["source_url"]},
        "figures": {r["label"]: {"value": r["value"], "unit": r["unit"], "scope": r["scope"]} for r in rows.values()},
        "derived_from_figures": {
            "transport_fuel_share_of_scope1_2_pct": _pct(v["emissions_transport_scope1"], s12),
            "electricity_share_of_scope1_2_pct": _pct(v["emissions_electricity_transport"]
                                                     + v["emissions_electricity_non_transport"], s12),
            "scope1_2_tco2e_per_gbp_million_revenue": _r(s12 / v["revenue"]),
            "scope3_vs_scope1_2_pct": _pct(v["emissions_scope3"], s12),
        },
        "scopes_explained": SCOPES_EXPLAINED,
    }
    if electricity_reduction_ratio is not None:
        r = calculate_electricity_scenario(v["electricity_non_transport"] * 1000.0, electricity_reduction_ratio, 0.25,
                                           factor=factor)
        out["electricity_scenario"] = {
            "label": "2026-factor scenario using FY2024 activity; an assumption, not a Wincanton plan",
            "reduction_pct": _r(100 * electricity_reduction_ratio),
            "co2e_saved_tco2e_per_year": _r(r["saved_tco2e"], 2),
            "share_of_reported_scope1_2_pct": _pct(r["saved_tco2e"], s12),
            "modelled_baseline_tco2e": _r(r["baseline_tco2e"]),
            "scenario_tco2e": _r(r["scenario_tco2e"]),
            "gross_energy_cost_saving_gbp_per_year": round(r["gross_energy_savings_gbp"]),
            "assumed_tariff_gbp_per_kwh": 0.25,
            "factor": f"GOV.UK {factor['year']} UK electricity {factor['value']} kgCO2e/kWh (ID {factor['factor_id']})",
            "why_baseline_differs_from_reported": (
                f"The modelled baseline uses the 2026 factor ({factor['value']} kgCO2e/kWh). The reported FY2024 "
                f"electricity emissions imply about {v['emissions_electricity_non_transport'] / v['electricity_non_transport']:.3f}"
                " kgCO2e/kWh; the UK grid has become cleaner since."),
            "cost_note": "Gross energy-bill saving before any project costs; not profit.",
        }
    return out
