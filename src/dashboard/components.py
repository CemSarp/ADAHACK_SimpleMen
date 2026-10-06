"""Streamlit sections of the report-style page. All reads come from DashboardState and public
contract objects; all writes go through DashboardState."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import pandas as pd
import streamlit as st

from src.contracts.errors import CarbonOptError
from src.contracts.identity import canonical_hash
from src.contracts.serialization import to_json
from src.contracts.types import ACTION_NAMES, ActionAssumptions, ActionConfig, AnalysisRequest, SimulationResult
from src.data_sources.public_data import (
    GridFetchError,
    choose_one_hour_window,
    fetch_grid_forecast,
    load_grid_snapshot,
    normalize_grid_snapshot,
)
from src.forecasting.ws1_adapter import BENCHMARK, MODEL, available_models, compare_models
from src.integration.services import Services
from src.optimization import inactive_actions, relaxation_hints, risk_pool_from_frontier

from . import charts
from .presentation import (
    ACTION_HELP,
    ACTION_LABELS,
    ACTION_NEEDS,
    gbp,
    hint_lines,
    model_name,
    pct,
    period_label,
    resulting_share,
    short_gbp,
    tonnes,
    uncertainty_method,
)
from .state import COMPUTING, INFEASIBLE, PROVIDER_ERROR, READY, VALIDATION_ERROR, DashboardState, ErrorInfo, slider_key

logger = logging.getLogger(__name__)
MONEY = st.column_config.NumberColumn(format="£%,.0f")
PERCENT = st.column_config.NumberColumn(format="%.0f%%")


def section(number: int, label: str, title: str, lede: str | None = None) -> None:
    st.html(f'<div class="co-eyebrow">{number} · {label}</div>')
    st.subheader(title, anchor=False)
    if lede:
        st.caption(lede)


def figures(items: list[dict[str, Any]]) -> None:
    """Headline numbers in a row; they wrap on narrow screens instead of truncating."""
    with st.container(horizontal=True, wrap=True, gap="large"):
        for item in items:
            delta = item.get("delta")
            st.metric(item["label"], item["value"], delta=None if delta is None else delta.replace("−", "-"),
                      delta_color=item.get("delta_color", "normal"), help=item.get("help"), width="content")


def error_box(kind: str, error_type: str, message: str) -> None:
    logger.error("Dashboard %s (%s): %s", kind, error_type, message)
    if kind == VALIDATION_ERROR:
        st.error("These goals could not be used. Check the budget, profit floor and CO₂ target, then try again.")
    else:
        st.error("This analysis could not be completed. Try again; if it keeps failing, contact the administrator.")


def constraint_failures(check: Any) -> list[str]:
    """Labels of the goals the provider's evaluation failed. Uses the per-constraint `satisfied`
    flags when supplied, otherwise positive raw violations (test doubles)."""
    labels = (("budget", "budget_gbp", "budget"), ("profit", "profit_gbp", "profit floor"),
              ("target", "reduction_ratio", "CO₂ target"))
    satisfied = getattr(check, "satisfied", None) or {}
    if satisfied:
        return [label for flag, _, label in labels if not satisfied.get(flag, True)]
    return [label for _, raw, label in labels if check.raw_violations.get(raw, 0) > 0]


def available_actions(state: DashboardState, services: Services) -> tuple[str, ...]:
    """Actions this company's data supports; the rest change nothing and are hidden."""
    key = ("co_active_actions", state.baseline.baseline_id, services.assumptions.assumptions_id)
    if key not in st.session_state:
        off = inactive_actions(state.baseline, services.assumptions, services.simulator.simulate)
        st.session_state[key] = tuple(a for a in ACTION_NAMES if a not in off)
    return st.session_state[key]


def full_mix_cost(state: DashboardState, services: Services) -> float:
    """Spend of every action at full take-up: a budget above this buys nothing more."""
    key = ("co_full_cost", state.baseline.baseline_id, services.assumptions.assumptions_id)
    if key not in st.session_state:
        everything = ActionConfig.from_mapping(dict.fromkeys(ACTION_NAMES, 1.0))
        st.session_state[key] = float(services.simulate(state.baseline, everything).metrics["total_cost_gbp"])
    return st.session_state[key]


def _unavailable_note(active: tuple[str, ...]) -> None:
    off = [a for a in ACTION_NAMES if a not in active]
    if off:
        st.caption("Not available for this data: " + "; ".join(f"{ACTION_LABELS[a]} (needs {ACTION_NEEDS[a]})"
                                                                  for a in off) + ".")


# --------------------------------------------------------------------------- #
# Header and baseline
# --------------------------------------------------------------------------- #


