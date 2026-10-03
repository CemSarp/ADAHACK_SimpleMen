"""Deterministic text summaries of tool-result payloads.

Used by the mock model and by the template explanation. Every number comes
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
    status, name = payload.get("status"), payload.get("tool_name")
    if status != "ok":
        label = "unavailable" if status == "unavailable" else "failed"
        return f"The {name} tool {label}: {payload.get('error')}"
    data = payload.get("data") or {}
    mock = " (mock backend output)" if data.get("is_mock") else ""
    kind = data.get("kind")
    if kind == "baseline":
        t = data["totals"]
        return (f"Baseline forecast for {data['period']}: emissions {tonnes(t['total_co2e_tco2e'])}, "
                f"operating profit {gbp(t['operating_profit_gbp'])}, revenue {gbp(t['revenue_gbp'])}{mock}.")
    if kind == "simulation":
        m = data["metrics"]
        text = (f"Preview for this action mix{mock}: emissions {tonnes(m['total_co2e_tco2e'])} "
                f"({pct(m['co2_reduction_ratio'])} reduction), operating profit {gbp(m['total_profit_gbp'])} "
                f"({gbp(m['profit_change_gbp'])} vs baseline), gross outlay {gbp(m['total_cost_gbp'])}.")
        for c in data.get("conversions", []):
            text += (f" A final {c['action'].replace('_', ' ')} share of {pct(c['target_final_share'])} from a baseline "
                     f"{pct(c['baseline_share'])} needs {c['fraction_of_remaining']:.3f} of the remaining opportunity.")
        feas = data.get("feasibility")
        if feas is not None:
            text += " It meets all current constraints." if feas["feasible"] else (
                " It does not meet: " + ", ".join(feas["failed"]) + ".")
        return text
    if kind == "optimization":
        if data["status"] != "ok":
            return (f"No feasible plan was found within the search budget for budget {gbp(data['constraints']['budget_gbp'])}"
                    f"{mock}. Relaxing the budget, profit floor or target may help.")
        r = data["recommended"]
        m = r["metrics"]
        return (f"Found {data['pareto_count']} feasible frontier plans{mock}. Recommended {r['strategy_id']}: emissions "
                f"{tonnes(m['total_co2e_tco2e'])} ({pct(m['co2_reduction_ratio'])} reduction), profit "
                f"{gbp(m['total_profit_gbp'])}, gross outlay {gbp(m['total_cost_gbp'])}.")
    if kind == "risk":
        s = data["summary"]
        return (f"Over {data['n_simulations']:,} trials{mock} the target is met with probability "
                f"{pct(s['target_probability'])} and all constraints with {pct(s['joint_feasibility_probability'])} "
                f"(finite-trial estimates, not guarantees).")
    return "The tool returned a result."
