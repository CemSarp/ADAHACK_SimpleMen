"""SHAP feature-importance dashboard for the models trained in the trainer panel."""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import trainer
from .theme import ACCENT, BG, BODY_FONT, GREEN, GRID, INK, MUTED, PANEL

TREE_MODELS = ("XGBoost", "LightGBM", "RandomForest")
HORIZONS = {"ALL MONTHS": None, "MONTH 1": 1, "MONTH 2": 2, "MONTH 3": 3}
LINE_COLORS = {1: GREEN, 2: ACCENT, 3: "#ffffff"}
DIM = "#2c3a33"

_CSS = f"""
<style>
.st-key-shap_panel {{
  background: {BG}; border: 2px solid {GREEN}; max-width: 760px;
  padding: .8rem 1rem .6rem 1rem; border-radius: 0; margin: .25rem 0 1rem 0;
}}
.st-key-shap_panel [data-baseweb="select"] > div {{
  background: {PANEL}; border: 1px solid {GREEN}; border-radius: 0; font-family: {BODY_FONT}; font-size: 18px;
  color: {INK}; min-height: 32px;
}}
.st-key-shap_panel [data-baseweb="select"] svg {{ fill: {GREEN}; }}
.st-key-shap_panel [data-testid="stSlider"] div[role="slider"] {{ background: {GREEN}; border-radius: 0; }}
.st-key-shap_panel [data-testid="stSlider"] [data-testid="stTickBarMin"],
.st-key-shap_panel [data-testid="stSlider"] [data-testid="stTickBarMax"],
.st-key-shap_panel [data-testid="stSliderThumbValue"] {{ font-family: {BODY_FONT}; font-size: 18px; color: {GREEN}; }}
</style>
"""


@dataclass
class HorizonShap:
    features: list[str]
    shap_train: np.ndarray
    level_train: np.ndarray
    scale_train: np.ndarray
    base: float
    shap_last: np.ndarray
    level_last: float
    scale_last: float
    date: str


def _silence_joblib_config_warning() -> None:
    """Re-assert the filter: Streamlit and sklearn both use the thread-unsafe warnings.catch_warnings,
    which can restore an older filter list and silently drop a filter installed once at import."""
    warnings.filterwarnings("ignore", category=UserWarning, module=r"sklearn\.utils\.parallel")
    warnings.filterwarnings("ignore", message=".*sklearn.utils.parallel.delayed.*")


def _summaries(job: trainer.TrainingJob) -> dict[str, dict]:
    out = {}
    for key in trainer.TARGETS:
        path = job.output_dir / key / "summary.json"
        if path.exists():
            out[key] = json.loads(path.read_text(encoding="utf-8"))
    return out


@st.cache_data(show_spinner=False)
def _explain(target: str, model: str, trained_at: float) -> dict[int, HorizonShap]:
    """Refits `model` on all data and returns SHAP values (relative-target space) per horizon."""
    import shap

    from ml_core import modelling as mm

    _silence_joblib_config_warning()
    data = mm.prepare_data(pd.read_csv(trainer.DATA_PATH, parse_dates=["date"]))
    pipeline = mm.ForecastingPipeline(target, data, mm.ModellingConfig(models=(model,)))
    forecaster = pipeline.models[model]().fit(data)
    last = data["date"].iloc[-1]
    result = {}
    for h, estimator in forecaster.models_.items():
        X, y, level, scale = mm.build_supervised(data, pipeline.spec, h)
        mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
        explainer = shap.TreeExplainer(estimator)
        result[h] = HorizonShap(
            features=list(X.columns), shap_train=np.asarray(explainer.shap_values(X[mask])),
            level_train=level[mask].to_numpy(), scale_train=scale[mask].to_numpy(),
            base=float(np.ravel(explainer.expected_value)[0]),
            shap_last=np.asarray(explainer.shap_values(X.iloc[[-1]]))[0],
            level_last=float(level.iloc[-1]), scale_last=float(scale.iloc[-1]),
            date=(last + pd.DateOffset(months=h)).strftime("%Y-%m"))
    return result


def _units(rel, level, scale, positive: bool):
    return level * np.exp(rel) if positive else level + scale * rel


def _style(fig: go.Figure, height: int) -> go.Figure:
    font = dict(family=BODY_FONT, color=INK, size=15)
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor=BG, plot_bgcolor=BG, font=font,
        hoverlabel=dict(bgcolor=PANEL, bordercolor=GREEN, font=font), legend=dict(orientation="h", y=1.15, x=0, font=font))
    fig.update_xaxes(gridcolor=GRID, linecolor=GRID, tickfont=font)
    fig.update_yaxes(gridcolor=GRID, linecolor=GRID, tickfont=font)
    return fig


def _signed(value: float, digits: int = 0) -> str:
    return f"{value:+,.{digits}f}"


def _hint(text: str) -> None:
    st.html(f'<div class="tr-lines" style="color:{MUTED}">&gt; {text}<span class="tr-cur">_</span></div>')


def shap_explorer() -> None:
    st.html(_CSS)
    job = st.session_state.get(trainer.JOB_KEY)
    with st.container(key="shap_panel"):
        st.html('<div class="tr-title">&gt; FEATURE IMPORTANCE (SHAP)</div>')
        if job is None:
            return _hint("TRAIN MODELS FIRST. SHAP EXPLAINS THE TRAINED TREE MODELS")
        if job.running:
            return _hint("WAITING FOR TRAINING TO FINISH")
        summaries = _summaries(job) if job.returncode == 0 else {}
        if not summaries:
            return _hint("NO TRAINING RESULTS AVAILABLE")

        c_target, c_model, c_horizon = st.columns(3)
        with c_target:
            st.html('<div class="tr-label">TARGET</div>')
            target = st.selectbox("Target", list(summaries), format_func=lambda t: summaries[t]["label"].upper(),
                                  key="shap_target", label_visibility="collapsed")
        summary = summaries[target]
        metric = summary["selection_metric"]
        trained = sorted((m for m in summary["backtest_metrics"] if m in TREE_MODELS),
                         key=lambda m: summary["backtest_metrics"][m][metric])
        if not trained:
            return _hint("SHAP NEEDS A TREE MODEL: TRAIN XGBOOST, LIGHTGBM OR RANDOMFOREST")
        with c_model:
            st.html('<div class="tr-label">MODEL</div>')
            model = st.selectbox("Model", trained, key=f"shap_model_{target}", label_visibility="collapsed")
        with c_horizon:
            st.html('<div class="tr-label">HORIZON</div>')
            horizon_name = st.selectbox("Horizon", list(HORIZONS), key="shap_horizon", label_visibility="collapsed")
        if model != summary["best_model"]:
            st.html(f'<div class="tr-lines" style="color:{MUTED};font-size:15px">BEST MODEL IS '
                    f'{summary["best_model"].upper()}'
                    + (" (NOT A TREE MODEL)" if summary["best_model"] not in TREE_MODELS else "") + "</div>")

        with st.spinner("COMPUTING SHAP VALUES..."):
            expl = _explain(target, model, job.started)
        positive = trainer_positive(target)
        hs = [h for h in expl if HORIZONS[horizon_name] in (None, h)]
        features = expl[hs[0]].features
        n = len(features)
        importance = np.mean([np.abs(expl[h].shap_train).mean(axis=0) for h in hs], axis=0)
        order = np.argsort(-importance)
        share = importance / importance.sum()

        st.html('<div class="tr-label" style="margin-top:.6rem">TOP-K FEATURES</div>')
        k = st.slider("Top-k", 1, n, min(5, n), key=f"shap_k_{target}", label_visibility="collapsed")
        top = order[:k]

        tiles = [trainer._card("IMPORTANCE CAPTURED", f"{share[top].sum() * 100:.0f}%", True)]
        history_dev = []
        for h in hs:
            e = expl[h]
            full = _units(e.base + e.shap_last.sum(), e.level_last, e.scale_last, positive)
            topk = _units(e.base + e.shap_last[top].sum(), e.level_last, e.scale_last, positive)
            tiles.append(trainer._card(
                f"{e.date} FORECAST",
                f'{full:,.0f} <span style="font-size:15px;color:{MUTED}">TOP-{k}: {topk:,.0f} '
                f'({_signed((topk / full - 1) * 100, 1)}%)</span>'))
            f_all = _units(e.base + e.shap_train.sum(axis=1), e.level_train, e.scale_train, positive)
            f_top = _units(e.base + e.shap_train[:, top].sum(axis=1), e.level_train, e.scale_train, positive)
            history_dev.append(np.abs(f_top - f_all).sum() / np.abs(f_all).sum() * 100)
        tiles.append(trainer._card(f"AVG ERROR TOP-{k} (HISTORY)", f"{np.mean(history_dev):.1f}%"))
        st.html(f'<div class="tr-best">{"".join(tiles)}</div>')

        shown = order[:max(10, min(k, 20))]
        fig = go.Figure(go.Bar(
            y=[features[i] for i in shown], x=importance[shown], orientation="h",
            marker_color=[GREEN if i in top else DIM for i in shown],
            hovertemplate="%{y}<br>mean |SHAP| %{x:.4f}<extra></extra>"))
        _style(fig, 40 + 24 * len(shown)).update_layout(showlegend=False)
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(title=dict(text="MEAN |SHAP| (MODEL UNITS)", font=dict(family=BODY_FONT, size=15)))
        st.html('<div class="tr-label">MOST IMPORTANT FEATURES</div>')
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key="shap_importance_chart")

        curve = go.Figure()
        for h in hs:
            e = expl[h]
            cum = e.base + np.concatenate([[0.0], np.cumsum(e.shap_last[order])])
            units = _units(cum, e.level_last, e.scale_last, positive)
            curve.add_scatter(x=list(range(n + 1)), y=(units / units[-1] - 1) * 100, mode="lines",
                              line=dict(color=LINE_COLORS[h], width=2, shape="hv"), name=e.date,
                              hovertemplate="%{x} features<br>%{y:+.1f}% vs full<extra></extra>")
        curve.add_vline(x=k, line=dict(color=ACCENT, dash="dot", width=2))
        _style(curve, 230)
        curve.update_xaxes(title=dict(text="FEATURES ADDED, MOST IMPORTANT FIRST", font=dict(family=BODY_FONT, size=15)))
        curve.update_yaxes(title=dict(text="FORECAST VS FULL MODEL (%)", font=dict(family=BODY_FONT, size=15)))
        st.html('<div class="tr-label">HOW THE FORECAST BUILDS UP</div>')
        st.plotly_chart(curve, width="stretch", config={"displayModeBar": False}, key="shap_curve_chart")

        h0 = hs[0]
        e = expl[h0]
        steps = _units(e.base + np.concatenate([[0.0], np.cumsum(e.shap_last[order])]), e.level_last, e.scale_last, positive)
        rows = []
        for rank, i in enumerate(order[:min(k, 15)]):
            effect = steps[rank + 1] - steps[rank]
            arrow = "&#9650;" if effect >= 0 else "&#9660;"
            rows.append(f'<tr><td>{rank + 1}. {features[i]}</td><td>{share[i] * 100:.1f}%</td>'
                        f'<td>{arrow} {_signed(effect)}</td></tr>')
        head = ["FEATURE", "SHARE", f"EFFECT ON {e.date} ({summary['unit']})"]
        st.html('<table class="tr-table"><tr>' + "".join(f"<th>{c}</th>" for c in head) + "</tr>" + "".join(rows)
                + "</table>" + (f'<div class="tr-lines" style="color:{MUTED};font-size:15px">SHOWING TOP 15 OF {k}</div>'
                                if k > 15 else ""))


def trainer_positive(target: str) -> bool:
    from ml_core import modelling as mm

    return mm.TARGETS[target].positive