def header(services: Services | None, state: DashboardState | None) -> None:
    st.title("CarbonOpt", anchor=False)
    st.html('<p class="co-lede">Find the action mix that cuts the most emissions for the money you can spend, '
            'without letting profit fall below the line you set.</p>')
    if services is None or state is None or state.history is None:
        return
    kind = "synthetic demo data" if state.baseline is not None and state.baseline.data_kind == "synthetic" else "your data"
    st.html(f'<p class="co-meta">{services.forecast.company_id} · {kind} · {period_label(state.history["timestamp"])}</p>')


def baseline_section(state: DashboardState, services: Services, dark: bool) -> None:
    section(1, "Starting point", "Where you are heading without new actions",
            "A 12-month forecast from your history. Every plan below is measured against it.")
    b = state.baseline
    if b is None:
        if state.baseline_error:
            e = state.baseline_error
            error_box(e.kind, e.error_type, e.message)
            with st.expander("Compare forecasting models", expanded=True):  # a model that cannot fit can be swapped back
                model_panel(services, dark)
        return
    m = b.monthly
    items = [
        {"label": "Emissions, next 12 months", "value": f"{m['total_co2e_tco2e'].sum():,.0f} tCO₂e"},
        {"label": "Revenue", "value": short_gbp(m["revenue_gbp"].sum())},
        {"label": "Operating profit", "value": short_gbp(m["operating_profit_gbp"].sum()),
         "help": "EBITDA used as operating profit."},
    ]
    report = state.backtest
    accuracy = (report.aggregate_metrics.get("total_co2e_tco2e") if report else None) or {}
    if accuracy.get("naive_mae"):
        gain = 1 - accuracy["mae"] / accuracy["naive_mae"]
        items.append({"label": "Forecast error vs a simple repeat", "value": pct(-gain, signed=True, decimals=0),
                      "help": "Average monthly emissions error over the last 12 months, compared with repeating "
                              "last year's month adjusted for the trend. Negative means the forecast is better."})
    figures(items)
    if state.history is not None:
        start, end = _timeline(state)
        for col, column in zip(st.columns(2, gap="large"), ("total_co2e_tco2e", "operating_profit_gbp")):
            col.plotly_chart(charts.history_forecast(state.history, b, column, start=start, end=end, dark=dark),
                             width="stretch", config={"displayModeBar": False})
    with st.expander("About this forecast and your data"):
        model = (report.selected_models.get("total_co2e_tco2e") if report else None) or b.model_id
        months = len(state.history) if state.history is not None else 0
        st.markdown(f"- Model: **{model_name(model)}**, refitted on all {months} months and checked on the last 12.\n"
                    "- Revenue and activity follow last year's months, scaled by recent growth.\n"
                    "- Emissions are split into scopes in their recent proportions.")
        notes = getattr(getattr(services.forecast, "imported", None), "transforms", ())
        if notes:
            st.caption("On import: " + "; ".join(notes) + ".")
    with st.expander("Compare forecasting models"):
        model_panel(services, dark)


