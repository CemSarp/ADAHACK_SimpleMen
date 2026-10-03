"""Public reference data, official conversion factors and a deterministic electricity scenario.

Kept separate from the optimizer: nothing here reads or writes analysis requests, providers or
action assumptions. Snapshots live in data/public/ and are loaded relative to the repository root.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

PUBLIC_DIR = Path(__file__).resolve().parents[2] / "data" / "public"
_COMPANY_META = ("source_id", "source_url", "retrieved_at", "period_start", "period_end", "data_kind")
_FACTOR_FIELDS = ("value", "unit", "factor_id", "sheet", "row", "year", "version", "source_url", "retrieved_at",
                  "license")
REQUIRED_FACTORS = ("uk_electricity",)


def _load(name: str) -> dict[str, Any]:
    return json.loads((PUBLIC_DIR / name).read_text(encoding="utf-8"))


def _require(record: dict[str, Any], fields: tuple[str, ...], what: str) -> None:
    missing = [f for f in fields if record.get(f) in (None, "")]
    if missing:
        raise ValueError(f"{what} is missing source metadata: {', '.join(missing)}")


def load_company_reference() -> dict[str, Any]:
    """Wincanton FY2024 annual disclosure: reported historical totals, never monthly observations."""
    ref = _load("wincanton_fy2024.json")
    _require(ref, _COMPANY_META, "company reference")
    return ref


def load_factors() -> dict[str, dict[str, Any]]:
    """Factor records keyed by factor key, each carrying its own workbook provenance."""
    snap = _load("uk_factors_2026.json")
    meta = {k: snap.get(k) for k in ("year", "version", "source_url", "retrieved_at", "license", "publication_url")}
    factors = {key: {**meta, **rec} for key, rec in snap.get("factors", {}).items()}
    for key in REQUIRED_FACTORS:
        if key not in factors:
            raise ValueError(f"factor snapshot is missing required factor {key!r}")
    for key, rec in factors.items():
        _require(rec, _FACTOR_FIELDS, f"factor {key!r}")
    return factors


def _finite_nonneg(field: str, value: Any) -> float:
    # A blank is unavailable, not zero.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be a finite number >= 0, got {value!r}")
    return float(value)


def calculate_electricity_scenario(
    electricity_kwh: float,
    reduction_ratio: float,
    tariff_gbp_per_kwh: float,
    *,
    factor: dict,
) -> dict:
    """tCO2e = kWh x kgCO2e/kWh / 1000, before and after a fractional consumption reduction."""
    kwh = _finite_nonneg("electricity_kwh", electricity_kwh)
    tariff = _finite_nonneg("tariff_gbp_per_kwh", tariff_gbp_per_kwh)
    ratio = _finite_nonneg("reduction_ratio", reduction_ratio)
    if ratio > 1:
        raise ValueError(f"reduction_ratio must be between 0 and 1, got {reduction_ratio!r}")
    if factor.get("unit") != "kgCO2e/kWh":
        raise ValueError(f"factor unit must be 'kgCO2e/kWh', got {factor.get('unit')!r}")
    kg_per_kwh = _finite_nonneg("factor value", factor.get("value"))
    saved_kwh = kwh * ratio
    baseline = kwh * kg_per_kwh / 1000.0
    scenario = (kwh - saved_kwh) * kg_per_kwh / 1000.0
    return {
        "baseline_tco2e": baseline,
        "scenario_tco2e": scenario,
        "saved_tco2e": baseline - scenario,
        "saved_kwh": saved_kwh,
        "gross_energy_savings_gbp": saved_kwh * tariff,
        "factor_id": factor.get("factor_id"),
        "factor_year": factor.get("year"),
        "assumptions": {"reduction_ratio": ratio, "tariff_gbp_per_kwh": tariff},
    }


# ---- GB grid forecast (Carbon Intensity API) and one-hour scheduling ------- #
# Forecast generation CO2 in gCO2/kWh (GB average): not lifecycle CO2e, not a corporate reporting factor.

GRID_URL = "https://api.carbonintensity.org.uk/intensity/{start}/fw48h"
GRID_TIMEOUT_S = 5
_SLOT = pd.Timedelta(minutes=30)


class GridFetchError(RuntimeError):
    """The live forecast could not be fetched or was malformed; callers decide on a labelled fallback."""


def _aware(as_of: dt.datetime) -> pd.Timestamp:
    if not isinstance(as_of, dt.datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be a timezone-aware datetime")
    return pd.Timestamp(as_of).tz_convert("UTC")


def fetch_grid_forecast(as_of: dt.datetime) -> dict[str, Any]:
    """One live fw48h request (5 s timeout). Never falls back to the recorded snapshot itself."""
    url = GRID_URL.format(start=_aware(as_of).strftime("%Y-%m-%dT%H:%MZ"))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=GRID_TIMEOUT_S) as resp:
            body = json.load(resp)
        snapshot = {"source_url": url, "fetched_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "data_kind": "live_forecast", "response": body}
        normalize_grid_snapshot(snapshot)  # validate shape before anyone displays it
    except (OSError, ValueError) as exc:  # URLError and timeouts are OSErrors; bad JSON/shape is ValueError
        raise GridFetchError(f"Carbon Intensity API request failed: {exc}") from exc
    return snapshot


def load_grid_snapshot() -> dict[str, Any]:
    """A genuinely fetched fw48h response, kept for offline demos and always labelled a recorded example."""
    snap = _load("grid_forecast_snapshot.json")
    _require(snap, ("source_url", "fetched_at", "data_kind", "response"), "grid snapshot")
    return snap


def _intensity(value: Any, field: str) -> float:
    if value is None:
        return math.nan  # missing stays missing, never zero
    return _finite_nonneg(field, value)


def normalize_grid_snapshot(snapshot: dict) -> pd.DataFrame:
    """UTC-aware from/to, forecast and nullable actual gCO2/kWh, sorted by interval start."""
    try:
        rows = [(r["from"], r["to"], r["intensity"].get("forecast"), r["intensity"].get("actual"))
                for r in snapshot["response"]["data"]]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"unexpected Carbon Intensity response shape: {exc!r}") from exc
    df = pd.DataFrame({
        "from": pd.to_datetime([r[0] for r in rows], utc=True),
        "to": pd.to_datetime([r[1] for r in rows], utc=True),
        "forecast_gco2_per_kwh": [_intensity(r[2], "forecast") for r in rows],
        "actual_gco2_per_kwh": [_intensity(r[3], "actual") for r in rows],
    }, columns=["from", "to", "forecast_gco2_per_kwh", "actual_gco2_per_kwh"])
    return df.sort_values("from", kind="stable").reset_index(drop=True)


def choose_one_hour_window(intervals: pd.DataFrame, *, energy_kwh: float, as_of: dt.datetime) -> dict | None:
    """Earliest vs lowest-forecast contiguous pair of complete future 30-minute slots, constant power.

    Slots with a missing forecast, a non-30-minute length or any overlap are ineligible; pairs must join exactly.
    Returns None when no eligible full hour exists.
    """
    start = _aware(as_of)
    energy = _finite_nonneg("energy_kwh", energy_kwh)
    df = intervals.sort_values("from", kind="stable").reset_index(drop=True)
    overlap = (df["from"].shift(-1) < df["to"]) | (df["from"] < df["to"].shift(1))
    ok = (~overlap & (df["to"] - df["from"] == _SLOT) & df["forecast_gco2_per_kwh"].notna()).tolist()
    windows = []
    for i in range(len(df) - 1):
        a, b = df.iloc[i], df.iloc[i + 1]
        if ok[i] and ok[i + 1] and a["to"] == b["from"] and a["from"] >= start:
            kg = energy / 2 * (a["forecast_gco2_per_kwh"] + b["forecast_gco2_per_kwh"]) / 1000.0
            windows.append((a["from"].to_pydatetime(), b["to"].to_pydatetime(), kg))
    if not windows:
        return None
    base, best = windows[0], min(windows, key=lambda w: w[2])  # min keeps the earliest on a tie
    return {"baseline_start": base[0], "baseline_end": base[1], "best_start": best[0], "best_end": best[1],
            "baseline_kgco2": base[2], "best_kgco2": best[2], "saved_kgco2": base[2] - best[2],
            "energy_kwh": energy}
