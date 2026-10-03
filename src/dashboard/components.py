"""Streamlit rendering components. All reads come from DashboardState and
public contract objects; all writes go through DashboardState."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from src.contracts.errors import CarbonOptError
from src.contracts.serialization import to_json
from src.contracts.types import ACTION_NAMES, ActionAssumptions, AnalysisRequest, SimulationResult
from src.integration.services import Services

from . import charts, eda, trainer
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
    if kind == VALIDATION_ERROR:
        st.error(f"**Input not valid** ({error_type}): {message}", icon="🚫")
    else:
        st.error(f"**Provider error** ({error_type}): {message}. Nothing was replaced with mock output; adjust "
                 "the inputs or provider configuration and retry.", icon="🛑")


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
    st.subheader("Exploratory Data Analysis and Model Selection")
    eda.feature_explorer()
    trainer.model_trainer()
    baseline = state.baseline
    if baseline is None:
        if state.baseline_error:
            e = state.baseline_error
            error_box(e.kind, e.error_type, e.message)
        return
    history = state.history
    st.markdown("#### Baseline forecast")
    st.caption(
        f"Company `{baseline.company_id}` · data kind **{baseline.data_kind}** · scope 2 method "
        f"`{baseline.scope2_method}` · model `{baseline.model_id}` · driver policy `{baseline.driver_policy_id}` · "
        f"provider `{baseline.provenance.provider}`"
    )
    tiles: list[dict[str, Any]] = []
    if history is not None and len(history):
        trailing = trailing_window(history, 12)
        window = period_label(trailing["timestamp"])
        tiles += [
            {"label": "Emissions, trailing 12 months (history)", "value": tonnes(float(trailing["total_co2e_tco2e"].sum())),
             "help": f"Historical {window}."},
            {"label": "Operating profit, trailing 12 months (history)", "value": gbp(float(trailing["operating_profit_gbp"].sum())),
             "help": f"Historical {window}."},
        ]
    horizon = period_label(baseline.monthly["timestamp"])
    tiles += [
        {"label": "Baseline forecast emissions", "value": tonnes(baseline.totals["total_co2e_tco2e"]),
         "help": f"Business-as-usual forecast, {horizon}."},
        {"label": "Baseline forecast operating profit", "value": gbp(baseline.totals["operating_profit_gbp"]),
         "help": f"Cumulative over {horizon}."},
    ]
    kpi_row(tiles)
    st.caption(
        f"History: {period_label(history['timestamp']) if history is not None and len(history) else 'not provided'} · "
        f"Forecast horizon: {period_label(baseline.monthly['timestamp'])}. Both 12-month totals above are labelled "
        "periods; the history window is observed and the forecast window is projected."
    )
    tab_e, tab_p = st.tabs(["Emissions", "Operating profit"])
    with tab_e:
        st.plotly_chart(charts.history_and_baseline(history, baseline, "total_co2e_tco2e", dark=dark), width="stretch")
    with tab_p:
        st.plotly_chart(charts.history_and_baseline(history, baseline, "operating_profit_gbp", dark=dark), width="stretch")


def backtest_panel(state: DashboardState, dark: bool) -> None:
    report = state.backtest
    st.subheader("Forecast evaluation (temporal backtest)")
    if report is None:
        st.info("The forecast provider did not publish a backtest report.", icon="ℹ️")
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
    st.caption(f"Pooled out-of-fold metrics over {n_folds} expanding-window forecast origins{horizons}; units follow "
               f"each target (tCO₂e or GBP per month). Model family `{report.model_family}`, feature spec "
               f"`{report.feature_spec_id}`." + (" The chart shows the 1-month-ahead path." if horizons else ""))
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
    return f"{star}{sid} · {tonnes(row['total_co2e_tco2e'])} · {gbp(row['total_profit_gbp'])}"


def optimization_panel(state: DashboardState, services: Services, request: AnalysisRequest, dark: bool) -> None:
    analysis = state.analysis
    st.subheader("Optimized strategies")
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
    st.caption(
        f"Evaluated {diag.get('evaluated_count', '?')} candidates ({diag.get('unique_count', '?')} unique) · seed "
        f"{diag.get('seed', '?')} · termination `{diag.get('termination_reason', '?')}` · provider "
        f"`{opt.provenance.provider}`"
    )
    if diag.get("warning"):
        st.caption(f"Provider note: {diag['warning']}")
    for warning in analysis.warnings:
        st.caption(f"⚠️ {warning}")

    if status == INFEASIBLE:
        st.error(
            "**No feasible recommendation found.** No evaluated strategy met all three constraints within the "
            "search budget (this is not a proof that none exists). Relax the budget, profit floor or CO₂ target "
            "and optimize again.", icon="🚫",
        )
        mv = diag.get("minimum_normalized_violations", {})
        if mv:
            st.caption("Smallest normalized violation among evaluated candidates — "
                       + ", ".join(f"{k}: {v:.3g}" for k, v in mv.items()))
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
    st.caption("Click a frontier point, a table row, or use the selector to choose a strategy. Feasibility and "
               "Pareto ranks come from the optimizer provider; the chart only plots them.")

    table = opt.pareto.sort_values(["total_co2e_tco2e", "strategy_id"]).reset_index(drop=True)
    st.session_state["co_table_ids"] = table["strategy_id"].tolist()
    display = pd.DataFrame({
        "": ["★" if sid == analysis.recommendation.strategy_id else "" for sid in table["strategy_id"]],
        "Strategy ID": table["strategy_id"],
        "Emissions (tCO₂e)": table["total_co2e_tco2e"],
        "CO₂ reduction (%)": table["co2_reduction_ratio"] * 100.0,
        "Cumulative profit (£)": table["total_profit_gbp"],
        "Gross outlay (£)": table["total_cost_gbp"],
        **{ACTION_LABELS[n]: table[n] for n in ACTION_NAMES},
    })
    st.dataframe(
        display, hide_index=True, width="stretch", key="co_widget_table", on_select="rerun", selection_mode="single-row",
        column_config={
            "Emissions (tCO₂e)": st.column_config.NumberColumn(format="%.1f"),
            "CO₂ reduction (%)": st.column_config.NumberColumn(format="%.1f%%"),
            "Cumulative profit (£)": st.column_config.NumberColumn(format="£%,.0f"),
            "Gross outlay (£)": st.column_config.NumberColumn(format="£%,.0f"),
            **{ACTION_LABELS[n]: st.column_config.NumberColumn(format="%.2f") for n in ACTION_NAMES},
        },
    )
    st.caption("Action columns are fractions of remaining opportunity, rounded for display only; selection uses the "
               "strategy ID and the exact stored configuration.")

    ids = table["strategy_id"].tolist()
    if state.selected_strategy_id in ids:
        st.session_state["co_widget_select"] = state.selected_strategy_id

    def on_select() -> None:
        state.select_strategy(st.session_state["co_widget_select"])

    st.selectbox("Selected strategy", ids, key="co_widget_select", on_change=on_select,
                 format_func=lambda sid: _strategy_label(sid, analysis))
    rec = analysis.recommendation
    st.caption(f"★ Recommended by policy `{rec.policy}` (tolerance {rec.tolerance}, risk status `{rec.risk_status}`). "
               f"{rec.reason or ''}")


def strategy_kpis(result: SimulationResult, *, title: str, services: Services, request: AnalysisRequest) -> None:
    m = result.metrics
    st.markdown(f"**{title}**" + f" · `{result.strategy_id}`")
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
    strategy_kpis(selected, title="Selected strategy (stored optimizer result)", services=services, request=request)
    cfg = selected.config
    st.caption("Actions (fraction of remaining opportunity): " + " · ".join(
        f"{ACTION_LABELS[n]} {getattr(cfg, n):.3f}" for n in ACTION_NAMES))


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
        "Each slider is the **fraction of the remaining opportunity** implemented at month 1 and held for the horizon "
        "(0 = no change). Moving a slider calls the simulator directly; it does not retrain or re-optimize. "
        f"Simulator: `{services.providers['simulator'].name}`."
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
            st.success("Meets the current budget, profit floor and CO₂ target (shared constraint evaluation).", icon="✅")
        else:
            failed = constraint_failures(check)
            st.warning("Does not meet: " + ", ".join(failed or ["constraint tolerance"]) + ".", icon="⚠️")
    if selected is not None and result.strategy_id == selected.strategy_id:
        same = all(result.metrics[k] == selected.metrics[k] for k in selected.metrics)
        st.caption("✔ Identical to the stored optimizer result for the selected strategy." if same else
                   "✖ Differs from the stored optimizer result for the same strategy ID — report to WS2.")


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
    st.subheader("Risk, forecast explanation, benchmark and scenarios")
    caps = services.capabilities
    analysis = state.analysis
    tabs = st.tabs(["Risk", "Forecast SHAP", "Benchmark", "Scenario comparison"])

    with tabs[0]:
        if not caps.risk_available:
            st.info(f"Risk is unavailable: {services.unavailable.get('risk', 'no provider')}.", icon="⛔")
        elif not request.risk_enabled:
            st.caption("Enable **Risk** in the sidebar and optimize to evaluate the frontier risk pool.")
        elif analysis is None:
            st.caption("Optimize to evaluate risk.")
        else:
            sid = state.selected_strategy_id
            risk = analysis.risk_results.get(sid) if sid else None
            st.caption(f"Risk results available for {len(analysis.risk_results)} pool strategies. Risk is "
                       "assumption-based action uncertainty conditional on the baseline forecast.")
            if risk is None:
                st.info("No risk result for the selected strategy.", icon="ℹ️")
            else:
                s = risk.summary
                st.markdown(f"**{risk.n_simulations:,} trials** · uncertainty `{risk.uncertainty_id}` · seed "
                            f"{risk.provenance.seed}")
                kpi_row([
                    {"label": "P(target met)", "value": pct(s["target_probability"]),
                     "help": f"MC standard error {s['target_probability_mc_standard_error']:.4f}. "
                             "A finite-trial estimate, not a guarantee."},
                    {"label": "P(profit floor met)", "value": pct(s["profit_floor_probability"])},
                    {"label": "P(within budget)", "value": pct(s["budget_probability"])},
                    {"label": "P(all constraints)", "value": pct(s["joint_feasibility_probability"])},
                ])
                st.plotly_chart(charts.risk_intervals(risk, state.selected_strategy(), dark=dark), width="stretch")
                st.caption("Intervals are empirical p05–p95 trial outcomes (90% of trials), not confidence intervals.")

    with tabs[1]:
        if not caps.shap_available_targets:
            st.info(f"SHAP is unavailable: {services.unavailable.get('shap', 'no provider')}.", icon="⛔")
        elif analysis is None or analysis.explanation is None:
            st.caption("Enable **SHAP** in the sidebar and optimize to load forecast explanations.")
        else:
            exp = analysis.explanation
            st.caption("Explains the forecast model's raw output (not causal action effects, nor why the optimizer "
                       "chose a strategy).")
            targets = sorted(set(exp.contributions["target"]))
            for tab, target in zip(st.tabs([charts.TARGET_LABELS.get(t, t) for t in targets]), targets):
                with tab:
                    st.plotly_chart(charts.shap_contributions(exp, target, dark=dark), width="stretch")

    with tabs[2]:
        if not caps.benchmark_available:
            st.info(f"Benchmark is unavailable: {services.unavailable.get('benchmark', 'no provider')}.", icon="⛔")
        elif analysis is None or analysis.benchmark is None:
            st.caption("Enable **Benchmark** in the sidebar and optimize to compare against peers.")
        else:
            b = analysis.benchmark
            if b.status != "ok":
                st.info(f"Benchmark unavailable: {b.reason}", icon="ℹ️")
            else:
                st.markdown(
                    f"Estimated intensity percentile: **{b.percentile:.0f}** (lower is better) — lower intensity than "
                    f"about **{b.better_than_pct:.0f}%** of this peer set (ties use midpoint rank)."
                )
                st.plotly_chart(charts.benchmark_position(b, dark=dark), width="stretch")
                st.caption(
                    f"{b.peer_count} peers · source `{b.source_id}` ({'synthetic' if b.is_synthetic else 'reported'}) · "
                    f"forecast period compared {b.period_start} – {b.period_end} · coverage `{b.scope_coverage}` · scope 2 "
                    f"`{b.scope2_method}` · basis `{b.comparison_basis}` (forecast compared with historical peers)."
                )

    with tabs[3]:
        scenario_panel(state, services, request)


def scenario_panel(state: DashboardState, services: Services, request: AnalysisRequest) -> None:
    """Conservative / balanced / aggressive selections from WS2's policy on one analysis."""
    if not services.capabilities.scenario_compare_available:
        st.info(f"Scenario comparison is unavailable: {services.unavailable.get('scenario_compare', '')}.", icon="⛔")
        return
    analysis = state.analysis
    if analysis is None or not request.risk_enabled:
        st.caption("Enable **Risk** in the sidebar and optimize: all three policies rank the same evaluated risk pool.")
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
        row: dict[str, Any] = {"Tolerance": tol, "Strategy ID": rec.strategy_id or "none", "Risk status": rec.risk_status}
        if rec.strategy_id is not None:
            sim = opt.strategies[rec.strategy_id]
            m = sim.metrics
            risk = analysis.risk_results.get(rec.strategy_id)
            row.update({
                "Emissions (tCO₂e)": m["total_co2e_tco2e"], "CO₂ reduction (%)": (m["co2_reduction_ratio"] or 0) * 100,
                "Cumulative profit (£)": m["total_profit_gbp"], "Gross outlay (£)": m["total_cost_gbp"],
                "P(target)": None if risk is None else risk.summary["target_probability"] * 100,
                "P(all constraints)": None if risk is None else risk.summary["joint_feasibility_probability"] * 100,
                **{ACTION_LABELS[n]: getattr(sim.config, n) for n in ACTION_NAMES},
            })
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "Emissions (tCO₂e)": st.column_config.NumberColumn(format="%.1f"),
        "CO₂ reduction (%)": st.column_config.NumberColumn(format="%.1f%%"),
        "Cumulative profit (£)": st.column_config.NumberColumn(format="£%,.0f"),
        "Gross outlay (£)": st.column_config.NumberColumn(format="£%,.0f"),
        "P(target)": st.column_config.NumberColumn(format="%.1f%%"),
        "P(all constraints)": st.column_config.NumberColumn(format="%.1f%%"),
        **{ACTION_LABELS[n]: st.column_config.NumberColumn(format="%.3f") for n in ACTION_NAMES},
    })
    picked = {rec.strategy_id for rec in result.values()}
    pool = len(analysis.risk_results)
    st.caption(
        f"Same baseline, constraints, optimization run and risk pool ({pool} strategies, "
        f"{next(iter(analysis.risk_results.values())).n_simulations if pool else 0:,} trials each) for every policy; "
        "selection is WS2's recommendation policy. "
        + ("All three tolerances pick the same plan for these inputs. " if len(picked) == 1 else "")
        + "Policies are compared, not ranked: no tolerance dominates another. Probabilities are finite-trial "
        "estimates under illustrative uncertainty."
    )
    for tol, rec in result.items():
        if rec.reason:
            st.caption(f"**{tol}**: {rec.reason}")