def _timeline(state: DashboardState) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Months of history the charts show; reset to the last four years when the data changes."""
    months = list(state.history["timestamp"].sort_values())
    labels = [f"{m:%b %Y}" for m in months]
    if st.session_state.get("co_timeline_for") != state.baseline.baseline_id:
        st.session_state["co_timeline_for"] = state.baseline.baseline_id
        st.session_state.pop("co_widget_timeline", None)  # old labels may not exist in new data
    first, last = st.select_slider("History shown", options=labels, value=(labels[max(0, len(labels) - 48)], labels[-1]),
                                   key="co_widget_timeline",
                                   help="Drag either end. The forecast appears when the range reaches the latest month.")
    lookup = dict(zip(labels, months))
    return lookup[first], lookup[last]


def model_panel(services: Services, dark: bool) -> None:
    """Other forecasting models, scored on request only, and the choice of model for planning."""
    forecast = services.forecast
    imported = getattr(forecast, "imported", None)
    if imported is None:  # a forecast that is not WS1 has no models to compare
        st.caption("Model comparison is not available for this forecast.")
        return
    models = available_models()
    st.caption("Each model forecasts the last 12 months from the months before them, and its miss is compared with "
               "what really happened. Random forest and seasonal repeat take seconds; Prophet can take a minute or more.")
    picked = st.pills("Models to compare", models, selection_mode="multi", key="co_widget_models",
                      default=[m for m in (MODEL, BENCHMARK) if m in models], format_func=model_name) or []
    key = canonical_hash([imported.csv_sha256, imported.import_config.content_hash(), sorted(picked)])
    if st.button("Compare models", disabled=not picked, icon=":material/compare_arrows:"):
        bar = st.progress(0.0, text="Comparing models…")
        table = compare_models(imported, forecast.settings, forecast.config.horizon_months, tuple(picked),
                               progress=lambda done, total: bar.progress(done / total, text=f"Scored {done} of {total}"))
        bar.empty()
        st.session_state["co_model_comparison"] = {"key": key, "table": table}
    stored = st.session_state.get("co_model_comparison")
    if stored and stored["key"] == key:
        table = stored["table"]
        wide = table.pivot(index="model", columns="target", values="wape").reindex(picked)
        seconds = table.groupby("model")["seconds"].sum().reindex(picked)
        st.dataframe(pd.DataFrame({"Model": [model_name(m) for m in picked], "Emissions error": wide["emissions"],
                                   "Profit error": wide["profit"], "Time (s)": seconds}).reset_index(drop=True),
                     hide_index=True, width="stretch", key="co_model_table", column_config={
                         "Emissions error": st.column_config.NumberColumn(format="%.1f%%"),
                         "Profit error": st.column_config.NumberColumn(format="%.1f%%"),
                         "Time (s)": st.column_config.NumberColumn(format="%.1f")})
        st.plotly_chart(charts.model_errors(table, dark=dark), width="stretch", config={"displayModeBar": False})
        best = {t: wide[t].dropna().idxmin() for t in ("emissions", "profit") if wide[t].notna().any()}
        if best:
            winners = (f"{model_name(best['emissions'])} for both emissions and profit"
                       if len(best) == 2 and len(set(best.values())) == 1
                       else " and ".join(f"{model_name(m)} for {t}" for t, m in best.items()))
            st.caption(f"Lowest error: {winners}. Error is the average monthly miss as a share of the actual values.")
        for row in table[table["note"].notna()].itertuples():
            st.caption(f"{model_name(row.model)} could not be scored on this data ({row.target}).")
    st.selectbox("Forecast with", ("auto", *models), key="co_widget_forecast_model",
                 format_func=lambda m: "Automatic (random forest from 5 years of data, else seasonal repeat)"
                 if m == "auto" else model_name(m),
                 help="The forecast, plans and forecast drivers are rebuilt with this model. Forecast drivers need a "
                      "tree model (random forest, XGBoost or LightGBM).")


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #


def _consume_selection_events(state: DashboardState) -> None:
    """Apply a new chart click or table-row selection made on the previous run."""
    if state.analysis is None:
        return
    chart_event = st.session_state.get("co_widget_pareto")
    if chart_event is not None:
        points = chart_event.get("selection", {}).get("points", [])
        signature = repr([(p.get("curve_number"), p.get("point_index")) for p in points])
        if points and signature != st.session_state.get("co_last_pareto_event"):
            st.session_state["co_last_pareto_event"] = signature
            point = points[-1]
            sid = st.session_state.get("co_pareto_point_ids", {}).get((point.get("curve_number"), point.get("point_index")))
            if sid:
                try:
                    state.select_strategy(sid)
                except KeyError:
                    st.toast("Only plans on the best trade-off line can be selected.")
    table_event = st.session_state.get("co_widget_table")
    if table_event is not None:
        rows = table_event.get("selection", {}).get("rows", [])
        signature = repr(rows)
        if rows and signature != st.session_state.get("co_last_table_event"):
            st.session_state["co_last_table_event"] = signature
            ids = st.session_state.get("co_table_ids", [])
            if rows[0] < len(ids):
                state.select_strategy(ids[rows[0]])


def _strategy_name(sid: str | None, analysis: Any) -> str:
    ids = analysis.optimization.pareto.sort_values(["total_co2e_tco2e", "strategy_id"])["strategy_id"].tolist()
    return f"Plan {ids.index(sid) + 1}" if sid in ids else "No plan"


def _strategy_label(sid: str, analysis: Any) -> str:
    row = analysis.optimization.pareto.set_index("strategy_id").loc[sid]
    star = "★ " if sid == analysis.recommendation.strategy_id else ""
    return f"{star}{_strategy_name(sid, analysis)} · {tonnes(row['total_co2e_tco2e'], decimals=0)} · {gbp(row['total_profit_gbp'])}"


def recommendation_text(rec: Any) -> str:
    """Describe the existing policy without displaying internal field names."""
    if rec.risk_status == "not_requested":
        return "Recommended: the plan that best balances lower emissions against higher profit."
    if rec.risk_status == "unavailable":
        return "Uncertainty results are unavailable; the recommendation balances forecast emissions and profit."
    descriptions = {
        "conservative": "Balances high-emissions and low-profit trial outcomes, preferring plans with at least a 90% chance of meeting all goals.",
        "balanced": "Balances average trial emissions and profit, preferring plans with at least a 75% chance of meeting all goals.",
        "aggressive": "Prioritises average trial emissions reductions, with a smaller weight on profit.",
    }
    text = f"{rec.tolerance.capitalize()} approach: {descriptions[rec.tolerance]}"
    if rec.risk_status == "threshold_unmet":
        text += " No assessed plan met that probability threshold; the selected plan has the highest chance of meeting all goals."
    elif rec.risk_status == "partial":
        text += " Uncertainty results cover only part of the assessed plans."
    return text


def plan_figures(result: SimulationResult) -> None:
    m = result.metrics
    figures([
        {"label": "Emissions, next 12 months", "value": tonnes(m["total_co2e_tco2e"], decimals=0),
         "delta": f"{pct(-m['co2_reduction_ratio'], signed=True)} vs no action" if m["co2_reduction_ratio"] else None,
         "delta_color": "inverse"},
        {"label": "Operating profit", "value": short_gbp(m["total_profit_gbp"]),
         "delta": f"{gbp(m['profit_change_gbp'], signed=True)} vs no action" if m["profit_change_gbp"] else None},
        {"label": "Spend from budget", "value": short_gbp(m["total_cost_gbp"]),
         "help": "Up-front investment plus extra running costs over 12 months. Savings do not reduce it."},
        {"label": "Net cash, 12 months", "value": short_gbp(m["net_cash_impact_gbp"]),
         "help": "Savings minus extra running costs minus investment."},
    ])


def plans_section(state: DashboardState, services: Services, request: AnalysisRequest, dark: bool) -> None:
    section(2, "Plans", "Plans that meet your goals",
            "Each point is an action mix. The green line holds the plans you cannot beat on emissions without "
            "giving up profit. Click one to inspect it.")
    analysis, status = state.analysis, state.status
    if status in (VALIDATION_ERROR, PROVIDER_ERROR) and state.error:
        error_box(state.error.kind, state.error.error_type, state.error.message)
        return
    if analysis is None:
        if status == COMPUTING:
            st.info("Searching for plans…")
        elif state.invalidated:
            st.info("Your goals changed since the last search, so those plans were cleared. Press **Find plans** again.")
        else:
            st.info("Set your budget, profit floor and CO₂ target in the sidebar, then press **Find plans**.")
        return
    for warning in analysis.warnings:
        logger.warning("Analysis note: %s", warning)
    if analysis.warnings:
        st.caption("Some supporting results could not be produced; everything shown is complete.")
    opt = analysis.optimization
    if status == INFEASIBLE:
        st.error("No plan met all three goals. The search tried many mixes but none fitted the budget, kept profit "
                 "above the floor and reached the CO₂ target together.")
        lines = hint_lines(relaxation_hints(opt.candidates, request.constraints), request.constraints)
        st.markdown("**What would make it work** (each change on its own, from the mixes already tried):\n"
                    + "\n".join(f"- {line}" for line in lines))
    _consume_selection_events(state)
    pareto_fig = charts.pareto_scatter(opt, analysis.baseline, selected_id=state.selected_strategy_id,
                                       recommended_id=analysis.recommendation.strategy_id, whatif=state.whatif_result, dark=dark)
    st.session_state["co_pareto_point_ids"] = dict(pareto_fig.point_ids)
    st.plotly_chart(pareto_fig.figure, width="stretch", key="co_widget_pareto", on_select="rerun",
                    selection_mode="points", config={"displaylogo": False})
    if status != READY:
        return

    table = opt.pareto.sort_values(["total_co2e_tco2e", "strategy_id"]).reset_index(drop=True)
    ids = table["strategy_id"].tolist()
    st.session_state["co_table_ids"] = ids
    # A shortlist spread evenly along the line keeps the picker readable; the chart and table show every plan.
    keep = {*risk_pool_from_frontier(opt.pareto, max_size=25), analysis.recommendation.strategy_id, state.selected_strategy_id}
    shortlist = [sid for sid in ids if sid in keep]
    if state.selected_strategy_id in shortlist:
        st.session_state["co_widget_select"] = state.selected_strategy_id
    st.selectbox("Plan", shortlist, key="co_widget_select", format_func=lambda sid: _strategy_label(sid, analysis),
                 on_change=lambda: state.select_strategy(st.session_state["co_widget_select"]))
    st.caption("★ " + recommendation_text(analysis.recommendation))

    active = available_actions(state, services)
    selected = state.selected_strategy()
    if selected is not None:
        plan_figures(selected)
        mix = [f"{ACTION_LABELS[n]} {pct(getattr(selected.config, n), decimals=0)}" for n in active
               if getattr(selected.config, n) > 0.005]
        st.markdown("**Mix:** " + (" · ".join(mix) if mix else "no new actions"))
        st.plotly_chart(charts.scope_totals(analysis.baseline, {"selected": selected}, dark=dark), width="stretch",
                        config={"displayModeBar": False})

    with st.expander(f"Compare all {len(table)} plans"):
        display = pd.DataFrame({
            "": ["★" if sid == analysis.recommendation.strategy_id else "" for sid in ids],
            "Plan": [_strategy_name(sid, analysis) for sid in ids],
            "Emissions (tCO₂e)": table["total_co2e_tco2e"],
            "Cut": table["co2_reduction_ratio"] * 100.0,
            "Operating profit": table["total_profit_gbp"],
            "Spend": table["total_cost_gbp"],
            **{ACTION_LABELS[n]: table[n] * 100 for n in active},
        })
        st.dataframe(display, hide_index=True, width="stretch", key="co_widget_table", on_select="rerun",
                     selection_mode="single-row", column_config={
                         "Emissions (tCO₂e)": st.column_config.NumberColumn(format="%,.0f"), "Cut": PERCENT,
                         "Operating profit": MONEY, "Spend": MONEY, **{ACTION_LABELS[n]: PERCENT for n in active}})
        st.caption("Action percentages are the share of each remaining opportunity a plan takes up. Select a row to "
                   "inspect that plan.")


# --------------------------------------------------------------------------- #
# Your own mix
# --------------------------------------------------------------------------- #


def whatif_section(state: DashboardState, services: Services, request: AnalysisRequest, dark: bool) -> None:
    section(3, "Your mix", "Try your own mix",
            "Each slider is the share of that action's remaining opportunity you take up from the first month.")
    baseline = state.baseline
    active = available_actions(state, services)
    selected = state.selected_strategy()
    with st.container(horizontal=True):
        st.button("Start from the selected plan", disabled=selected is None,
                  on_click=lambda: state.load_whatif(state.selected_strategy().config))
        st.button("Reset", on_click=lambda: state.load_whatif(type(state.whatif_config).noop()))
    cols = st.columns(3)
    for i, name in enumerate(active):
        with cols[i % 3]:
            key = slider_key(name)
            st.slider(ACTION_LABELS[name], min_value=0.0, max_value=1.0, step=0.01, key=key, format="percent",
                      help=ACTION_HELP[name], on_change=lambda n=name, k=key: state.set_whatif_action(n, st.session_state[k]))
            share = resulting_share(baseline, name, getattr(state.whatif_config, name), services.assumptions)
            if share is not None:
                label = "Renewable share" if name == "renewable_energy" else "EV share of fleet"
                st.caption(f"{label}: {share.describe()}")
    _unavailable_note(active)

    result = state.ensure_whatif(services)
    if state.whatif_error:
        e = state.whatif_error
        error_box(e.kind, e.error_type, e.message)
        return
    if result is None:
        return
    if not any(result.config.as_vector()):
        st.caption("Move a slider, or start from the selected plan, to see what a mix does.")
        return
    plan_figures(result)
    check = state.whatif_constraint_check(services, request)
    if check is not None:
        if check.feasible:
            st.success("This mix meets your budget, profit floor and CO₂ target.")
        else:
            st.warning("This mix misses: " + ", ".join(constraint_failures(check) or ["a goal, narrowly"]) + ".")
    if selected is not None and result.strategy_id == selected.strategy_id:
        if all(result.metrics[k] == selected.metrics[k] for k in selected.metrics):
            st.caption("Matches the selected plan.")
        else:
            logger.error("What-if differs from stored strategy %s", selected.strategy_id)
            st.warning("The preview could not reproduce the selected plan. Please search again.")
    scenarios = {"whatif": result, **({"selected": selected} if selected is not None else {})}
    st.plotly_chart(charts.scope_totals(baseline, scenarios, dark=dark), width="stretch", config={"displayModeBar": False},
                    key="co_whatif_scopes")


# --------------------------------------------------------------------------- #
# Confidence
# --------------------------------------------------------------------------- #


def confidence_section(state: DashboardState, services: Services, request: AnalysisRequest, dark: bool) -> None:
    section(4, "Confidence", "How sure can you be?",
            "Optional checks. Turn them on under Also check in the sidebar before searching.")
    caps, analysis = services.capabilities, state.analysis
    labels = ["Uncertainty", "Risk appetite", "Peers"] + (["Forecast drivers"] if caps.shap_available_targets else [])
    tabs = dict(zip(labels, st.tabs(labels)))

    with tabs["Uncertainty"]:
        if caps.risk_available:
            with st.expander("How this is calculated", icon=":material/casino:"):
                st.markdown(uncertainty_method(services.risk, trials=request.risk_config.n_simulations))
        if not caps.risk_available:
            st.caption("Uncertainty analysis is not available.")
        elif not request.risk_enabled or analysis is None:
            st.caption("Turn on **Uncertainty** and search to see how often plans still meet your goals when costs "
                       "and effects vary.")
        else:
            sid = state.selected_strategy_id
            risk = analysis.risk_results.get(sid) if sid else None
            if sid is None:
                st.caption("No plan is selected, so there is nothing to assess yet.")
            elif risk is None:
                st.caption("The selected plan was not among the plans assessed.")
            else:
                s = risk.summary
                figures([
                    {"label": "Chance of all goals", "value": pct(s["joint_feasibility_probability"], decimals=0)},
                    {"label": "CO₂ target", "value": pct(s["target_probability"], decimals=0),
                     "help": f"Sampling error ±{pct(s['target_probability_mc_standard_error'])}."},
                    {"label": "Profit floor", "value": pct(s["profit_floor_probability"], decimals=0)},
                    {"label": "Budget", "value": pct(s["budget_probability"], decimals=0)},
                ])
                st.plotly_chart(charts.risk_intervals(risk, state.selected_strategy(), dark=dark), width="stretch",
                                config={"displayModeBar": False})
                st.caption(f"{risk.n_simulations:,} trials for the selected plan; {len(analysis.risk_results)} plans "
                           "assessed. Bars span the middle 90% of trial outcomes.")

    with tabs["Risk appetite"]:
        scenario_panel(state, services, request)

    with tabs["Peers"]:
        if not caps.benchmark_available:
            st.caption("Peer comparison is not available.")
        elif analysis is None or analysis.benchmark is None:
            st.caption("Turn on **Peers** and search to compare your emissions intensity with similar companies.")
        elif analysis.benchmark.status != "ok":
            logger.info("Benchmark unavailable: %s", analysis.benchmark.reason)
            st.caption("No comparable peer group was found for this company's data.")
        else:
            b = analysis.benchmark
            st.markdown(f"Your forecast intensity is lower than about **{b.better_than_pct:.0f}%** of {b.peer_count} peers.")
            st.plotly_chart(charts.benchmark_position(b, dark=dark), width="stretch", config={"displayModeBar": False})
            st.caption(f"{'Synthetic' if b.is_synthetic else 'Reported'} peer data · coverage "
                       f"{b.scope_coverage.replace('_', ' ')}. Your forecast is compared with peers' reported years.")

    if "Forecast drivers" in tabs:
        with tabs["Forecast drivers"]:
            if analysis is None or analysis.explanation is None:
                st.caption("Turn on **Forecast drivers** and search to see which inputs move the forecast. They need a "
                           "tree model (random forest, XGBoost or LightGBM).")
            else:
                drivers_panel(analysis.explanation, dark)


def drivers_panel(exp: Any, dark: bool) -> None:
    """SHAP contributions of the forecast's inputs, keeping the k that matter most."""
    st.caption("Which inputs push the forecast up or down. This explains the forecast, not the plans.")
    present = set(exp.contributions["target"])
    targets = [t for t in charts.TARGET_LABELS if t in present] + sorted(present - set(charts.TARGET_LABELS))
    most = int(exp.contributions.groupby("target")["feature"].nunique().max())
    k = most if most < 2 else st.slider("Inputs to show", min_value=1, max_value=most, value=min(5, most),
                                        key="co_widget_topk", help="The rest are grouped into one bar.")
    for tab, target in zip(st.tabs([charts.TARGET_LABELS.get(t, t) for t in targets]), targets):
        with tab:
            share = charts.shap_importance(exp, target)
            top = min(k, len(share))
            st.caption(f"The top {top} inputs carry {share.iloc[:top].sum():.0%} of how much this forecast moves. "
                       "Green inputs raise it on average, red ones lower it.")
            st.plotly_chart(charts.shap_top_k(exp, target, top, dark=dark), width="stretch",
                            config={"displayModeBar": False})
    missing = set(charts.TARGET_LABELS) - set(targets)
    if missing:
        st.caption("Not shown for " + ", ".join(charts.TARGET_LABELS[t].split(" (")[0].lower() for t in sorted(missing))
                   + ": its forecast model is not a tree model.")


