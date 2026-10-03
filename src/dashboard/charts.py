"""Plotly figure builders. Inputs are public contract objects/frames only.

Presentation transformations only: unit labels, ratio->percent, sign for
display, ID joins. No emissions, accounting, feasibility, Pareto or risk logic
lives here, so swapping mock for real providers needs no chart change.

Entity colors are fixed across charts (validated with the dataviz palette
validator): baseline = neutral gray (reference; also dotted), selected strategy
= blue, manual what-if = orange. Every chart has a single y-axis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .theme import ACCENT, BG, BODY_FONT, GREEN, GRID, INK, MUTED

from src.contracts.types import (
    BacktestReport,
    BaselineBundle,
    BenchmarkResult,
    ExplanationResult,
    OptimizationResult,
    RiskResult,
    SimulationResult,
)

TARGET_LABELS = {"total_co2e_tco2e": "Total emissions (tCO₂e)", "operating_profit_gbp": "Operating profit (GBP)"}


@dataclass(frozen=True)
class Theme:
    surface: str
    text: str
    text_secondary: str
    muted: str
    grid: str
    axis: str
    baseline: str
    selected: str
    whatif: str
    actual: str
    positive: str
    negative: str


LIGHT = Theme(
    surface="#fcfcfb", text="#0b0b0b", text_secondary="#52514e", muted="#898781", grid="#e1e0d9", axis="#c3c2b7",
    baseline="#898781", selected="#2a78d6", whatif="#eb6834", actual="#0b0b0b", positive="#2a78d6", negative="#e34948",
)
DARK = Theme(
    surface=BG, text=INK, text_secondary=MUTED, muted=MUTED, grid=GRID, axis=GRID,
    baseline=MUTED, selected=ACCENT, whatif="#f0a85b", actual=GREEN, positive=GREEN, negative="#ff7387",
)


def theme_for(dark: bool) -> Theme:
    return DARK if dark else LIGHT


def _layout(fig: go.Figure, t: Theme, *, height: int, x_title: str | None = None, y_title: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=36, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=BODY_FONT, color=t.text_secondary, size=14),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(color=t.text_secondary)),
        hoverlabel=dict(font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif')),
        hovermode="x unified",
    )
    axis = dict(gridcolor=t.grid, linecolor=t.axis, zerolinecolor=t.axis, tickfont=dict(color=t.muted), title_font=dict(color=t.text_secondary))
    fig.update_xaxes(**axis, showline=True)
    fig.update_yaxes(**axis, showline=False)
    if x_title:
        fig.update_xaxes(title_text=x_title)
    if y_title:
        fig.update_yaxes(title_text=y_title)
    return fig


# --------------------------------------------------------------------------- #
# History + baseline forecast
# --------------------------------------------------------------------------- #


def history_and_baseline(history: pd.DataFrame | None, baseline: BaselineBundle, target: str, *, dark: bool = False) -> go.Figure:
    t = theme_for(dark)
    fig = go.Figure()
    if history is not None and len(history):
        fig.add_trace(go.Scatter(
            x=history["timestamp"], y=history[target], name="History", mode="lines",
            line=dict(color=t.actual, width=2),
        ))
    fig.add_trace(go.Scatter(
        x=baseline.monthly["timestamp"], y=baseline.monthly[target], name="Baseline forecast", mode="lines",
        line=dict(color=t.baseline, width=2, dash="dot"),
    ))
    start = baseline.monthly["timestamp"].iloc[0]
    fig.add_vline(x=start, line=dict(color=t.axis, width=1))
    fig.add_annotation(x=start, y=1, yref="paper", text="Forecast starts", showarrow=False, xanchor="left",
                       font=dict(color=t.muted, size=11))
    return _layout(fig, t, height=300, y_title=TARGET_LABELS[target])


# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #


def backtest_predictions(report: BacktestReport, target: str, *, dark: bool = False) -> go.Figure:
    t = theme_for(dark)
    oof = report.oof_predictions[report.oof_predictions["target"] == target]
    if "horizon" in oof.columns:  # multi-horizon walk-forward: plot the 1-month-ahead path (presentation only)
        oof = oof[oof["horizon"] == 1]
    oof = oof.sort_values("timestamp")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=oof["timestamp"], y=oof["actual"], name="Actual", mode="lines", line=dict(color=t.actual, width=2)))
    fig.add_trace(go.Scatter(x=oof["timestamp"], y=oof["predicted"], name="Model (out-of-fold)", mode="lines",
                             line=dict(color=t.selected, width=2)))
    fig.add_trace(go.Scatter(x=oof["timestamp"], y=oof["naive_predicted"], name="Seasonal naive", mode="lines",
                             line=dict(color=t.baseline, width=2, dash="dot")))
    for _, fold in report.folds[report.folds["target"] == target].iterrows():
        fig.add_vline(x=fold["test_start"], line=dict(color=t.grid, width=1))
    return _layout(fig, t, height=280, y_title=TARGET_LABELS[target])


# --------------------------------------------------------------------------- #
# Pareto
# --------------------------------------------------------------------------- #


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
    t = theme_for(dark)
    fig = go.Figure()
    ids: dict[tuple[int, int], str] = {}
    cand = optimization.candidates
    pareto = optimization.pareto.sort_values("total_co2e_tco2e")
    hover = (
        "Emissions %{x:,.1f} tCO₂e<br>Profit £%{y:,.0f}"
        "<br>Gross outlay £%{customdata[1]:,.0f}<extra></extra>"
    )

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
        add(infeasible, name="Infeasible candidate", mode="markers",
            marker=dict(color=t.muted, size=6, opacity=0.35, symbol="x-thin", line=dict(width=1, color=t.muted)))
    if len(dominated):
        add(dominated, name="Feasible, dominated", mode="markers",
            marker=dict(color=t.muted, size=7, opacity=0.6, line=dict(width=0)))
    if len(pareto):
        add(pareto, name="Pareto frontier", mode="lines+markers",
            line=dict(color=t.selected, width=2), marker=dict(color=t.selected, size=10, line=dict(width=2, color=t.surface)))
    for sid, label, symbol in ((recommended_id, "Recommended", "star"), (selected_id, "Selected", "circle-open")):
        if sid and sid in set(pareto["strategy_id"]):
            row = pareto[pareto["strategy_id"] == sid]
            add(row, name=label, mode="markers",
                marker=dict(color=t.selected if symbol == "star" else t.text, size=18 if symbol == "star" else 22,
                            symbol=symbol, line=dict(width=2, color=t.surface if symbol == "star" else t.text)))
    base = baseline.totals
    fig.add_trace(go.Scatter(
        x=[base["total_co2e_tco2e"]], y=[base["operating_profit_gbp"]], name="Baseline (no action)", mode="markers",
        marker=dict(color=t.baseline, size=12, symbol="square", line=dict(width=2, color=t.surface)),
        hovertemplate="<b>Baseline</b><br>Emissions %{x:,.1f} tCO₂e<br>Profit £%{y:,.0f}<extra></extra>",
    ))
    if whatif is not None:
        fig.add_trace(go.Scatter(
            x=[whatif.metrics["total_co2e_tco2e"]], y=[whatif.metrics["total_profit_gbp"]], name="Manual what-if",
            mode="markers", marker=dict(color=t.whatif, size=13, symbol="diamond", line=dict(width=2, color=t.surface)),
            hovertemplate="<b>Manual what-if</b><br>Emissions %{x:,.1f} tCO₂e<br>Profit £%{y:,.0f}<extra></extra>",
        ))
    _layout(fig, t, height=440, x_title="Horizon emissions (tCO₂e) — lower is better",
            y_title="Cumulative operating profit (GBP)")
    fig.update_layout(hovermode="closest", clickmode="event+select", dragmode="pan")
    fig.update_yaxes(tickprefix="£", tickformat=",.0f")
    return ParetoFigure(figure=fig, point_ids=ids)


# --------------------------------------------------------------------------- #
# Monthly comparison
# --------------------------------------------------------------------------- #


def monthly_comparison(
    baseline: BaselineBundle,
    scenarios: Mapping[str, SimulationResult],
    *,
    dark: bool = False,
) -> go.Figure:
    """Two stacked panels (emissions, operating profit), each with its own single
    y-axis and a shared month axis. Keys of `scenarios`: 'selected', 'whatif'."""
    t = theme_for(dark)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12,
                        subplot_titles=("Monthly emissions (tCO₂e)", "Monthly operating profit (GBP)"))
    styles = {
        "baseline": ("Baseline", dict(color=t.baseline, width=2, dash="dot")),
        "selected": ("Selected strategy", dict(color=t.selected, width=2)),
        "whatif": ("Manual what-if", dict(color=t.whatif, width=2)),
    }
    # Baseline is drawn last so its dotted reference line stays visible when a
    # scenario coincides with it (e.g. the no-op what-if).
    series = {**{k: v.monthly for k, v in scenarios.items()}, "baseline": baseline.monthly}
    for key, frame in series.items():
        name, line = styles[key]
        for row, col, fmt in ((1, "total_co2e_tco2e", ",.2f"), (2, "operating_profit_gbp", ",.0f")):
            fig.add_trace(go.Scatter(
                x=frame["timestamp"], y=frame[col], name=name, legendgroup=key, showlegend=row == 1,
                mode="lines+markers", line=line, marker=dict(size=6),
                hovertemplate=f"{name}: %{{y:{fmt}}}<extra></extra>",
            ), row=row, col=1)
    _layout(fig, t, height=460)
    fig.update_yaxes(tickprefix="£", tickformat=",.0f", row=2, col=1)
    fig.update_annotations(font=dict(color=t.text_secondary, size=12), x=0, xanchor="left")
    fig.update_layout(legend=dict(y=1.08))
    return fig


def scope_totals(
    baseline: BaselineBundle, scenarios: Mapping[str, SimulationResult], *, dark: bool = False
) -> go.Figure:
    """Horizon emissions by scope, grouped by scenario (presentation sums only)."""
    t = theme_for(dark)
    scopes = [("scope1_tco2e", "Scope 1"), ("scope2_tco2e", "Scope 2"), ("scope3_tco2e", "Scope 3")]
    styles = {"baseline": ("Baseline", t.baseline), "selected": ("Selected strategy", t.selected), "whatif": ("Manual what-if", t.whatif)}
    series = {"baseline": baseline.monthly, **{k: v.monthly for k, v in scenarios.items()}}
    fig = go.Figure()
    for key, frame in series.items():
        name, color = styles[key]
        fig.add_trace(go.Bar(
            x=[label for _, label in scopes], y=[float(frame[c].sum()) for c, _ in scopes], name=name,
            marker=dict(color=color, line=dict(width=0), cornerradius=4),
            hovertemplate=f"{name}<br>%{{x}}: %{{y:,.1f}} tCO₂e<extra></extra>",
        ))
    _layout(fig, t, height=300, y_title="Horizon emissions (tCO₂e)")
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08, hovermode="closest")
    return fig


# --------------------------------------------------------------------------- #
# P1 optional panels
# --------------------------------------------------------------------------- #


def risk_intervals(risk: RiskResult, deterministic: SimulationResult | None, *, dark: bool = False) -> go.Figure:
    """Empirical p05–p95 trial interval (not a confidence interval on the mean)."""
    t = theme_for(dark)
    s = risk.summary
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Horizon emissions (tCO₂e)", "Cumulative profit (GBP)"),
                        horizontal_spacing=0.14)
    for col, (lo, mean, hi, metric) in enumerate((
        ("co2_p05_tco2e", "co2_mean_tco2e", "co2_p95_tco2e", "total_co2e_tco2e"),
        ("profit_p05_gbp", "profit_mean_gbp", "profit_p95_gbp", "total_profit_gbp"),
    ), start=1):
        fig.add_trace(go.Scatter(
            x=[s[mean]], y=["Trials"], mode="markers", name="Trial mean", showlegend=col == 1,
            marker=dict(color=t.selected, size=12),
            error_x=dict(type="data", symmetric=False, array=[s[hi] - s[mean]], arrayminus=[s[mean] - s[lo]],
                         color=t.selected, thickness=2, width=8),
            hovertemplate="p05 %{customdata[0]:,.1f} · mean %{x:,.1f} · p95 %{customdata[1]:,.1f}<extra></extra>",
            customdata=[[s[lo], s[hi]]],
        ), row=1, col=col)
        if deterministic is not None:
            fig.add_trace(go.Scatter(
                x=[deterministic.metrics[metric]], y=["Deterministic"], mode="markers", name="Deterministic result",
                showlegend=col == 1, marker=dict(color=t.baseline, size=11, symbol="square"),
            ), row=1, col=col)
    _layout(fig, t, height=220)
    fig.update_layout(hovermode="closest")
    fig.update_annotations(font=dict(color=t.text_secondary, size=12))
    return fig


def shap_contributions(explanation: ExplanationResult, target: str, *, dark: bool = False) -> go.Figure:
    """Mean |SHAP| ranking is a presentation summary of provider rows."""
    t = theme_for(dark)
    rows = explanation.contributions[explanation.contributions["target"] == target]
    mean = rows.groupby("feature")["shap_value"].mean().sort_values(key=lambda s: s.abs())
    fig = go.Figure(go.Bar(
        x=mean.to_numpy(), y=mean.index.tolist(), orientation="h",
        marker=dict(color=[t.positive if v >= 0 else t.negative for v in mean.to_numpy()], cornerradius=4),
        hovertemplate="%{y}: %{x:,.3f}<extra></extra>",
    ))
    unit = explanation.units.get(target, "")
    _layout(fig, t, height=60 + 36 * len(mean), x_title=f"Mean contribution to raw model output ({unit})")
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig


def benchmark_position(result: BenchmarkResult, *, dark: bool = False) -> go.Figure:
    t = theme_for(dark)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[result.industry_median, result.company_intensity_tco2e_per_million_gbp],
        y=["Peer median", "Company (baseline forecast)"], orientation="h",
        marker=dict(color=[t.baseline, t.selected], cornerradius=4),
        hovertemplate="%{y}: %{x:,.1f} tCO₂e per £m revenue<extra></extra>",
    ))
    _layout(fig, t, height=160, x_title="Emissions intensity (tCO₂e per £m revenue) — lower is better")
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig
