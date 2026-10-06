"""Plotly figure builders. Inputs are public contract objects/frames only.

Presentation transformations only: unit labels, ratio->percent, sign for display, ID
joins. No emissions, accounting, feasibility, Pareto or risk logic lives here.

Entity colours are fixed across charts: baseline = warm grey (also dashed), plans =
deep green, the user's own mix = burnt orange. Every chart has a single y-axis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.contracts.types import (
    BaselineBundle,
    BenchmarkResult,
    ExplanationResult,
    OptimizationResult,
    RiskResult,
    SimulationResult,
)

from .presentation import feature_label, model_name, shap_importance
from .theme import SANS, Palette, palette

TARGET_LABELS = {"total_co2e_tco2e": "Total emissions (tCO₂e)", "operating_profit_gbp": "Operating profit (GBP)"}


def _layout(fig: go.Figure, p: Palette, *, height: int, x_title: str | None = None, y_title: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=4, r=4, t=36, b=4),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=SANS, color=p.text_secondary, size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(color=p.text_secondary)),
        hoverlabel=dict(font=dict(family=SANS)),
        hovermode="x unified",
    )
    axis = dict(gridcolor=p.grid, linecolor=p.axis, zerolinecolor=p.axis, tickfont=dict(color=p.muted),
                title_font=dict(color=p.text_secondary, size=12))
    fig.update_xaxes(**axis, showline=True, showgrid=False)
    fig.update_yaxes(**axis, showline=False)
    if x_title:
        fig.update_xaxes(title_text=x_title)
    if y_title:
        fig.update_yaxes(title_text=y_title)
    return fig


def history_forecast(history: pd.DataFrame, baseline: BaselineBundle, column: str, *,
                     start: pd.Timestamp | None = None, end: pd.Timestamp | None = None, dark: bool = False) -> go.Figure:
    """Reported months from `start` to `end` (default: the last four years) running into the baseline
    forecast for one column; the forecast is drawn only when the window reaches the last reported month."""
    p = palette(dark)
    ordered = history.sort_values("timestamp")
    if start is None and end is None:
        recent = ordered.tail(48)
    else:
        ts = ordered["timestamp"]
        recent = ordered[(ts >= (start if start is not None else ts.iloc[0])) & (ts <= (end if end is not None else ts.iloc[-1]))]
    money = column.endswith("_gbp")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=recent["timestamp"], y=recent[column], name="Reported", mode="lines",
                             line=dict(color=p.text, width=1.6), hovertemplate="Reported %{y:,.0f}<extra></extra>"))
    if len(recent) and recent["timestamp"].iloc[-1] == ordered["timestamp"].iloc[-1]:
        joined = pd.concat([recent.tail(1), baseline.monthly])  # the forecast starts from the last reported month
        fig.add_trace(go.Scatter(x=joined["timestamp"], y=joined[column], name="Forecast", mode="lines",
                                 line=dict(color=p.baseline, width=2, dash="dash"),
                                 hovertemplate="Forecast %{y:,.0f}<extra></extra>"))
        fig.add_vline(x=baseline.monthly["timestamp"].iloc[0], line=dict(color=p.axis, width=1))
    _layout(fig, p, height=260)
    fig.update_layout(title=dict(text="Operating profit per month" if money else "Emissions per month (tCO₂e)",
                                 font=dict(size=13, color=p.text_secondary), x=0, xanchor="left", y=0.98),
                      legend=dict(y=1.0, x=1, xanchor="right"), margin=dict(t=44))
    fig.update_yaxes(tickprefix="£" if money else "", tickformat="~s")
    return fig


@dataclass(frozen=True)
class ParetoFigure:
    figure: go.Figure
    # (curve_number, point_index) -> strategy_id, for click selection
    point_ids: Mapping[tuple[int, int], str]


def pareto_scatter(
    optimization: OptimizationResult,
    baseline: BaselineBundle,
    *,
    selected_id: str | None,
    recommended_id: str | None,
    whatif: SimulationResult | None = None,
    dark: bool = False,
) -> ParetoFigure:
    """x = horizon emissions (tCO₂e, lower is better); y = cumulative operating profit (GBP)."""
    p = palette(dark)
    fig = go.Figure()
    ids: dict[tuple[int, int], str] = {}
    cand = optimization.candidates
    pareto = optimization.pareto.sort_values("total_co2e_tco2e")
    hover = "Emissions %{x:,.0f} tCO₂e<br>Profit £%{y:,.0f}<br>Outlay £%{customdata[1]:,.0f}<extra></extra>"

    def add(frame: pd.DataFrame, **kwargs: object) -> None:
        curve = len(fig.data)
        fig.add_trace(go.Scatter(
            x=frame["total_co2e_tco2e"], y=frame["total_profit_gbp"],
            customdata=frame[["strategy_id", "total_cost_gbp"]].to_numpy(), hovertemplate=hover, **kwargs,
        ))
        for i, sid in enumerate(frame["strategy_id"]):
            ids[(curve, i)] = sid

    infeasible = cand[~cand["feasible"]]
    dominated = cand[cand["feasible"] & (cand["pareto_rank"] != 0)]
    if len(infeasible):
        add(infeasible, name="Misses a goal", mode="markers", visible="legendonly" if len(pareto) else True,
            marker=dict(color=p.muted, size=5, opacity=0.35, symbol="x-thin", line=dict(width=1, color=p.muted)))
    if len(dominated):
        add(dominated, name="Meets goals, not best", mode="markers",
            marker=dict(color=p.muted, size=4, opacity=0.22, line=dict(width=0)))
    if len(pareto):
        add(pareto, name="Best trade-offs", mode="lines+markers",
            line=dict(color=p.plan, width=2), marker=dict(color=p.plan, size=9, line=dict(width=1.5, color=p.surface)))
    for sid, label, symbol in ((recommended_id, "Recommended", "star"), (selected_id, "Selected", "circle-open")):
        if sid and sid in set(pareto["strategy_id"]):
            add(pareto[pareto["strategy_id"] == sid], name=label, mode="markers",
                marker=dict(color=p.plan if symbol == "star" else p.text, size=17 if symbol == "star" else 21,
                            symbol=symbol, line=dict(width=1.5, color=p.surface if symbol == "star" else p.text)))
    base = baseline.totals
    fig.add_trace(go.Scatter(
        x=[base["total_co2e_tco2e"]], y=[base["operating_profit_gbp"]], name="No new actions", mode="markers",
        marker=dict(color=p.baseline, size=11, symbol="square", line=dict(width=1.5, color=p.surface)),
        hovertemplate="<b>No new actions</b><br>Emissions %{x:,.0f} tCO₂e<br>Profit £%{y:,.0f}<extra></extra>",
    ))
    if whatif is not None and any(whatif.config.as_vector()):  # an empty mix is the baseline square
        fig.add_trace(go.Scatter(
            x=[whatif.metrics["total_co2e_tco2e"]], y=[whatif.metrics["total_profit_gbp"]], name="Your mix",
            mode="markers", marker=dict(color=p.whatif, size=12, symbol="diamond", line=dict(width=1.5, color=p.surface)),
            hovertemplate="<b>Your mix</b><br>Emissions %{x:,.0f} tCO₂e<br>Profit £%{y:,.0f}<extra></extra>",
        ))
    _layout(fig, p, height=420, x_title="Emissions over the next 12 months (tCO₂e) — lower is better",
            y_title="Operating profit over the next 12 months")
    fig.update_layout(hovermode="closest", clickmode="event+select", dragmode="pan")
    fig.update_yaxes(tickprefix="£", tickformat="~s")
    fig.update_xaxes(tickformat=",.0f", showgrid=True)
    return ParetoFigure(figure=fig, point_ids=ids)


def scope_totals(baseline: BaselineBundle, scenarios: Mapping[str, SimulationResult], *, dark: bool = False) -> go.Figure:
    """Where the cut comes from: next-12-month emissions by scope (presentation sums only)."""
    p = palette(dark)
    scopes = [("scope3_tco2e", "Scope 3 · value chain"), ("scope2_tco2e", "Scope 2 · bought energy"),
              ("scope1_tco2e", "Scope 1 · own fuel")]
    styles = {"baseline": ("No new actions", p.baseline), "selected": ("Selected plan", p.plan), "whatif": ("Your mix", p.whatif)}
    series = {**{k: v.monthly for k, v in scenarios.items()}, "baseline": baseline.monthly}
    fig = go.Figure()
    for key, frame in series.items():
        name, color = styles[key]
        fig.add_trace(go.Bar(
            y=[label for _, label in scopes], x=[float(frame[c].sum()) for c, _ in scopes], name=name, orientation="h",
            marker=dict(color=color, line=dict(width=0)),
            hovertemplate=f"{name}<br>%{{y}}: %{{x:,.0f}} tCO₂e<extra></extra>",
        ))
    _layout(fig, p, height=230, x_title="tCO₂e over the next 12 months")
    fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.05, hovermode="closest", legend=dict(traceorder="reversed"))
    fig.update_xaxes(tickformat=",.0f", showgrid=True)
    return fig


def risk_intervals(risk: RiskResult, deterministic: SimulationResult | None, *, dark: bool = False) -> go.Figure:
    """Empirical p05–p95 trial interval (not a confidence interval on the mean)."""
    p = palette(dark)
    s = risk.summary
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Emissions (tCO₂e)", "Operating profit (£)"), horizontal_spacing=0.14)
    for col, (lo, mean, hi, metric) in enumerate((
        ("co2_p05_tco2e", "co2_mean_tco2e", "co2_p95_tco2e", "total_co2e_tco2e"),
        ("profit_p05_gbp", "profit_mean_gbp", "profit_p95_gbp", "total_profit_gbp"),
    ), start=1):
        fig.add_trace(go.Scatter(
            x=[s[mean]], y=["Trials"], mode="markers", name="Trial mean, 5th–95th percentile", showlegend=col == 1,
            marker=dict(color=p.plan, size=11),
            error_x=dict(type="data", symmetric=False, array=[s[hi] - s[mean]], arrayminus=[s[mean] - s[lo]],
                         color=p.plan, thickness=2, width=7),
            hovertemplate="p05 %{customdata[0]:,.0f} · mean %{x:,.0f} · p95 %{customdata[1]:,.0f}<extra></extra>",
            customdata=[[s[lo], s[hi]]],
        ), row=1, col=col)
        if deterministic is not None:
            fig.add_trace(go.Scatter(
                x=[deterministic.metrics[metric]], y=["Plan"], mode="markers", name="Plan as calculated",
                showlegend=col == 1, marker=dict(color=p.baseline, size=10, symbol="square"),
            ), row=1, col=col)
    _layout(fig, p, height=210)
    fig.update_layout(hovermode="closest")
    fig.update_annotations(font=dict(color=p.text_secondary, size=12))
    return fig


def shap_top_k(explanation: ExplanationResult, target: str, k: int, *, dark: bool = False) -> go.Figure:
    """The k inputs that move the forecast most, as their share of the movement (mean |SHAP|), coloured by
    whether they raise or lower it on average; the rest grouped into one bar. Presentation summaries only."""
    p = palette(dark)
    share = shap_importance(explanation, target)
    rows = explanation.contributions[explanation.contributions["target"] == target]
    push = rows.groupby("feature")["shap_value"].mean()
    top, rest = list(share.index[:k]), list(share.index[k:])
    labels = [feature_label(f) for f in reversed(top)]  # plotly draws the first bar at the bottom
    values = [100 * float(share[f]) for f in reversed(top)]
    colors = [p.plan if push[f] >= 0 else p.negative for f in reversed(top)]
    hover = ["raises the forecast" if push[f] >= 0 else "lowers the forecast" for f in reversed(top)]
    if rest:
        labels.insert(0, f"All other {len(rest)} inputs")
        values.insert(0, 100 * float(share[rest].sum()))
        colors.insert(0, p.baseline)
        hover.insert(0, "together")
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker=dict(color=colors), customdata=hover,
                           hovertemplate="%{y}: %{x:.0f}% of the movement, %{customdata}<extra></extra>"))
    _layout(fig, p, height=60 + 28 * len(labels), x_title="Share of the forecast's movement (%)")
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig


def benchmark_position(result: BenchmarkResult, *, dark: bool = False) -> go.Figure:
    p = palette(dark)
    fig = go.Figure(go.Bar(
        x=[result.industry_median, result.company_intensity_tco2e_per_million_gbp],
        y=["Peer median", "Your forecast"], orientation="h", marker=dict(color=[p.baseline, p.plan]),
        hovertemplate="%{y}: %{x:,.1f} tCO₂e per £m revenue<extra></extra>",
    ))
    _layout(fig, p, height=150, x_title="Emissions per £m revenue (tCO₂e) — lower is better")
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig


def model_errors(table: pd.DataFrame, *, dark: bool = False) -> go.Figure:
    """Held-out error (WAPE %) per model and target from `compare_models`; shorter is better."""
    p = palette(dark)
    fig = go.Figure()
    for target, name, color in (("emissions", "Emissions", p.plan), ("profit", "Operating profit", p.baseline)):
        rows = table[table["target"] == target]
        fig.add_trace(go.Bar(x=rows["wape"], y=[model_name(m) for m in rows["model"]], name=name, orientation="h",
                             marker=dict(color=color), hovertemplate=f"{name}<br>%{{y}}: %{{x:.1f}}% error<extra></extra>"))
    _layout(fig, p, height=80 + 44 * table["model"].nunique(), x_title="Average miss on the last 12 months (% of actual)")
    fig.update_layout(barmode="group", hovermode="closest")
    fig.update_yaxes(autorange="reversed")
    return fig


def grid_intensity(times: pd.Series, intensity: pd.Series, best: tuple[pd.Timestamp, pd.Timestamp] | None, *,
                   dark: bool = False) -> go.Figure:
    """GB grid carbon intensity per half-hour, with the cleanest hour shaded."""
    p = palette(dark)
    fig = go.Figure(go.Scatter(x=times, y=intensity, mode="lines", line=dict(color=p.text, width=1.6, shape="hv"),
                               name="Forecast", hovertemplate="%{x|%d %b %H:%M}: %{y:,.0f} g CO₂/kWh<extra></extra>"))
    if best is not None:
        fig.add_vrect(x0=best[0], x1=best[1], fillcolor=p.plan, opacity=0.25, line_width=0)
    _layout(fig, p, height=220, y_title="g CO₂ per kWh")
    fig.update_layout(showlegend=False, margin=dict(t=12))
    return fig