def scenario_panel(state: DashboardState, services: Services, request: AnalysisRequest) -> None:
    """Conservative / balanced / aggressive selections from WS2's policy on one analysis."""
    if not services.capabilities.scenario_compare_available:
        st.caption("Risk appetite comparison is not available.")
        return
    analysis = state.analysis
    if analysis is None or not request.risk_enabled:
        st.caption("Turn on **Uncertainty** and search to compare cautious, balanced and bold choices.")
        return
    result = state.scenarios(services)
    if isinstance(result, ErrorInfo):
        error_box(result.kind, result.error_type, result.message)
        return
    if not result:
        return
    opt = analysis.optimization
    rows = []
    for tol, rec in result.items():
        row: dict[str, Any] = {"Approach": tol.capitalize(), "Plan": _strategy_name(rec.strategy_id, analysis)}
        if rec.strategy_id is not None:
            m = opt.strategies[rec.strategy_id].metrics
            risk = analysis.risk_results.get(rec.strategy_id)
            row.update({"Emissions (tCO₂e)": m["total_co2e_tco2e"], "Cut": (m["co2_reduction_ratio"] or 0) * 100,
                        "Operating profit": m["total_profit_gbp"], "Spend": m["total_cost_gbp"],
                        "Chance of all goals": None if risk is None else risk.summary["joint_feasibility_probability"] * 100})
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "Emissions (tCO₂e)": st.column_config.NumberColumn(format="%,.0f"), "Cut": PERCENT,
        "Operating profit": MONEY, "Spend": MONEY, "Chance of all goals": PERCENT})
    picked = {rec.strategy_id for rec in result.values()}
    st.caption(f"All approaches use the same forecast, goals and {len(analysis.risk_results)} assessed plans"
               + ("; they agree on one plan here." if len(picked) == 1 else ".")
               + " Probabilities are estimates under illustrative uncertainty.")
    for rec in result.values():
        if rec.reason:
            st.caption(recommendation_text(rec))


# --------------------------------------------------------------------------- #
# Timing: the cleanest hour on the GB grid
# --------------------------------------------------------------------------- #

GRID_LIVE_KEY = "co_grid_live"
GRID_MAX_AGE = dt.timedelta(minutes=30)  # same as the fetch cache
LONDON = "Europe/London"


@st.cache_data(ttl=1800, show_spinner=False)
def _grid_forecast(slot_start: dt.datetime) -> dict:
    return fetch_grid_forecast(slot_start)  # failures raise and are not cached


def _london(ts: Any, fmt: str = "%d %b %H:%M") -> str:
    return pd.Timestamp(ts).tz_convert(LONDON).strftime(fmt)


def timing_section(state: DashboardState, dark: bool) -> None:
    section(5, "Timing", "When the grid is cleanest",
            "GB grid electricity is cleaner at some hours than others. Moving flexible use, such as charging, batch "
            "jobs or pre-heating, to the cleanest hour cuts emissions at no cost. Useful for sites in Great Britain.")
    history = state.history
    hourly = float(history.tail(12)["electricity_kwh"].sum()) / 8760 if history is not None else 0.0
    kwh = st.number_input("Electricity moved (kWh in one hour)", min_value=1.0, step=10.0, format="%.0f",
                          value=float(round(hourly)) if hourly >= 1 else 100.0,
                          key=f"co_widget_grid_kwh_{state.baseline.company_id}",
                          help="Starts at your average hourly electricity use over the last 12 months.")
    now = dt.datetime.now(dt.timezone.utc)
    row = st.container(horizontal=True, vertical_alignment="center")
    if row.button("Get the live forecast", icon=":material/refresh:", key="co_grid_refresh"):
        try:  # no network call happens unless this button is pressed
            st.session_state[GRID_LIVE_KEY] = _grid_forecast(now.replace(minute=now.minute // 30 * 30, second=0,
                                                                         microsecond=0))
        except GridFetchError:
            logger.warning("Live grid forecast unavailable", exc_info=True)
            st.session_state.pop(GRID_LIVE_KEY, None)  # never keep showing an older response as live
            st.caption("The live forecast could not be reached, so the saved example is shown.")
    live = st.session_state.get(GRID_LIVE_KEY)
    if live and now - pd.Timestamp(live["fetched_at"]).to_pydatetime() > GRID_MAX_AGE:
        st.session_state.pop(GRID_LIVE_KEY, None)
        live = None
    try:
        snap = live or load_grid_snapshot()
        df = normalize_grid_snapshot(snap)
    except (OSError, ValueError):
        logger.exception("Grid forecast unavailable")
        st.caption("The grid forecast is not available right now.")
        return
    if df.empty:
        st.caption("The grid forecast contains no half-hours.")
        return
    row.badge("Live forecast" if live else "Saved example", icon=":material/sensors:" if live else ":material/history:",
              color="green" if live else "gray")
    as_of = now if live else df["from"].iloc[0].to_pydatetime()  # the saved example replays its own period
    window = choose_one_hour_window(df, energy_kwh=kwh, as_of=as_of)
    if window is not None:
        base, best = window["baseline_kgco2"], window["best_kgco2"]
        less = f", {(base - best) / base:.0%} less" if base > 0 else ""
        text = (f"**{_london(window['best_start'])}–{_london(window['best_end'], '%H:%M')}** UK time: "
                f"{best:,.1f} kg CO₂ instead of {base:,.1f} kg if started at {_london(window['baseline_start'], '%H:%M')}"
                f"{less}.")
        (st.success if live else st.info)(("Best upcoming hour " if live else "Cleanest hour in the saved forecast ")
                                          + text, icon=":material/eco:")
    local = df["from"].dt.tz_convert(LONDON).dt.tz_localize(None)
    best_range = None if window is None else tuple(pd.Timestamp(window[k]).tz_convert(LONDON).tz_localize(None)
                                                   for k in ("best_start", "best_end"))
    st.plotly_chart(charts.grid_intensity(local, df["forecast_gco2_per_kwh"], best_range, dark=dark),
                    width="stretch", config={"displayModeBar": False})
    covers = f"{_london(df['from'].iloc[0])} to {_london(df['to'].iloc[-1])}"
    st.caption(("Live forecast" if live else "Saved example forecast, a replay rather than advice for today")
               + f", covering {covers} UK time. GB average generation CO₂ from the Carbon Intensity API (NESO, "
               "CC BY 4.0); not added to your company totals.")


