"""Shared palette and readable panel styling, based on the data explorer."""

from __future__ import annotations

BG = "#0b0f14"
PANEL = "#10161d"
GRID = "#263540"
INK = "#d6ffe6"
MUTED = "#a1b5ab"
GREEN = "#39ff88"
ACCENT = "#4cc9f0"
HEAD_FONT = "'Segoe UI', system-ui, sans-serif"
BODY_FONT = "'Segoe UI', system-ui, sans-serif"


def apply_theme(dark: bool) -> None:
    import streamlit as st

    accent = GREEN if dark else "#147a46"
    border = GRID if dark else "#d4e3da"
    st.html(f"""<style>
    [data-testid="stMainBlockContainer"] {{ max-width: 1280px; padding-top: 2rem; }}
    [data-testid="stHeading"] h2, [data-testid="stHeading"] h3 {{ color: {accent}; }}
    [data-testid="stHeading"] h3 {{ margin-top: .8rem; }}
    [data-testid="stMetric"] {{ border-color: {border}; padding: 1rem; min-width: 180px; }}
    [data-testid="stMetricLabel"] {{ white-space: normal; }}
    [data-testid="stMetricValue"] {{ font-size: clamp(1.3rem, 2vw, 1.8rem); }}
    [data-testid="stExpander"] {{ border-color: {border}; }}
    </style>""")
