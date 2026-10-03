"""Streamlit rendering components. All reads come from DashboardState and
public contract objects; all writes go through DashboardState."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import streamlit as st

from src.contracts.errors import CarbonOptError
from src.contracts.serialization import to_json
from src.contracts.types import ACTION_NAMES, ActionAssumptions, AnalysisRequest, SimulationResult
from src.integration.services import Services

from . import charts, eda, explain, trainer
from .presentation import (
    ACTION_HELP,
    ACTION_LABELS,
    gbp,
    pct,
    period_label,
    resulting_share,
    tonnes,
    trailing_window,
)
from .state import (
    COMPUTING,
    INFEASIBLE,
    PROVIDER_ERROR,
    READY,
    VALIDATION_ERROR,
    DashboardState,
    ErrorInfo,
    slider_key,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


def constraint_failures(check: Any) -> list[str]:
    """Labels of the constraints the provider's evaluation failed. Uses the per-constraint
    `satisfied` flags when the optimizer provider supplies them (WS2), otherwise falls back
    to positive raw violations (fixture/behavioral doubles)."""
    labels = (("budget", "budget_gbp", "budget"), ("profit", "profit_gbp", "profit floor"),
              ("target", "reduction_ratio", "CO₂ target"))
    satisfied = getattr(check, "satisfied", None) or {}
    if satisfied:
        return [label for flag, _, label in labels if not satisfied.get(flag, True)]
    return [label for _, raw, label in labels if check.raw_violations.get(raw, 0) > 0]


def error_box(kind: str, error_type: str, message: str) -> None:
    logger.error("Dashboard %s (%s): %s", kind, error_type, message)
    if kind == VALIDATION_ERROR:
        st.error("These inputs could not be used. Review your planning goals and try again.", icon="🚫")
    else:
        st.error("This analysis could not be completed. Try again or contact the application administrator.", icon="🛑")


def kpi_row(items: list[dict[str, Any]]) -> None:
    """Metric tiles that wrap on narrow screens instead of truncating values.
    Deltas use an ASCII sign because Streamlit colours deltas by a leading "-"."""
    with st.container(horizontal=True, wrap=True, gap="medium"):
        for item in items:
            delta = item.get("delta")
            st.metric(
                item["label"], item["value"],
                delta=None if delta is None else delta.replace("−", "-"),
                delta_color=item.get("delta_color", "normal"),
                delta_description=item.get("delta_description"),
                help=item.get("help"), width="content", border=True,
            )


# --------------------------------------------------------------------------- #
# Company context, baseline, backtest
# --------------------------------------------------------------------------- #


def company_context(state: DashboardState, dark: bool) -> None:
    if state.baseline is not None and state.baseline.data_kind == "synthetic":
        st.caption("Synthetic data · results use illustrative company data and action assumptions.")
    eda.feature_explorer()
    trainer.model_trainer()
    explain.shap_explorer()
    baseline = state.baseline
    if baseline is None:
        if state.baseline_error:
            e = state.baseline_error
            error_box(e.kind, e.error_type, e.message)
        return


def backtest_panel(state: DashboardState, dark: bool) -> None:
    report = state.backtest
    st.subheader("Forecast accuracy")
    st.caption("Compare predictions with held-out history to judge how reliable the forecast is.")
    if report is None:
        st.info("Historical forecast evaluation is currently unavailable.", icon="ℹ️")
        return
    rows = []
    for target, m in report.aggregate_metrics.items():
        beats = m["mae"] < m["naive_mae"]
        rows.append({
            "Target": charts.TARGET_LABELS.get(target, target),
            "Selected model": report.selected_models.get(target, report.model_family),
            "MAE": m["mae"], "RMSE": m["rmse"], "R²": m.get("r2"),
            "Seasonal-naive MAE": m["naive_mae"], "Seasonal-naive RMSE": m["naive_rmse"],
            "Beats naive (MAE)": "Yes" if beats else "No",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "MAE": st.column_config.NumberColumn(format="%.2f"), "RMSE": st.column_config.NumberColumn(format="%.2f"),
        "R²": st.column_config.NumberColumn(format="%.3f"),
        "Seasonal-naive MAE": st.column_config.NumberColumn(format="%.2f"),
        "Seasonal-naive RMSE": st.column_config.NumberColumn(format="%.2f"),
    })
    n_folds = report.folds["fold_id"].nunique()
    horizons = (f" and horizons 1–{int(report.oof_predictions['horizon'].max())}"
                if "horizon" in report.oof_predictions.columns and len(report.oof_predictions) else "")
    st.caption(f"Evaluation covers {n_folds} historical forecast dates{horizons}. "
               "MAE is the average absolute error; RMSE gives more weight to large errors. "
               "Lower errors are better; R² closer to 1 indicates a better fit. "
               "The seasonal reference repeats the same month from the previous year. "
               "Error units are tonnes of CO₂e or pounds per month."
               + (" The chart shows predictions one month ahead." if horizons else ""))
    targets = [t for t in report.aggregate_metrics]
    tabs = st.tabs([charts.TARGET_LABELS.get(t, t) for t in targets])
    for tab, target in zip(tabs, targets):
        with tab:
            st.plotly_chart(charts.backtest_predictions(report, target, dark=dark), width="stretch")


# --------------------------------------------------------------------------- #
# Optimization, Pareto, selection
# --------------------------------------------------------------------------- #


def _consume_selection_events(state: DashboardState) -> None:
    """Apply a new Pareto click or table-row selection made on the previous run."""
    analysis = state.analysis
    if analysis is None:
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
                    st.toast("Only feasible Pareto strategies can be selected.", icon="ℹ️")
    table_event = st.session_state.get("co_widget_table")
    if table_event is not None:
        rows = table_event.get("selection", {}).get("rows", [])
        signature = repr(rows)
        if rows and signature != st.session_state.get("co_last_table_event"):
            st.session_state["co_last_table_event"] = signature
            ids = st.session_state.get("co_table_ids", [])
            if rows[0] < len(ids):
                state.select_strategy(ids[rows[0]])


def _strategy_label(sid: str, analysis: Any) -> str:
    row = analysis.optimization.pareto.set_index("strategy_id").loc[sid]
    star = "★ " if sid == analysis.recommendation.strategy_id else ""
    return f"{star}{_strategy_name(sid, analysis)} · {tonnes(row['total_co2e_tco2e'])} · {gbp(row['total_profit_gbp'])}"


def _strategy_name(sid: str | None, analysis: Any) -> str:
    ids = analysis.optimization.pareto.sort_values(["total_co2e_tco2e", "strategy_id"])["strategy_id"].tolist()
    return f"Plan {ids.index(sid) + 1}" if sid in ids else "No plan"


def recommendation_text(rec: Any) -> str:
    """Describe the existing policy without displaying internal field names."""
    if rec.risk_status == "not_requested":
        return "Recommendation balances emissions reductions and operating profit across feasible plans."
    if rec.risk_status == "unavailable":
        return "Uncertainty results are unavailable; the recommendation balances forecast emissions and profit."
    descriptions = {
        "conservative": "Balances high-emissions and low-profit trial outcomes, preferring plans with at least a 90% chance of meeting all goals.",
        "balanced": "Balances average trial emissions and profit, preferring plans with at least a 75% chance of meeting all goals.",
        "aggressive": "Prioritises average trial emissions reductions, with a smaller weight on profit.",
    }
    text = f"{rec.tolerance.capitalize()} approach: {descriptions[rec.tolerance]}"
    if rec.risk_status == "threshold_unmet":
        text += " No evaluated plan met that probability threshold; the selected plan has the highest chance of meeting all goals."
    elif rec.risk_status == "partial":
        text += " Uncertainty results cover only part of the assessed plan set."
    return text


def optimization_panel(state: DashboardState, services: Services, request: AnalysisRequest, dark: bool) -> None:
    analysis = state.analysis
    st.subheader("Optimized strategies")
    st.caption("Compare action mixes that meet your goals. The frontier shows the best available trade-offs between emissions and profit.")
    status = state.status
    if status in (VALIDATION_ERROR, PROVIDER_ERROR) and state.error:
        error_box(state.error.kind, state.error.error_type, state.error.message)
        return
    if analysis is None:
        if status == COMPUTING:
            st.info("Optimizing…", icon="⏳")
        elif state.invalidated:
            st.info("Inputs changed since the last optimization, so the previous results were discarded. "
                    "Press **Optimize** to compute results for the current inputs.", icon="🔄")
        else:
            st.info("Set the budget, profit floor and CO₂ target in the sidebar, then press **Optimize**.", icon="👈")
        return

    opt = analysis.optimization
    diag = opt.diagnostics
    kpi_row([
        {"label": "Feasible plans", "value": f"{diag.get('feasible_count', 0):,}"},
        {"label": "Frontier plans", "value": f"{len(opt.pareto):,}"},
    ])
    for warning in analysis.warnings:
        logger.warning("Analysis note: %s", warning)
    if analysis.warnings:
        st.warning("Some supporting results could not be produced. Available results are shown below.")

    if status == INFEASIBLE:
        st.error(
            "**No feasible recommendation found.** No evaluated strategy met all three constraints within the "
            "search budget (this is not a proof that none exists). Relax the budget, profit floor or CO₂ target "
            "and optimize again.", icon="🚫",
        )
    _consume_selection_events(state)

    pareto_fig = charts.pareto_scatter(
        opt, analysis.baseline, selected_id=state.selected_strategy_id,
        recommended_id=analysis.recommendation.strategy_id, whatif=state.whatif_result, dark=dark,
    )
    st.session_state["co_pareto_point_ids"] = dict(pareto_fig.point_ids)
    st.plotly_chart(pareto_fig.figure, width="stretch", key="co_widget_pareto", on_select="rerun",
                    selection_mode="points", config={"displaylogo": False})
    if status != READY:
        return
    st.caption("Click a frontier point or use the selector to choose a plan. Open Compare plan details for the full table. ★ marks the recommendation.")

    table = opt.pareto.sort_values(["total_co2e_tco2e", "strategy_id"]).reset_index(drop=True)
    st.session_state["co_table_ids"] = table["strategy_id"].tolist()
    display = pd.DataFrame({
        "": ["★" if sid == analysis.recommendation.strategy_id else "" for sid in table["strategy_id"]],
        "Plan": [_strategy_name(sid, analysis) for sid in table["strategy_id"]],
        "Emissions (tCO₂e)": table["total_co2e_tco2e"],
        "CO₂ reduction (%)": table["co2_reduction_ratio"] * 100.0,
        "Cumulative profit (£)": table["total_profit_gbp"],
        "Gross outlay (£)": table["total_cost_gbp"],
        **{ACTION_LABELS[n]: table[n] * 100 for n in ACTION_NAMES},
    })
    with st.expander("Compare plan details"):
        st.dataframe(
            display, hide_index=True, width="stretch", key="co_widget_table", on_select="rerun", selection_mode="single-row",
            column_config={
                "Emissions (tCO₂e)": st.column_config.NumberColumn(format="%.1f"),
                "CO₂ reduction (%)": st.column_config.NumberColumn(format="%.1f%%"),
                "Cumulative profit (£)": st.column_config.NumberColumn(format="£%,.0f"),
                "Gross outlay (£)": st.column_config.NumberColumn(format="£%,.0f"),
                **{ACTION_LABELS[n]: st.column_config.NumberColumn(format="%.1f%%") for n in ACTION_NAMES},
            },
        )
        st.caption("Action percentages show how much of the remaining opportunity each plan implements.")

    ids = table["strategy_id"].tolist()
    if state.selected_strategy_id in ids:
        st.session_state["co_widget_select"] = state.selected_strategy_id

    def on_select() -> None:
        state.select_strategy(st.session_state["co_widget_select"])

    st.selectbox("Selected strategy", ids, key="co_widget_select", on_change=on_select,
                 format_func=lambda sid: _strategy_label(sid, analysis))
    rec = analysis.recommendation
    st.caption("★ " + recommendation_text(rec))


def strategy_kpis(result: SimulationResult, *, title: str, services: Services, request: AnalysisRequest) -> None:
    m = result.metrics
    st.markdown(f"**{title}**")
    kpi_row([
        {"label": "Horizon emissions", "value": tonnes(m["total_co2e_tco2e"]),
         "delta": tonnes(-m["co2_reduction_tco2e"], signed=True), "delta_color": "inverse",
         "delta_description": "vs baseline"},
        {"label": "CO₂ reduction", "value": pct(m["co2_reduction_ratio"]),
         "help": "Strategy horizon emissions vs baseline horizon emissions."},
        {"label": "Cumulative operating profit", "value": gbp(m["total_profit_gbp"]),
         "delta": gbp(m["profit_change_gbp"], signed=True), "delta_description": "vs baseline"},
        {"label": "Gross outlay (budget use)", "value": gbp(m["total_cost_gbp"]),
         "help": "Capex + incremental opex over the horizon; savings are excluded (counted against the budget)."},
        {"label": "Net cash impact", "value": gbp(m["net_cash_impact_gbp"], signed=True),
         "help": "Savings − incremental opex − capex over the horizon."},
    ])


def selected_strategy_panel(state: DashboardState, services: Services, request: AnalysisRequest) -> None:
    selected = state.selected_strategy()
    if selected is None:
        return
    st.subheader("Selected strategy")
    st.caption("Review this plan's emissions, profit and implementation cost against the baseline.")
    strategy_kpis(selected, title=_strategy_name(selected.strategy_id, state.analysis), services=services, request=request)
    cfg = selected.config
    st.caption("Actions (% of remaining opportunity): " + " · ".join(
        f"{ACTION_LABELS[n]} {pct(getattr(cfg, n))}" for n in ACTION_NAMES))


# --------------------------------------------------------------------------- #
# Manual what-if
# --------------------------------------------------------------------------- #


def whatif_panel(state: DashboardState, services: Services, request: AnalysisRequest) -> None:
    baseline = state.baseline
    st.subheader("Manual what-if")
    if baseline is None:
        st.info("What-if needs a baseline forecast.", icon="ℹ️")
        return
    st.caption(
        "Explore an action mix and compare its results with your goals. Each slider is the fraction of the remaining "
        "opportunity implemented from the first month (0 = no change; 1 = full implementation)."
    )
    b1, b2 = st.columns(2)
    selected = state.selected_strategy()
    b1.button("Load selected strategy", disabled=selected is None, width="stretch",
              on_click=lambda: state.load_whatif(state.selected_strategy().config))
    b2.button("Reset to no action", width="stretch", on_click=lambda: state.load_whatif(type(state.whatif_config).noop()))

    cols = st.columns(3)
    for i, name in enumerate(ACTION_NAMES):
        with cols[i % 3]:
            key = slider_key(name)
            st.slider(
                ACTION_LABELS[name], min_value=0.0, max_value=1.0, step=0.01, key=key, format="%.2f",
                help=ACTION_HELP[name],
                on_change=lambda n=name, k=key: state.set_whatif_action(n, st.session_state[k]),
            )
            share = resulting_share(baseline, name, getattr(state.whatif_config, name), services.assumptions)
            if share is not None:
                label = "Renewable share" if name == "renewable_energy" else "EV fleet share"
                st.caption(f"{label}: {share.describe()} (baseline → resulting)")

    result = state.ensure_whatif(services)
    if state.whatif_error:
        e = state.whatif_error
        error_box(e.kind, e.error_type, e.message)
        return
    if result is None:
        return
    strategy_kpis(result, title="What-if result", services=services, request=request)
    check = state.whatif_constraint_check(services, request)
    if check is not None:
        if check.feasible:
            st.success("Meets the current budget, profit floor and CO₂ target.", icon="✅")
        else:
            failed = constraint_failures(check)
            st.warning("Does not meet: " + ", ".join(failed or ["constraint tolerance"]) + ".", icon="⚠️")
    if selected is not None and result.strategy_id == selected.strategy_id:
        same = all(result.metrics[k] == selected.metrics[k] for k in selected.metrics)
        if same:
            st.caption("Matches the selected plan.")
        else:
            logger.error("What-if differs from stored strategy %s", selected.strategy_id)
            st.warning("The preview could not reproduce the selected plan. Please rerun the analysis.")


def monthly_panel(state: DashboardState, dark: bool) -> None:
    baseline = state.baseline
    if baseline is None:
        return
    scenarios: dict[str, SimulationResult] = {}
    if state.selected_strategy() is not None:
        scenarios["selected"] = state.selected_strategy()
    if state.whatif_result is not None:
        scenarios["whatif"] = state.whatif_result
    st.subheader("Monthly baseline vs scenarios")
    st.caption(f"Forecast horizon {period_label(baseline.monthly['timestamp'])}. Profit includes depreciation; "
               "capex is a month-1 cash outlay and is not deducted from operating profit.")
    st.plotly_chart(charts.monthly_comparison(baseline, scenarios, dark=dark), width="stretch")
    st.plotly_chart(charts.scope_totals(baseline, scenarios, dark=dark), width="stretch")


# --------------------------------------------------------------------------- #
# P1 optional capabilities
# --------------------------------------------------------------------------- #


def optional_panels(state: DashboardState, services: Services, request: AnalysisRequest, dark: bool) -> None:
    st.subheader("Decision confidence")
    st.caption("Assess uncertainty, compare with peers and explore how risk preferences affect the recommendation.")
    caps = services.capabilities
    analysis = state.analysis
    labels = ["Uncertainty", "Peer comparison", "Risk preferences"]
    if caps.shap_available_targets:
        labels.append("Forecast explanation")
    tabs = dict(zip(labels, st.tabs(labels)))

    with tabs["Uncertainty"]:
        if not caps.risk_available:
            st.info("Uncertainty analysis is currently unavailable.", icon="ℹ️")
        elif not request.risk_enabled:
            st.caption("Enable **Assess uncertainty** in the sidebar and optimize to evaluate a representative set of frontier plans.")
        elif analysis is None:
            st.caption("Optimize to evaluate risk.")
        else:
            sid = state.selected_strategy_id
            risk = analysis.risk_results.get(sid) if sid else None
            st.caption(f"Uncertainty assessed for {len(analysis.risk_results)} frontier plans. "
                       "Trials vary action assumptions while keeping the baseline forecast fixed.")
            if risk is None:
                st.info("No risk result for the selected strategy.", icon="ℹ️")
            else:
                s = risk.summary
                st.markdown(f"**{risk.n_simulations:,} uncertainty trials** for the selected plan")
                kpi_row([
                    {"label": "Chance of meeting CO₂ target", "value": pct(s["target_probability"]),
                     "help": f"Sampling standard error: {pct(s['target_probability_mc_standard_error'])}. "
                             "A finite-trial estimate, not a guarantee."},
                    {"label": "Chance of meeting profit floor", "value": pct(s["profit_floor_probability"])},
                    {"label": "Chance of staying within budget", "value": pct(s["budget_probability"])},
                    {"label": "Chance of meeting all goals", "value": pct(s["joint_feasibility_probability"])},
                ])
                st.plotly_chart(charts.risk_intervals(risk, state.selected_strategy(), dark=dark), width="stretch")
                st.caption("Intervals are empirical p05–p95 trial outcomes (90% of trials), not confidence intervals.")

    if "Forecast explanation" in tabs:
        with tabs["Forecast explanation"]:
            if analysis is None or analysis.explanation is None:
                st.caption("Enable **Explain the forecast** in the sidebar and optimize to view forecast drivers.")
            else:
                exp = analysis.explanation
                st.caption("Shows which inputs influence the forecast. These contributions do not measure the effects of actions or explain plan selection.")
                targets = sorted(set(exp.contributions["target"]))
                for tab, target in zip(st.tabs([charts.TARGET_LABELS.get(t, t) for t in targets]), targets):
                    with tab:
                        st.plotly_chart(charts.shap_contributions(exp, target, dark=dark), width="stretch")

    with tabs["Peer comparison"]:
        if not caps.benchmark_available:
            st.info("Peer comparison is currently unavailable.", icon="ℹ️")
        elif analysis is None or analysis.benchmark is None:
            st.caption("Enable **Compare with peers** in the sidebar and optimize to see the comparison.")
        else:
            b = analysis.benchmark
            if b.status != "ok":
                logger.info("Benchmark unavailable: %s", b.reason)
                st.info("A comparable peer group could not be found for this company.", icon="ℹ️")
            else:
                st.markdown(
                    f"Estimated intensity percentile: **{b.percentile:.0f}** (lower is better) — lower intensity than "
                    f"about **{b.better_than_pct:.0f}%** of this peer set (ties use midpoint rank)."
                )
                st.plotly_chart(charts.benchmark_position(b, dark=dark), width="stretch")
                st.caption(
                    f"{b.peer_count} peers · {'synthetic' if b.is_synthetic else 'reported'} peer data · "
                    f"forecast period {b.period_start} – {b.period_end}. "
                    f"Coverage: {b.scope_coverage.replace('_', ' ')}; scope 2: {b.scope2_method.replace('_', ' ')}. "
                    "Company forecasts are compared with historical peer results."
                )

    with tabs["Risk preferences"]:
        scenario_panel(state, services, request)


def scenario_panel(state: DashboardState, services: Services, request: AnalysisRequest) -> None:
    """Conservative / balanced / aggressive selections from WS2's policy on one analysis."""
    if not services.capabilities.scenario_compare_available:
        st.info("Risk preference comparison is currently unavailable.", icon="ℹ️")
        return
    analysis = state.analysis
    if analysis is None or not request.risk_enabled:
        st.caption("Enable **Assess uncertainty** and optimize to compare conservative, balanced and aggressive approaches.")
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
        row: dict[str, Any] = {"Approach": tol.capitalize(), "Plan": _strategy_name(rec.strategy_id, analysis),
                               "Uncertainty assessment": rec.risk_status.replace('_', ' ').capitalize()}
        if rec.strategy_id is not None:
            sim = opt.strategies[rec.strategy_id]
            m = sim.metrics
            risk = analysis.risk_results.get(rec.strategy_id)
            row.update({
                "Emissions (tCO₂e)": m["total_co2e_tco2e"], "CO₂ reduction (%)": (m["co2_reduction_ratio"] or 0) * 100,
                "Cumulative profit (£)": m["total_profit_gbp"], "Gross outlay (£)": m["total_cost_gbp"],
                "Chance of CO₂ target": None if risk is None else risk.summary["target_probability"] * 100,
                "Chance of all goals": None if risk is None else risk.summary["joint_feasibility_probability"] * 100,
                **{ACTION_LABELS[n]: getattr(sim.config, n) * 100 for n in ACTION_NAMES},
            })
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "Emissions (tCO₂e)": st.column_config.NumberColumn(format="%.1f"),
        "CO₂ reduction (%)": st.column_config.NumberColumn(format="%.1f%%"),
        "Cumulative profit (£)": st.column_config.NumberColumn(format="£%,.0f"),
        "Gross outlay (£)": st.column_config.NumberColumn(format="£%,.0f"),
        "Chance of CO₂ target": st.column_config.NumberColumn(format="%.1f%%"),
        "Chance of all goals": st.column_config.NumberColumn(format="%.1f%%"),
        **{ACTION_LABELS[n]: st.column_config.NumberColumn(format="%.1f%%") for n in ACTION_NAMES},
    })
    picked = {rec.strategy_id for rec in result.values()}
    pool = len(analysis.risk_results)
    st.caption(
        f"All approaches use the same forecast, goals and assessed plans ({pool} plans, "
        f"{next(iter(analysis.risk_results.values())).n_simulations if pool else 0:,} trials each). "
        + ("All three tolerances pick the same plan for these inputs. " if len(picked) == 1 else "")
        + "Each approach reflects a different risk preference. Probabilities are estimates under illustrative uncertainty."
    )
    for tol, rec in result.items():
        if rec.reason:
            st.caption(recommendation_text(rec))


