"""'Real data and sources' section: public reference, official-factor scenario and source links.

Self-contained: it takes no DashboardState, Services or AnalysisRequest, so nothing here can change the
optimizer's inputs. Widget keys use the "co_grounding_" prefix.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data_sources.public_data import (
    GridFetchError,
    calculate_electricity_scenario,
    choose_one_hour_window,
    fetch_grid_forecast,
    load_company_reference,
    load_factors,
    load_grid_snapshot,
    normalize_grid_snapshot,
)

KEY = "co_grounding_"
DEFAULT_TARIFF = 0.25  # illustrative, not a Wincanton tariff
CCF_URL = "https://github.com/cloud-carbon-footprint/cloud-carbon-footprint"
CCF_METHOD_URL = "https://www.cloudcarbonfootprint.org/docs/methodology/"
CARBON_INTENSITY_DOCS = "https://carbon-intensity.github.io/api-definitions/"
GRID_TASK_KWH = 100.0  # one-hour task at a constant 100 kW
LONDON = "Europe/London"


def render_grounding_panel() -> None:
    with st.expander("Real data and sources"):
        try:
            ref, factor = load_company_reference(), load_factors()["uk_electricity"]
        except (OSError, ValueError) as exc:  # a broken snapshot must not take the dashboard down
            st.error(f"Public reference data unavailable: {exc}")
            return
        _reference_card(ref)
        st.divider()
        _calculator(ref, factor)
        st.divider()
        _grid()
        st.divider()
        _sources(ref, factor)


def _reference_card(ref: dict) -> None:
    rows = ref["values"]
    st.markdown(f"#### {ref['company']} — FY2024 public reference")
    st.caption("**Historical public reference; separate from the synthetic optimization company.**")
    st.markdown(
        f"Reported historical · period **{ref['period_start']} to {ref['period_end']}** · revenue "
        f"**£{rows['revenue']['value']:,.1f}m** · source: [{ref['title']}]({ref['source_url']}) "
        f"(retrieved {ref['retrieved_at']})"
    )
    st.dataframe(pd.DataFrame([
        {"Item": r["label"], "Scope": r["scope"], "Value": f"{r['value']:,}", "Unit": r["unit"], "Page": r["page"]}
        for key, r in rows.items() if key != "revenue"
    ]), hide_index=True, width="stretch")
    st.caption(ref["boundary_note"])


def _calculator(ref: dict, factor: dict) -> None:
    reported_kwh = float(ref["values"]["electricity_non_transport"]["value"]) * 1000.0
    st.markdown("#### Electricity-efficiency scenario")
    c1, c2, c3 = st.columns(3)
    kwh = c1.number_input("Electricity (kWh/year)", min_value=0.0, value=reported_kwh, step=1_000_000.0,
                          format="%.0f", key=KEY + "kwh",
                          help="Defaults to reported FY2024 non-transport electricity (77,485 MWh).")
    pct = c2.slider("Consumption reduction (%)", 0, 100, 10, key=KEY + "reduction_pct",
                    help="Assumption. No claim that Wincanton can achieve it.")
    tariff = c3.number_input("Tariff (£/kWh, illustrative)", min_value=0.0, value=DEFAULT_TARIFF, step=0.01,
                             format="%.3f", key=KEY + "tariff")
    if kwh != reported_kwh:
        st.caption("Custom activity: user-entered, not a reported company value.")
    try:
        r = calculate_electricity_scenario(kwh, pct / 100.0, tariff, factor=factor)
    except ValueError as exc:
        st.error(str(exc))
        return
    m1, m2, m3 = st.columns(3)
    m1.metric("Electricity saving (2026-factor scenario using FY2024 activity)", f"{r['saved_tco2e']:,.2f} tCO2e")
    m2.metric("Modelled baseline → scenario", f"{r['baseline_tco2e']:,.0f} → {r['scenario_tco2e']:,.0f} tCO2e")
    m3.metric("Gross energy-cost saving", f"£{r['gross_energy_savings_gbp']:,.0f}")
    st.caption(
        f"tCO2e = kWh × (1 − reduction) × {factor['value']} kgCO2e/kWh ÷ 1,000. Official factor: GOV.UK {factor['year']} "
        f"v{factor['version']}, factor ID `{factor['factor_id']}` ({factor['sheet']}, row {factor['row']}). "
        "Shown as gross energy-cost savings before capex/opex — not profit. This is a 2026-factor sensitivity "
        "scenario using FY2024 activity: neither a reconstruction of the FY2024 Scope 2 disclosure nor a 2026 "
        "forecast. The UK factor is a scenario proxy for group activity whose exclusively UK boundary is unverified."
    )


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_grid_forecast(slot_start: dt.datetime) -> dict:
    return fetch_grid_forecast(slot_start)  # failures raise and are not cached


def _london(ts: pd.Timestamp) -> str:
    return ts.tz_convert(LONDON).strftime("%d %b %H:%M %Z")


def _grid() -> None:
    st.markdown("#### GB grid forecast — scheduling illustration")
    now = dt.datetime.now(dt.timezone.utc)
    if st.button("Refresh grid forecast", key=KEY + "grid_refresh"):
        try:  # no network call happens unless this button is pressed
            st.session_state[KEY + "grid_live"] = _cached_grid_forecast(
                now.replace(minute=now.minute // 30 * 30, second=0, microsecond=0))
        except GridFetchError as exc:
            st.error(f"Grid refresh failed; showing the recorded example instead. {exc}")
    live = st.session_state.get(KEY + "grid_live")
    try:
        snap = live or load_grid_snapshot()
        df = normalize_grid_snapshot(snap)
    except (OSError, ValueError) as exc:
        st.error(f"Grid forecast unavailable: {exc}")
        return
    if df.empty:
        st.info("The grid forecast contains no intervals.")
        return
    fetched = pd.Timestamp(snap["fetched_at"]).tz_convert("UTC")
    period = f"forecast period {_london(df['from'].iloc[0])} to {_london(df['to'].iloc[-1])}"
    if live:
        as_of = now  # only future windows
        st.markdown(f"**Live forecast** · fetched {fetched:%Y-%m-%d %H:%M} UTC · {period} · "
                    f"[request]({snap['source_url']})")
    else:
        as_of = df["from"].iloc[0].to_pydatetime()  # replays the algorithm over the recorded period only
        st.markdown(f"**Recorded example** · retrieved {fetched:%Y-%m-%d %H:%M} UTC · {period} · "
                    f"[request]({snap['source_url']}) — historical replay, not an upcoming recommendation.")
    window = choose_one_hour_window(df, energy_kwh=GRID_TASK_KWH, as_of=as_of)
    local = df["from"].dt.tz_convert(LONDON).dt.tz_localize(None)
    fig = go.Figure(go.Scatter(x=local, y=df["forecast_gco2_per_kwh"], mode="lines", line_shape="hv",
                               name="Forecast gCO2/kWh"))
    if df["actual_gco2_per_kwh"].notna().any():
        fig.add_trace(go.Scatter(x=local, y=df["actual_gco2_per_kwh"], mode="lines", line_shape="hv",
                                 name="Actual gCO2/kWh"))
    if window is not None:
        fig.add_vrect(x0=pd.Timestamp(window["best_start"]).tz_convert(LONDON).tz_localize(None),
                      x1=pd.Timestamp(window["best_end"]).tz_convert(LONDON).tz_localize(None),
                      fillcolor="green", opacity=0.15, line_width=0)
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Europe/London time",
                      yaxis_title="gCO2/kWh (GB average)", legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")
    if window is None:
        st.info("No complete future one-hour window in this forecast.")
        return
    title = "Recommended upcoming window" if live else "Lowest-forecast window in the recorded period"
    st.markdown(
        f"{title}: **{_london(pd.Timestamp(window['best_start']))}–{_london(pd.Timestamp(window['best_end']))}** "
        f"→ {window['best_kgco2']:,.1f} kgCO2 vs {window['baseline_kgco2']:,.1f} kgCO2 starting at "
        f"{_london(pd.Timestamp(window['baseline_start']))} (difference {window['saved_kgco2']:,.1f} kgCO2)."
    )
    st.caption(f"A one-hour, constant-power task using {GRID_TASK_KWH:,.0f} kWh (50 kWh per half hour). Forecast "
               "GB-average generation CO2 (kgCO2), not lifecycle CO2e, not depot-specific and not guaranteed marginal "
               "avoided emissions; never annualized or added to corporate totals. Source: Carbon Intensity API "
               "(NESO, CC BY 4.0).")


def _sources(ref: dict, factor: dict) -> None:
    st.markdown("#### Sources")
    st.markdown(
        f"- Company reference: [{ref['title']}]({ref['source_url']}) (reported historical)\n"
        f"- Official factor: [GOV.UK conversion factors {factor['year']}]({factor['publication_url']}) · "
        f"[flat workbook v{factor['version']}]({factor['source_url']}). {factor['license']}\n"
        f"- GB grid forecast: [Carbon Intensity API]({CARBON_INTENSITY_DOCS}) (NESO, CC BY 4.0) — "
        "electricity-generation CO2 for scheduling only, never added to corporate totals.\n"
        f"- Cloud: [Cloud Carbon Footprint]({CCF_URL}) ([methodology]({CCF_METHOD_URL})) — "
        "**planned; current cloud estimates illustrative**.\n"
        "- The six-action optimizer on this page still analyses `demo-company` with synthetic inputs and illustrative "
        "costs; it is not grounded in Wincanton records."
    )