# --------------------------------------------------------------------------- #
# Assumptions and provenance
# --------------------------------------------------------------------------- #


def assumptions_panel(assumptions: ActionAssumptions, is_mock: bool) -> None:
    st.subheader("Assumptions")
    calibrated = "calibrated" if assumptions.is_calibrated else "**illustrative, not calibrated** company economics"
    st.markdown(f"Action assumptions `{assumptions.assumptions_id}` v{assumptions.version} — {calibrated}. "
                f"{assumptions.description}")
    st.markdown(
        "- Action values are fractions of the **remaining** eligible opportunity, implemented in month 1.\n"
        "- Budget = horizon gross outlay (capex + incremental opex); savings do not offset it.\n"
        "- Profit floor = cumulative operating profit over the horizon; capex affects profit only via depreciation.\n"
        "- CO₂ target compares strategy horizon emissions with baseline horizon emissions.\n"
        "- Intervention effects come from these versioned assumptions, not from the forecast model."
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Emission partitions and effectiveness**")
        rows = [(f, getattr(assumptions, f)) for f in (
            "gas_share", "ice_fleet_share", "travel_share", "cloud_share", "supplier_share", "other_share",
            "building_electricity_share", "building_gas_share", "building_max_reduction", "cloud_max_reduction",
            "supplier_max_reduction", "renewable_effectiveness", "ev_effectiveness", "travel_effectiveness")]
        st.dataframe(pd.DataFrame(rows, columns=["Parameter (ratio 0–1)", "Value"]), hide_index=True, width="stretch")
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
        prices = [(f, getattr(assumptions, f)) for f in (
            "electricity_gbp_per_kwh", "gas_gbp_per_kwh", "renewable_premium_gbp_per_kwh", "ice_fuel_gbp_per_km",
            "travel_gbp_per_km", "cloud_gbp_per_hour", "supplier_monthly_savings_at_full_gbp", "ev_kwh_per_km",
            "grid_tco2e_per_kwh")]
        st.dataframe(pd.DataFrame(prices, columns=["Parameter (unit in name)", "Value"]), hide_index=True, width="stretch")


def provenance_details(state: DashboardState, services: Services) -> None:
    with st.expander("Provenance and run details"):
        st.dataframe(pd.DataFrame([
            {"Slot": slot, "Provider": info.name, "Kind": info.kind, "Version": info.version, "Mock": info.is_mock}
            for slot, info in services.providers.items()
        ]), hide_index=True, width="stretch")
        if services.unavailable:
            st.markdown("**Unavailable capabilities**")
            for slot, reason in services.unavailable.items():
                st.caption(f"{slot}: {reason}")
        analysis = state.analysis
        if analysis is not None:
            p = analysis.provenance
            st.caption(f"Run `{analysis.run_id}` · input hash `{p.input_hash[:16]}…` · seed {p.seed} · "
                       f"assumptions `{p.assumptions_id}` · is_mock {p.is_mock}")
            try:
                payload = to_json(analysis, indent=2)
            except CarbonOptError as exc:
                st.caption(f"Bundle serialization failed: {exc}")
            else:
                st.download_button("Download analysis bundle (JSON)", payload, file_name=f"{analysis.run_id}.json",
                                   mime="application/json")
