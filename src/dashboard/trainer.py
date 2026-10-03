"""Model comparison dashboard with progress and a summary report."""

from __future__ import annotations

import logging
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from .theme import ACCENT, BG, GREEN, GRID, INK, MUTED, PANEL, BODY_FONT, HEAD_FONT

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data" / "synthetic_data.csv"
OUTPUT_DIR = ROOT / "ml_core" / "temp_outputs" / "dashboard_run"
JOB_KEY = "trainer_job"
TARGETS = ("emissions", "profit")
RED = "#ff5d73"

_MODELS = (("XGBoost", "xgboost"), ("LightGBM", "lightgbm"), ("RandomForest", None),
           ("Prophet", "prophet"), ("SeasonalNaive", None))
_TIMING = re.compile(r"^(backtest|test)\s+(\w+)\s+(\w+)\s+\d+ origins in ([\d.]+)s")

_CSS = f"""
<style>
.st-key-train_panel {{
  background: {BG}; border: 1px solid {GRID}; width: 100%;
  padding: 1.2rem; border-radius: 8px; margin: .25rem 0 1rem 0;
}}
.st-key-train_panel [data-testid="stBaseButton-pills"],
.st-key-train_panel [data-testid="stBaseButton-pillsActive"] {{
  border-radius: 0; font-family: {BODY_FONT}; font-size: 18px; padding: 0 .7rem; min-height: 30px;
  background: {PANEL}; border: 1px solid {GRID}; color: {MUTED};
}}
.st-key-train_panel [data-testid="stBaseButton-pillsActive"] {{ border-color: {GREEN}; color: {GREEN}; background: #0d2a1a; }}
.st-key-train_panel [data-testid="stBaseButton-primary"],
.st-key-train_panel [data-testid="stBaseButton-secondary"] {{
  border-radius: 0; font-family: {HEAD_FONT}; font-size: 14px; letter-spacing: 1px; min-height: 34px;
  background: {GREEN}; color: {BG}; border: 1px solid {GREEN};
}}
.st-key-train_panel [data-testid="stBaseButton-secondary"] {{ background: transparent; color: {RED}; border-color: {RED}; }}
.st-key-train_panel [data-testid="stBaseButton-primary"]:disabled {{ background: {GRID}; border-color: {GRID}; color: {MUTED}; }}
.tr-label {{ font-family: {HEAD_FONT}; color: {ACCENT}; font-size: 13px; margin: 0 0 .5rem 0; }}
.tr-best {{ display: flex; flex-wrap: wrap; gap: 8px; margin: .2rem 0 .6rem 0; }}
.tr-card {{ flex: 1 1 120px; background: {PANEL}; border: 1px solid {GRID}; padding: .35rem .5rem; }}
.tr-card.star {{ border-color: {GREEN}; }}
.tr-card .k {{ font-family: {HEAD_FONT}; color: {MUTED}; font-size: 13px; margin-bottom: .25rem; }}
.tr-card .v {{ font-family: {BODY_FONT}; color: {INK}; font-size: 22px; line-height: 1.3; }}
.tr-card.star .v {{ color: {GREEN}; }}
.tr-h {{ font-family: {HEAD_FONT}; color: {GREEN}; font-size: 14px; margin: 1rem 0 .5rem 0; }}
table.tr-table {{ width: 100%; border-collapse: collapse; font-family: {BODY_FONT}; font-size: 18px; color: {INK}; }}
table.tr-table th {{ font-family: {HEAD_FONT}; font-size: 13px; color: {MUTED}; text-align: right; padding: 4px 6px; border-bottom: 1px solid {GRID}; }}
table.tr-table td {{ text-align: right; padding: 3px 6px; border-bottom: 1px solid {GRID}; }}
table.tr-table th:first-child, table.tr-table td:first-child {{ text-align: left; }}
table.tr-table tr.best td {{ color: {GREEN}; background: #0d2a1a; }}
</style>
"""