# --------------------------------------------------------------------------- #
# Assumptions and export
# --------------------------------------------------------------------------- #


def assumptions_section(assumptions: ActionAssumptions, state: DashboardState) -> None:
    section(6, "Assumptions", "What the numbers rest on")
    calibrated = "calibrated" if assumptions.is_calibrated else "**illustrative, not calibrated**"
    st.markdown(
        f"Action costs and effects are {calibrated}. Review them before acting on a plan.\n\n"
        "- **Budget** counts up-front investment plus extra running costs over 12 months; savings do not offset it.\n"
        "- **Profit floor** is total operating profit over the 12 months. Investment reaches profit only through "
        "depreciation.\n"
        "- **CO₂ target** compares a plan's 12-month emissions with the forecast without new actions."
    )
    with st.expander("Action costs, prices and factors"):
        costs = pd.DataFrame([{"Action": ACTION_LABELS[n], "Investment at full take-up": c.capex_at_full_gbp,
                               "Running cost per month": c.monthly_opex_at_full_gbp, "Asset life (months)": c.asset_life_months}
                              for n, c in ((n, assumptions.costs[n]) for n in ACTION_NAMES)])
        st.dataframe(costs, hide_index=True, width="stretch",
                     column_config={"Investment at full take-up": MONEY, "Running cost per month": MONEY})
        prices = {
            "electricity_gbp_per_kwh": "Electricity (£/kWh)", "gas_gbp_per_kwh": "Gas (£/kWh)",
            "renewable_premium_gbp_per_kwh": "Renewable premium (£/kWh)", "ice_fuel_gbp_per_km": "Fleet fuel (£/km)",
            "travel_gbp_per_km": "Business travel (£/km)", "cloud_gbp_per_hour": "Cloud computing (£/hour)",
            "ev_kwh_per_km": "EV energy use (kWh/km)", "grid_tco2e_per_kwh": "Grid emissions (tCO₂e/kWh)",
        }
        st.dataframe(pd.DataFrame([(label, getattr(assumptions, f)) for f, label in prices.items()],
                                  columns=["Price or factor", "Value"]), hide_index=True, width="stretch",
                     column_config={"Value": st.column_config.NumberColumn(format="%.4g")})
        st.caption(assumptions.description)
    analysis = state.analysis
    if analysis is not None:
        try:
            payload = to_json(analysis, indent=2)
        except CarbonOptError:
            logger.exception("Analysis serialization failed")
        else:
            st.download_button("Download the full analysis (JSON)", payload, file_name="carbonopt-analysis.json",
                               mime="application/json", icon=":material/download:")
