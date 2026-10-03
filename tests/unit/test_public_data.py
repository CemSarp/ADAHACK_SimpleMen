"""Public reference data (Wincanton FY2024), the GOV.UK 2026 electricity factor and the scenario calculator."""

from __future__ import annotations

import math

import pytest

from src.data_sources.public_data import calculate_electricity_scenario, load_company_reference, load_factors


def test_company_reference_retains_historical_period():
    ref = load_company_reference()
    assert (ref["period_start"], ref["period_end"]) == ("2023-04-01", "2024-03-31")
    assert ref["data_kind"] == "reported_historical"
    assert ref["source_url"].startswith("https://") and ref["retrieved_at"] and ref["source_id"]
    # Annual totals only: one scalar per reported field, never a generated monthly series.
    assert not any("month" in key for key in ref)
    assert all(isinstance(row["value"], (int, float)) and row["page"] for row in ref["values"].values())


def test_company_reference_reconciles():
    v = {key: row["value"] for key, row in load_company_reference()["values"].items()}
    parts = ("emissions_transport_scope1", "emissions_non_transport_scope1",
             "emissions_electricity_transport", "emissions_electricity_non_transport")
    assert [v[k] for k in parts] == [234_907, 7_948, 149, 17_433]
    assert sum(v[k] for k in parts) == v["emissions_scope1_and_2_total"] == 260_437
    rows = load_company_reference()["values"]
    assert (rows["electricity_non_transport"]["value"], rows["electricity_non_transport"]["unit"]) == (77_485, "MWh")
    assert (rows["revenue"]["value"], rows["revenue"]["unit"]) == (1406.6, "£m")
    assert {rows[k]["unit"] for k in parts} == {"tCO2e"}
    assert rows["emissions_scope3"]["scope"] == "Scope 3"


def test_electricity_factor_has_exact_source():
    f = load_factors()["uk_electricity"]
    assert (f["value"], f["unit"], f["factor_id"]) == (0.13096, "kgCO2e/kWh", "7_400_4000_5_1")
    assert (f["year"], f["version"], f["row"], f["sheet"]) == (2026, "1.2", 3066, "Factors by Category")
    assert f["source_url"].endswith(".xlsx") and f["retrieved_at"] and "Open Government Licence" in f["license"]


FACTOR = {"value": 0.13096, "unit": "kgCO2e/kWh", "factor_id": "7_400_4000_5_1", "year": 2026}


def test_scenario_matches_verified_arithmetic():
    r = calculate_electricity_scenario(77_485_000, 0.10, 0.25, factor=FACTOR)
    assert r["baseline_tco2e"] == pytest.approx(10_147.4356)
    assert r["saved_tco2e"] == pytest.approx(1_014.74356)
    assert r["scenario_tco2e"] == pytest.approx(10_147.4356 - 1_014.74356)
    assert r["saved_kwh"] == pytest.approx(7_748_500)
    assert r["gross_energy_savings_gbp"] == pytest.approx(1_937_125)
    assert (r["factor_id"], r["factor_year"]) == ("7_400_4000_5_1", 2026)
    assert r["assumptions"] == {"reduction_ratio": 0.10, "tariff_gbp_per_kwh": 0.25}


def test_scenario_zero_and_full_reduction():
    zero = calculate_electricity_scenario(1_000_000, 0.0, 0.25, factor=FACTOR)
    assert zero["scenario_tco2e"] == zero["baseline_tco2e"] and zero["saved_tco2e"] == 0
    full = calculate_electricity_scenario(1_000_000, 1.0, 0.25, factor=FACTOR)
    assert full["scenario_tco2e"] == 0 and full["saved_tco2e"] == full["baseline_tco2e"]
    none = calculate_electricity_scenario(0, 0.5, 0.25, factor=FACTOR)
    assert none["saved_tco2e"] == none["saved_kwh"] == none["gross_energy_savings_gbp"] == 0


@pytest.mark.parametrize(("kwh", "ratio", "tariff", "factor", "field"), [
    (-1, 0.1, 0.25, FACTOR, "electricity_kwh"),
    (math.nan, 0.1, 0.25, FACTOR, "electricity_kwh"),
    (1, 0.1, math.inf, FACTOR, "tariff_gbp_per_kwh"),
    (1, 0.1, -0.01, FACTOR, "tariff_gbp_per_kwh"),
    (1, -0.01, 0.25, FACTOR, "reduction_ratio"),
    (1, 1.01, 0.25, FACTOR, "reduction_ratio"),
    (1, 0.1, 0.25, {**FACTOR, "value": None}, "factor value"),
    (1, 0.1, 0.25, {**FACTOR, "unit": "gCO2/kWh"}, "factor unit"),
])
def test_scenario_rejects_invalid_inputs(kwh, ratio, tariff, factor, field):
    with pytest.raises(ValueError, match=field):
        calculate_electricity_scenario(kwh, ratio, tariff, factor=factor)


