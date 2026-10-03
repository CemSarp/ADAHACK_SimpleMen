"""Exploratory data analysis with the shared dashboard palette."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .theme import ACCENT, BG, BODY_FONT, GREEN, GRID, HEAD_FONT, INK, MUTED, PANEL

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "synthetic_data.csv"

RANGES = {"1 year": 12, "5 years": 60, "10 years": 120, "25 years": 300}


_UNIT_SUFFIXES = (
    ("_eur_per_kwh", "EUR/kWh"), ("_eur_per_l", "EUR/L"), ("_eur_per_t", "EUR/t"),
    ("_kg_per_kwh", "kgCO2e/kWh"), ("_tco2e", "tCO2e"), ("_eur", "EUR"), ("_tkm", "t-km"),
    ("_kwh", "kWh"), ("_l", "L"), ("_m2", "m2"), ("_km", "km"),
)
_RATIO_COLUMNS = {"load_factor", "empty_km_ratio"}

_CSS = f"""
<style>
.st-key-eda_panel {{
  background: {BG}; border: 1px solid {GRID}; width: 100%;
  padding: 1.2rem; border-radius: 8px; margin: .25rem 0 1rem 0;
}}
.eda-label {{ font-family: {HEAD_FONT}; color: {ACCENT}; font-size: 13px; margin: 0 0 .2rem 0; }}
.eda-tiles {{ display: flex; flex-wrap: wrap; gap: 8px; margin: .3rem 0 .2rem 0; }}
.eda-tile {{ flex: 1 1 90px; background: {PANEL}; border: 1px solid {GRID}; padding: .35rem .5rem; }}
.eda-tile .k {{ font-family: {HEAD_FONT}; color: {MUTED}; font-size: 13px; margin-bottom: .25rem; }}
.eda-tile .v {{ font-family: {BODY_FONT}; color: {INK}; font-size: 22px; line-height: 1.3; }}
.eda-tile .v.up {{ color: {GREEN}; }}
.eda-tile .v.down {{ color: #ff5d73; }}
.st-key-eda_panel [data-baseweb="select"] > div {{
  background: {PANEL}; border: 1px solid {GREEN}; border-radius: 0; font-family: {BODY_FONT}; font-size: 18px; color: {INK}; min-height: 32px;
}}
.st-key-eda_panel [data-baseweb="select"] svg {{ fill: {GREEN}; }}
</style>
"""


@st.cache_data(show_spinner=False)
def _load() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH, parse_dates=["date"])


def _label(column: str) -> str:
    label = column
    for suffix, _ in _UNIT_SUFFIXES:
        if label.endswith(suffix):
            label = label[:-len(suffix)]
            break
    return label.replace("_", " ").capitalize()


def _unit(column: str) -> str:
    if column.endswith("_share") or column in _RATIO_COLUMNS:
        return "%"
    for suffix, unit in _UNIT_SUFFIXES:
        if column.endswith(suffix):
            return unit
    return ""


def _fmt(column: str, value: float) -> str:
    if _unit(column) == "%":
        return f"{value * 100:.1f}%"
    magnitude = abs(value)
    for limit, tag in ((1e9, "G"), (1e6, "M"), (1e3, "K")):
        if magnitude >= limit:
            return f"{value / limit:.2f}{tag}"
    return f"{value:.3g}" if magnitude < 10 else f"{value:.1f}"


def _tile(key: str, value: str, tone: str = "") -> str:
    return f'<div class="eda-tile"><div class="k">{key}</div><div class="v {tone}">{value}</div></div>'


def _figure(df: pd.DataFrame, column: str, months: int) -> go.Figure:
    window = df.tail(months)
    rolling = df[column].rolling(12, min_periods=12).mean().tail(months)
    pct = _unit(column) == "%"
    scale = 100 if pct else 1
    font = dict(family=BODY_FONT, color=INK, size=15)
    fig = go.Figure()
    fig.add_scatter(x=window["date"], y=window[column] * scale, mode="lines", line=dict(color=GREEN, width=2, shape="hv"),
                    name=_label(column), hovertemplate="%{x|%b %Y}<br>%{y:,.4g}<extra></extra>")
    if months > 12:
        fig.add_scatter(x=window["date"], y=rolling * scale, mode="lines", line=dict(color=ACCENT, width=2, dash="dot"),
                        name="12-month average", hovertemplate="%{x|%b %Y}<br>%{y:,.4g}<extra>12-month average</extra>")
    fig.update_layout(
        height=260, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor=BG, plot_bgcolor=BG, font=font,
        hovermode="x unified", hoverlabel=dict(bgcolor=PANEL, bordercolor=GREEN, font=font),
        legend=dict(orientation="h", y=1.12, x=0, font=dict(family=BODY_FONT, size=15)),
        xaxis=dict(gridcolor=GRID, linecolor=GRID, zerolinecolor=GRID, tickfont=font),
        yaxis=dict(title=_unit(column), gridcolor=GRID, linecolor=GRID, zerolinecolor=GRID, tickfont=font, ticksuffix="%" if pct else ""),
    )
    return fig


def feature_explorer() -> None:
    st.html(_CSS)
    if not DATA_PATH.exists():
        st.info("Historical data is currently unavailable.", icon="ℹ️")
        return
    df = _load()
    features = [c for c in df.columns if c != "date"]

    with st.container(key="eda_panel"):
        st.subheader("Exploratory Data Analysis")
        st.caption("Explore historical trends in emissions, finances and operations before planning changes.")
        c_feature, c_range = st.columns([3, 1])
        with c_feature:
            st.html('<div class="eda-label">FEATURE</div>')
            default = features.index("total_emissions_tco2e") if "total_emissions_tco2e" in features else 0
            column = st.selectbox("Feature", features, index=default, format_func=_label,
                                  key="eda_feature", label_visibility="collapsed")
        with c_range:
            st.html('<div class="eda-label">TIME WINDOW</div>')
            window_name = st.selectbox("Time window", list(RANGES), index=1, key="eda_range",
                                       label_visibility="collapsed")
        months = RANGES[window_name]
        window = df.tail(months)[column]
        start, end = float(window.iloc[0]), float(window.iloc[-1])
        change = (end - start) / abs(start) if start else 0.0
        unit = _unit(column)
        suffix = f" {unit}" if unit and unit != "%" else ""
        tiles = "".join([
            _tile("Latest", _fmt(column, end) + suffix),
            _tile("Change over window", f"{change * 100:+.1f}%", "up" if change > 0 else "down" if change < 0 else ""),
            _tile("Minimum", _fmt(column, float(window.min())) + suffix),
            _tile("Maximum", _fmt(column, float(window.max())) + suffix),
            _tile("Average", _fmt(column, float(window.mean())) + suffix),
        ])
        st.html(f'<div class="eda-tiles">{tiles}</div>')
        st.plotly_chart(_figure(df, column, months), width="stretch", config={"displayModeBar": False})