class TrainingJob:
    """A ml_core.modelling subprocess whose output is collected on a reader thread."""

    def __init__(self, models: list[str]) -> None:
        self.models = models
        self.lines: list[str] = []
        self.started = time.time()
        self.finished: float | None = None
        self.returncode: int | None = None
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        cmd = [sys.executable, "-u", "-m", "ml_core.modelling", "--models", *models,
               "--data", str(DATA_PATH), "--output-dir", str(OUTPUT_DIR)]
        self.proc = subprocess.Popen(
            cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, env={**os.environ, "PYTHONIOENCODING": "utf-8", "MPLBACKEND": "Agg"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            self.lines.append(line.rstrip("\n"))
        self.returncode = self.proc.wait()
        self.finished = time.time()

    @property
    def running(self) -> bool:
        return self.returncode is None

    @property
    def elapsed(self) -> float:
        return (self.finished or time.time()) - self.started

    def abort(self) -> None:
        if self.running:
            self.proc.terminate()

    def timings(self) -> dict[tuple[str, str], float]:
        """Seconds spent per (target, model), summed over backtest and test phases."""
        totals: dict[tuple[str, str], float] = {}
        for line in list(self.lines):
            m = _TIMING.match(line)
            if m:
                key = (m.group(2), m.group(3))
                totals[key] = totals.get(key, 0.0) + float(m.group(4))
        return totals

    @property
    def progress(self) -> float:
        total = len(TARGETS) * len(self.models) * 2
        done = sum(1 for line in list(self.lines) if _TIMING.match(line))
        return 1.0 if self.returncode == 0 else min(done / total, 0.97)


def _available_models() -> list[str]:
    return [name for name, module in _MODELS if module is None or importlib.util.find_spec(module)]


def _num(value: float | None, digits: int = 0, suffix: str = "") -> str:
    return "-" if value is None else f"{value:,.{digits}f}{suffix}"


def _card(key: str, value: str, star: bool = False) -> str:
    return f'<div class="tr-card{" star" if star else ""}"><div class="k">{key}</div><div class="v">{value}</div></div>'


def _bar_chart(models: list[str], backtest: list[float], test: list[float], metric: str) -> go.Figure:
    font = dict(family=BODY_FONT, color=INK, size=15)
    fig = go.Figure()
    fig.add_bar(y=models, x=backtest, orientation="h", name="BACKTEST", marker_color=ACCENT)
    fig.add_bar(y=models, x=test, orientation="h", name="TEST", marker_color=GREEN)
    fig.update_layout(
        barmode="group", height=60 + 46 * len(models), margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor=BG,
        plot_bgcolor=BG, font=font, hoverlabel=dict(bgcolor=PANEL, bordercolor=GREEN, font=font),
        legend=dict(orientation="h", y=1.15, x=0, font=font),
        xaxis=dict(gridcolor=GRID, linecolor=GRID, tickfont=font, title=dict(text=f"{metric.upper()} (%)", font=font)),
        yaxis=dict(autorange="reversed", tickfont=font, linecolor=GRID))
    return fig


def _report(job: TrainingJob) -> None:
    timings = job.timings()
    shown = False
    for key in TARGETS:
        path = OUTPUT_DIR / key / "summary.json"
        if not path.exists():
            continue
        shown = True
        s = json.loads(path.read_text(encoding="utf-8"))
        metric, best = s["selection_metric"], s["best_model"]
        bt, te = s["backtest_metrics"], s["test_metrics"]
        ranked = sorted(bt, key=lambda m: bt[m][metric])
        st.html(f'<div class="tr-h">&gt; {s["label"].upper()} ({s["unit"]})</div>')
        cards = [_card("BEST MODEL", f"&#9733; {best}", True),
                 _card(f"TEST {metric.upper()}", _num(te[best][metric], 2, "%")),
                 _card("TEST MAE", _num(te[best]["mae"])),
                 _card("TRAIN TIME", _num(timings.get((key, best)), 1, "s"))]
        st.html(f'<div class="tr-best">{"".join(cards)}</div>')

        head = ["MODEL", f"BACKTEST {metric.upper()}", f"TEST {metric.upper()}", "TEST MAE", "TEST RMSE", "BIAS", "TIME"]
        rows = []
        for m in ranked:
            cells = [("&#9733; " if m == best else "") + m, _num(bt[m][metric], 2, "%"), _num(te[m][metric], 2, "%"),
                     _num(te[m]["mae"]), _num(te[m]["rmse"]), _num(te[m]["bias_pct"], 1, "%"),
                     _num(timings.get((key, m)), 1, "s")]
            rows.append(f'<tr class="{"best" if m == best else ""}">' + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        st.html('<table class="tr-table"><tr>' + "".join(f"<th>{h}</th>" for h in head) + "</tr>" + "".join(rows) + "</table>")
        st.plotly_chart(_bar_chart(ranked, [bt[m][metric] for m in ranked], [te[m][metric] for m in ranked], metric),
                        width="stretch", config={"displayModeBar": False}, key=f"trainer_chart_{key}")

        forecast = s["forecast"]
        lo = next((k for k in next(iter(forecast.values())) if k.startswith("lower_")), None)
        hi = lo.replace("lower_", "upper_") if lo else None
        tiles = "".join(
            _card(f'{v["date"]} ({lo.split("_")[1]}% RANGE)' if lo else v["date"],
                  _num(v["prediction"]) + (f' <span style="font-size:15px;color:{MUTED}">{_num(v[lo])}..{_num(v[hi])}</span>'
                                           if lo else ""))
            for v in forecast.values())
        st.html(f'<div class="tr-label">FORECAST BY {best.upper()}</div><div class="tr-best">{tiles}</div>')
    if not shown:
        st.info("No comparison results were produced. Please try again.")


def _panel(poll: bool) -> None:
    job: TrainingJob | None = st.session_state.get(JOB_KEY)
    if poll and job is not None and not job.running:
        st.rerun()

    with st.container(key="train_panel"):
        st.subheader("Model Selection")
        st.caption("Compare forecasting methods on held-out historical data. This comparison does not change the forecast used for planning.")
        options = _available_models()
        selected = st.pills("Models", options, selection_mode="multi", default=options, key="trainer_models",
                            label_visibility="collapsed") or []
        running = job is not None and job.running
        col_train, col_abort = st.columns(2)
        if col_train.button("Compare models", type="primary", disabled=running or not selected, key="trainer_start", width="stretch"):
            st.session_state[JOB_KEY] = TrainingJob(list(selected))
            st.rerun()
        if running and col_abort.button("Stop comparison", key="trainer_abort", width="stretch"):
            job.abort()
        if job is None:
            st.caption("Choose the forecasting methods to compare, then select Compare models.")
        elif job.running:
            st.progress(job.progress, text="Comparing forecasts with historical outcomes…")
            st.caption(f"Elapsed time: {job.elapsed:.0f} seconds")
        elif job.returncode == 0:
            st.success(f"Comparison complete in {job.elapsed:.0f} seconds.")
        elif job.returncode is not None and job.returncode < 0:
            st.info("Comparison stopped. Choose models to start again.")
        else:
            logger.error("Model comparison failed: %s", "\n".join(job.lines[-100:]))
            st.error("The model comparison could not be completed. Please try again.")
        if job is not None and not job.running and job.returncode == 0:
            _report(job)


def model_trainer() -> None:
    st.html(_CSS)
    job = st.session_state.get(JOB_KEY)
    running = job is not None and job.running
    st.fragment(run_every=0.7 if running else None)(_panel)(running)