# --------------------------------------------------------------------------- #
# Assumptions and provenance
# --------------------------------------------------------------------------- #


def assumptions_panel(assumptions: ActionAssumptions) -> None:
    st.subheader("Assumptions")
    calibrated = "calibrated" if assumptions.is_calibrated else "**illustrative, not calibrated** company economics"
    st.caption(f"Plans use {calibrated}. Review the assumptions before applying a plan.")
    st.markdown(
        "- Action values are fractions of the **remaining** eligible opportunity, implemented in month 1.\n"
        "- Budget = horizon gross outlay (capex + incremental opex); savings do not offset it.\n"
        "- Profit floor = cumulative operating profit over the horizon; capex affects profit only via depreciation.\n"
        "- CO₂ target compares strategy horizon emissions with baseline horizon emissions.\n"
        "- Intervention effects come from these versioned assumptions, not from the forecast model."
    )
    with st.expander("Action assumptions and costs"):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Emission partitions and effectiveness**")
            rows = [(f.replace("ice_fleet", "combustion fleet").replace("ev_", "electric vehicle ").replace("_", " ").capitalize(),
                     getattr(assumptions, f) * 100) for f in (
                "gas_share", "ice_fleet_share", "travel_share", "cloud_share", "supplier_share", "other_share",
                "building_electricity_share", "building_gas_share", "building_max_reduction", "cloud_max_reduction",
                "supplier_max_reduction", "renewable_effectiveness", "ev_effectiveness", "travel_effectiveness")]
            st.dataframe(pd.DataFrame(rows, columns=["Assumption", "Share (%)"]), hide_index=True, width="stretch",
                         column_config={"Share (%)": st.column_config.NumberColumn(format="%.1f%%")})
        with c2:
            st.markdown("**Costs at full implementation**")
            costs = pd.DataFrame([
                {"Action": ACTION_LABELS[n], "Capex (£)": c.capex_at_full_gbp, "Monthly opex (£)": c.monthly_opex_at_full_gbp,
                 "Asset life (months)": c.asset_life_months}
                for n, c in ((n, assumptions.costs[n]) for n in ACTION_NAMES)
            ])
            st.dataframe(costs, hide_index=True, width="stretch", column_config={
                "Capex (£)": st.column_config.NumberColumn(format="£%,.0f"),
                "Monthly opex (£)": st.column_config.NumberColumn(format="£%,.0f"),
            })
            st.markdown("**Prices and factors**")
            price_labels = {
                "electricity_gbp_per_kwh": "Electricity (£/kWh)", "gas_gbp_per_kwh": "Gas (£/kWh)",
                "renewable_premium_gbp_per_kwh": "Renewable electricity premium (£/kWh)",
                "ice_fuel_gbp_per_km": "Combustion fleet fuel (£/km)", "travel_gbp_per_km": "Business travel (£/km)",
                "cloud_gbp_per_hour": "Cloud computing (£/hour)",
                "supplier_monthly_savings_at_full_gbp": "Supplier savings at full implementation (£/month)",
                "ev_kwh_per_km": "Electric vehicle energy (kWh/km)", "grid_tco2e_per_kwh": "Grid emissions (tCO₂e/kWh)",
            }
            prices = [(label, getattr(assumptions, field)) for field, label in price_labels.items()]
            st.dataframe(pd.DataFrame(prices, columns=["Price or factor", "Value"]), hide_index=True, width="stretch",
                         column_config={"Value": st.column_config.NumberColumn(format="%.4g")})


def analysis_download(state: DashboardState) -> None:
    with st.expander("Export analysis"):
        analysis = state.analysis
        if analysis is not None:
            try:
                payload = to_json(analysis, indent=2)
            except CarbonOptError:
                logger.exception("Analysis serialization failed")
                st.info("The download could not be prepared. Please try again.")
            else:
                st.download_button("Download analysis (JSON)", payload, file_name="carbonopt-analysis.json",
                                   mime="application/json")
        else:
            st.caption("Optimize a plan to download its results and assumptions.")