# ---- GB grid forecast and one-hour scheduling (Task 3) -------------------- #

import datetime as dt  # noqa: E402
import urllib.request  # noqa: E402

import pandas as pd  # noqa: E402

from src.data_sources.public_data import (  # noqa: E402
    GridFetchError, choose_one_hour_window, fetch_grid_forecast, load_grid_snapshot, normalize_grid_snapshot,
)

T0 = dt.datetime(2026, 10, 3, 0, 0, tzinfo=dt.timezone.utc)
HALF = dt.timedelta(minutes=30)


def _slots(forecasts, starts=None):
    starts = starts or [T0 + i * HALF for i in range(len(forecasts))]
    return pd.DataFrame({"from": pd.to_datetime(starts, utc=True), "to": pd.to_datetime([s + HALF for s in starts], utc=True),
                         "forecast_gco2_per_kwh": [math.nan if f is None else float(f) for f in forecasts],
                         "actual_gco2_per_kwh": [math.nan] * len(forecasts)})


def test_cleaner_window_halves_forecast_co2():
    r = choose_one_hour_window(_slots([200, 200, 100, 100]), energy_kwh=100, as_of=T0)
    assert (r["baseline_kgco2"], r["best_kgco2"], r["saved_kgco2"]) == pytest.approx((20.0, 10.0, 10.0))
    assert (r["baseline_start"], r["best_start"], r["best_end"]) == (T0, T0 + 2 * HALF, T0 + 4 * HALF)
    assert r["energy_kwh"] == 100


def test_constant_forecast_ties_choose_earliest_window():
    r = choose_one_hour_window(_slots([150] * 4), energy_kwh=100, as_of=T0)
    assert r["best_start"] == r["baseline_start"] == T0 and r["saved_kgco2"] == 0


def test_missing_forecast_excludes_its_pairs():
    r = choose_one_hour_window(_slots([50, None, 300, 300]), energy_kwh=100, as_of=T0)
    assert r["baseline_start"] == r["best_start"] == T0 + 2 * HALF


@pytest.mark.parametrize("frame", [
    _slots([100, 100], starts=[T0, T0 + 2 * HALF]),                     # gap
    _slots([100, 100], starts=[T0, T0 + dt.timedelta(minutes=15)]),     # overlap
    _slots([100, 100, 100], starts=[T0, T0, T0 + HALF]),                # duplicate timestamps
    _slots([100]),                                                      # fewer than two slots
    _slots([None, 100]),
])
def test_invalid_intervals_cannot_form_a_window(frame):
    assert choose_one_hour_window(frame, energy_kwh=100, as_of=T0) is None


def test_past_windows_are_never_offered():
    assert choose_one_hour_window(_slots([100, 100]), energy_kwh=100, as_of=T0 + HALF / 2) is None
    assert choose_one_hour_window(_slots([100] * 4), energy_kwh=100, as_of=T0 + 9 * HALF) is None


@pytest.mark.parametrize("energy", [-1, math.nan, math.inf])
def test_schedule_rejects_invalid_energy(energy):
    with pytest.raises(ValueError, match="energy_kwh"):
        choose_one_hour_window(_slots([100, 100]), energy_kwh=energy, as_of=T0)


def test_schedule_requires_timezone_aware_as_of():
    with pytest.raises(ValueError, match="timezone-aware"):
        choose_one_hour_window(_slots([100, 100]), energy_kwh=100, as_of=T0.replace(tzinfo=None))


def test_recorded_snapshot_normalizes_and_keeps_null_actuals():
    snap = load_grid_snapshot()
    assert snap["data_kind"] == "recorded_example" and snap["fetched_at"] and snap["source_url"].endswith("/fw48h")
    df = normalize_grid_snapshot(snap)
    assert len(df) == 96 and str(df["from"].dt.tz) == "UTC"
    assert df["forecast_gco2_per_kwh"].notna().all() and (df["forecast_gco2_per_kwh"] >= 0).all()
    assert df["actual_gco2_per_kwh"].isna().all()


def test_normalize_rejects_bad_shape_and_negative_forecasts():
    with pytest.raises(ValueError):
        normalize_grid_snapshot({"response": {"nope": []}})
    bad = {"response": {"data": [{"from": "2026-10-03T00:00Z", "to": "2026-10-03T00:30Z",
                                  "intensity": {"forecast": -5, "actual": None}}]}}
    with pytest.raises(ValueError, match="forecast"):
        normalize_grid_snapshot(bad)


def test_fetch_timeout_raises_controlled_error(monkeypatch):
    def timeout(*args, **kwargs):
        raise TimeoutError("timed out")
    monkeypatch.setattr(urllib.request, "urlopen", timeout)
    with pytest.raises(GridFetchError, match="Carbon Intensity API"):
        fetch_grid_forecast(T0)
    with pytest.raises(ValueError, match="timezone-aware"):
        fetch_grid_forecast(T0.replace(tzinfo=None))
