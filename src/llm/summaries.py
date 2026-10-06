"""Deterministic text summaries of tool-result payloads.

Used by the mock model and as the fallback answer text. Every number comes
straight from the payload; nothing is estimated or invented.
"""

from __future__ import annotations

from typing import Any, Mapping


def gbp(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{'-' if v < 0 else ''}£{abs(v):,.0f}"


def tonnes(v: float | None) -> str:
    return "n/a" if v is None else f"{v:,.1f} tCO2e"


def pct(ratio: float | None) -> str:
    return "n/a" if ratio is None else f"{ratio * 100:.1f}%"


def summarize_payload(payload: Mapping[str, Any]) -> str:
    """payload = {"status", "tool_name", "data", "error"} as sent to the model."""
    status = payload.get("status")
    if status != "ok":
        label = "is currently unavailable" if status == "unavailable" else "could not be completed"
        return f"That analysis {label}. Review your settings or try again."
    data = payload.get("data") or {}
    mock = " (mock backend output)" if data.get("is_mock") else ""
    kind = data.get("kind")
    if kind == "baseline":
        t = data["totals"]
        text = (f"Baseline forecast for {data['period']}: emissions {tonnes(t['total_co2e_tco2e'])}, "
                f"operating profit {gbp(t['operating_profit_gbp'])}, revenue {gbp(t['revenue_gbp'])}{mock}.")
        f = data.get("forecast") or {}
        if f.get("model"):
            text += f" Model: {f['model']}."
        e = (f.get("accuracy_last_12_months") or {}).get("emissions")
        if e:
            text += (f" On the last 12 months it missed emissions by {e['average_monthly_miss']:,.1f} tCO2e a month on "
                     f"average, against {e['simple_repeat_miss']:,.1f} for repeating last year.")
        return text
    if kind == "simulation":
        m = data["metrics"]
        text = (f"Preview for this action mix{mock}: emissions {tonnes(m['total_co2e_tco2e'])} "
                f"({pct(m['co2_reduction_ratio'])} reduction), operating profit {gbp(m['total_profit_gbp'])} "
                f"({gbp(m['profit_change_gbp'])} vs baseline), gross outlay {gbp(m['total_cost_gbp'])}.")
        for c in data.get("conversions", []):
            text += (f" A final {c['action'].replace('_', ' ')} share of {pct(c['target_final_share'])} from a baseline "
                     f"{pct(c['baseline_share'])} needs {pct(c['fraction_of_remaining'])} of the remaining opportunity.")
        feas = data.get("feasibility")
        if feas is not None:
            text += " It meets all current constraints." if feas["feasible"] else (
                " It does not meet: " + ", ".join(feas["failed"]) + ".")
        return text
    if kind == "optimization":
        if data["status"] != "ok":
            text = f"No plan met all goals with a budget of {gbp(data['constraints']['budget_gbp'])}{mock}."
            h = data.get("how_to_meet_goals") or {}
            if h.get("budget_gbp_needed") is not None:
                text += f" The goals could be met with a budget of about {gbp(h['budget_gbp_needed'])}."
            if h.get("deepest_cut_within_budget_and_floor") is not None:
                text += f" Within this budget and profit floor the deepest cut is {pct(h['deepest_cut_within_budget_and_floor'])}."
            return text
        r = data["recommended"]
        m = r["metrics"]
        return (f"Found {data['pareto_count']} feasible frontier plans{mock}. Recommended action mix: emissions "
                f"{tonnes(m['total_co2e_tco2e'])} ({pct(m['co2_reduction_ratio'])} reduction), profit "
                f"{gbp(m['total_profit_gbp'])}, gross outlay {gbp(m['total_cost_gbp'])}.")
    if kind == "risk":
        s = data["summary"]
        return (f"Over {data['n_simulations']:,} trials{mock} the target is met with probability "
                f"{pct(s['target_probability'])} and all constraints with {pct(s['joint_feasibility_probability'])} "
                f"(finite-trial estimates, not guarantees).")
    if kind == "company_profile":
        hist = data.get("history")
        f = data["baseline_forecast"]["emissions"]
        text = (f"Baseline forecast ({data['baseline_forecast']['period']}): {tonnes(f['total_tco2e'])}, of which "
                f"Scope 1 {f['share_pct']['scope1']}%, Scope 2 {f['share_pct']['scope2']}%, "
                f"Scope 3 {f['share_pct']['scope3']}%.")
        if hist:
            w = hist["last_12_months"]
            text += (f" Last 12 months ({w['period']}): {tonnes(w['emissions']['total_tco2e'])}, operating profit "
                     f"{gbp(w['operating_profit_gbp'])}.")
        return text + f" {data['data_note']}"
    if kind == "action_comparison":
        rows = {r["action"]: r for r in data["actions"]}
        if not data["ranked_by_co2_cut"]:
            return "None of the actions changes emissions for this company under the current assumptions."
        top = rows[data["ranked_by_co2_cut"][0]]
        m = top["alone_at_full_adoption_over_horizon"]
        text = (f"On its own, {top['label'].lower()} cuts the most: {tonnes(m['co2_cut_tco2e'])} "
                f"({m['co2_cut_pct_of_total_baseline']}% of total baseline emissions) for a gross outlay of {gbp(m['gross_outlay_gbp'])}"
                f"{mock}.")
        if data["no_effect_for_this_company"]:
            text += " No effect for this company: " + ", ".join(
                rows[a]["label"].lower() for a in data["no_effect_for_this_company"]) + "."
        return text + " Action costs are illustrative assumptions."
    if kind == "forecast_drivers":
        parts = []
        for label, t in data["targets"].items():
            top = t["top_inputs"][0]
            parts.append(f"{top['input']} moves the {label.replace('_', ' ')} forecast most ({top['share_pct']}% of its "
                         f"movement, pushing it {top['pushes_forecast']})")
        return ("; ".join(parts) + ".") if parts else "No forecast drivers are available."
    if kind == "public_reference":
        d = data["derived_from_figures"]
        text = (f"{data['company']} ({data['period']}, a separate real company): transport fuel is "
                f"{d['transport_fuel_share_of_scope1_2_pct']}% and electricity {d['electricity_share_of_scope1_2_pct']}% "
                "of its reported Scope 1 and 2 emissions.")
        sc = data.get("electricity_scenario")
        if sc:
            text += (f" Cutting its electricity use by {sc['reduction_pct']}% would save about "
                     f"{tonnes(sc['co2e_saved_tco2e_per_year'])} a year ({sc['label']}).")
        return text
    return "The tool returned a result."
