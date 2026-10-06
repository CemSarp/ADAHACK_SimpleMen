"""Design tokens shared by charts and the few styles Streamlit's theme config cannot express.

Colours live in .streamlit/config.toml ([theme.light] / [theme.dark]); this module repeats
the handful charts need and adds report-style typography: serif figures with tabular
digits, small-caps section labels and hairline rules instead of boxed cards.
"""

from __future__ import annotations

from dataclasses import dataclass

SERIF = "Newsreader, Georgia, 'Times New Roman', serif"
SANS = "'IBM Plex Sans', system-ui, -apple-system, sans-serif"


@dataclass(frozen=True)
class Palette:
    text: str
    text_secondary: str
    muted: str
    grid: str
    axis: str
    surface: str
    baseline: str   # reference: no action
    plan: str       # optimized plans
    whatif: str     # the user's own mix
    negative: str


LIGHT = Palette(text="#1c1b18", text_secondary="#4a4842", muted="#8a867c", grid="#e6e1d6", axis="#cfc9bc",
                surface="#f7f4ee", baseline="#8a867c", plan="#1d5c45", whatif="#b4622d", negative="#a8432f")
DARK = Palette(text="#ece8df", text_secondary="#bdb8ad", muted="#8f8a80", grid="#2f2d29", axis="#46433d",
               surface="#161513", baseline="#8f8a80", plan="#6fbf98", whatif="#e0915a", negative="#e07a62")


def palette(dark: bool) -> Palette:
    return DARK if dark else LIGHT


def apply_theme(dark: bool) -> None:
    import streamlit as st

    p = palette(dark)
    st.html(f"""<style>
    [data-testid="stMainBlockContainer"] {{ max-width: 1180px; padding-top: 2.5rem; }}
    h1, h2, h3 {{ letter-spacing: -0.01em; }}
    [data-testid="stMetricValue"] {{ font-family: {SERIF}; font-variant-numeric: tabular-nums lining-nums; }}
    [data-testid="stMetricLabel"] p {{ font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; color: {p.text_secondary}; }}
    [data-testid="stMetric"] {{ padding: .2rem 0; }}
    .co-eyebrow {{ font-size: .75rem; letter-spacing: .12em; text-transform: uppercase; color: {p.text_secondary};
                   border-top: 1px solid {p.axis}; padding-top: .9rem; margin-top: 2.2rem; }}
    .co-lede {{ font-family: {SERIF}; font-size: 1.25rem; line-height: 1.45; color: {p.text_secondary}; max-width: 46rem; }}
    .co-meta {{ font-size: .85rem; color: {p.muted}; font-variant-numeric: tabular-nums; }}
    .co-off {{ color: {p.muted}; }}
    </style>""")
