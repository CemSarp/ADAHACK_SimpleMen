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
LIVE_KEY = KEY + "grid_live"
DEFAULT_TARIFF_P = 25.0  # p/kWh; illustrative, not a Wincanton tariff
CCF_URL = "https://github.com/cloud-carbon-footprint/cloud-carbon-footprint"
CCF_METHOD_URL = "https://www.cloudcarbonfootprint.org/docs/methodology/"
CARBON_INTENSITY_DOCS = "https://carbon-intensity.github.io/api-definitions/"
GRID_TASK_KWH = 100.0  # one-hour task at a constant 100 kW
GRID_MAX_AGE = dt.timedelta(minutes=30)  # same as the fetch cache TTL
LONDON = "Europe/London"
SCOPES_EXPLAINED = (
    "- **Scope 1:** fuel the company burns itself, e.g. diesel in its trucks.\n"
    "- **Scope 2:** electricity it buys (the power station burns the fuel; the company uses the power).\n"
    "- **Scope 3:** its wider supply chain, e.g. suppliers, subcontractors and business travel.\n\n"
    "Scope 1 + 2 is what the company directly controls; Scope 3 is reported separately."
)


def render_grounding_panel() -> None:
    with st.expander("Real data and sources", icon=":material/fact_check:"):
        try:
            ref, factor = load_company_reference(), load_factors()["uk_electricity"]
        except (OSError, ValueError) as exc:  # a broken snapshot must not take the dashboard down
            st.error(f"Public reference data unavailable: {exc}")
            return
        st.caption("Real, public numbers for context. They never change the optimizer below, which analyses a "
                   "synthetic demo company.")
        company, calculator, grid, sources = st.tabs([
            ":material/apartment: Real company", ":material/bolt: Savings calculator",
            ":material/schedule: Cleanest hour", ":material/link: Sources",
        ])
        with company:
            _reference_card(ref)
        with calculator:
            _calculator(ref, factor)
        with grid:
            _grid()
        with sources:
            _sources(ref, factor)


def _reference_card(ref: dict) -> None:
    rows = ref["values"]
    st.markdown(f"**{ref['company']}**, a UK logistics company, as published in its "
                f"[{ref['title']}]({ref['source_url']}).")
    with st.container(horizontal=True):
        st.metric("Revenue", f"£{rows['revenue']['value']:,.1f}m", border=True)
        st.metric("Emissions, Scope 1 + 2 (tCO2e)", f"{rows['emissions_scope1_and_2_total']['value']:,}", border=True)
        st.metric("Electricity, non-transport (MWh)", f"{rows['electricity_non_transport']['value']:,}", border=True)
    with st.expander("What are scopes?", icon=":material/help:"):
        st.markdown(SCOPES_EXPLAINED)
    st.caption(f"**Historical public reference; separate from the synthetic optimization company.** Reported period "
               f"{ref['period_start']} to {ref['period_end']} · retrieved {ref['retrieved_at']}.")
    with st.expander("All reported figures"):
        st.dataframe(pd.DataFrame([
            {"Item": r["label"], "Value": f"{r['value']:,}", "Unit": r["unit"], "Scope": r["scope"]}
            for key, r in rows.items() if key != "revenue"
        ]), hide_index=True, width="stretch")
        pages = "; ".join(sorted({r["page"] for r in rows.values()}))
        st.caption(f"Report pages: {pages}. {ref['boundary_note']}")


def _calculator(ref: dict, factor: dict) -> None:
    reported_kwh = float(ref["values"]["electricity_non_transport"]["value"]) * 1000.0
    st.markdown("**What if this company used less electricity?**")
    pct = st.slider("Cut electricity use by (%)", 0, 100, 10, key=KEY + "reduction_pct",
                    help="An assumption, not a claim that Wincanton can achieve it.")
    with st.expander("Change assumptions"):
        c1, c2 = st.columns(2)
        kwh = c1.number_input("Electricity (kWh/year)", min_value=0.0, value=reported_kwh, step=1_000_000.0,
                              format="%.0f", key=KEY + "kwh",
                              help="Defaults to reported FY2024 non-transport electricity (77,485 MWh).")
        # Pence, as UK tariffs are quoted; also avoids "0,250" in comma-decimal browser locales.
        tariff_p = c2.number_input("Tariff (p/kWh, illustrative)", min_value=0.0, value=DEFAULT_TARIFF_P,
                                   step=0.5, format="%.1f", key=KEY + "tariff_p")
    if kwh != reported_kwh:
        st.caption("Custom activity: user-entered, not a reported company value.")
    try:
        r = calculate_electricity_scenario(kwh, pct / 100.0, tariff_p / 100.0, factor=factor)
    except ValueError as exc:
        st.error(str(exc))
        return
    with st.container(horizontal=True):  # wraps instead of truncating on narrow screens
        st.metric("CO₂e saved per year (tCO2e)", f"{r['saved_tco2e']:,.2f}", border=True)
        st.metric("Energy-cost saving per year (£)", f"{r['gross_energy_savings_gbp']:,.0f}", border=True)
        st.metric("Emissions after the cut (tCO2e)", f"{r['scenario_tco2e']:,.0f}", border=True)
    st.caption("2026-factor scenario using FY2024 activity. The cost saving is gross, before any project costs.")
    with st.expander("How this is calculated"):
        st.caption(
            f"Modelled baseline {r['baseline_tco2e']:,.2f} → scenario {r['scenario_tco2e']:,.2f} tCO2e. "
            f"tCO2e = kWh × (1 − reduction) × {factor['value']} kgCO2e/kWh ÷ 1,000. Official factor: GOV.UK "
            f"{factor['year']} v{factor['version']}, factor ID `{factor['factor_id']}` ({factor['sheet']}, row "
            f"{factor['row']}). Shown as gross energy-cost savings before capex/opex — not profit. This is a "
            "2026-factor sensitivity scenario using FY2024 activity: neither a reconstruction of the FY2024 Scope 2 "
            "disclosure nor a 2026 forecast. The UK factor is a scenario proxy for group activity whose exclusively "
            "UK boundary is unverified."
        )


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_grid_forecast(slot_start: dt.datetime) -> dict:
    return fetch_grid_forecast(slot_start)  # failures raise and are not cached


def _london(ts: pd.Timestamp, fmt: str = "%d %b %H:%M %Z") -> str:
    return pd.Timestamp(ts).tz_convert(LONDON).strftime(fmt)


def _grid() -> None:
    st.markdown(f"**When is the GB grid cleanest?** The best time to run a one-hour, {GRID_TASK_KWH:,.0f} kWh job.")
    now = dt.datetime.now(dt.timezone.utc)
    row = st.container(horizontal=True, vertical_alignment="center")
    if row.button("Refresh grid forecast", key=KEY + "grid_refresh", icon=":material/refresh:"):
        try:  # no network call happens unless this button is pressed
            st.session_state[LIVE_KEY] = _cached_grid_forecast(
                now.replace(minute=now.minute // 30 * 30, second=0, microsecond=0))
        except GridFetchError as exc:
            st.session_state.pop(LIVE_KEY, None)  # never keep showing an older response as live
            st.error(f"Grid refresh failed; showing the saved example instead. {exc}")
    live = st.session_state.get(LIVE_KEY)
    if live and now - pd.Timestamp(live["fetched_at"]).to_pydatetime() > GRID_MAX_AGE:
        st.session_state.pop(LIVE_KEY, None)
        live = None
        st.caption("The live forecast was over 30 minutes old, so the saved example is shown. Refresh for current data.")
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
    covers = f"covers {_london(df['from'].iloc[0])} to {_london(df['to'].iloc[-1])}"
    if live:
        as_of = now  # only future windows
        row.badge("Live forecast", icon=":material/sensors:", color="green")
        status = f"Fetched {fetched:%Y-%m-%d %H:%M} UTC · {covers}."
    else:
        as_of = df["from"].iloc[0].to_pydatetime()  # replays the algorithm over the recorded period only
        row.badge("Recorded example", icon=":material/history:", color="gray")
        status = (f"Saved forecast, retrieved {fetched:%Y-%m-%d %H:%M} UTC · {covers}. "
                  "Historical replay, not an upcoming recommendation.")

    window = choose_one_hour_window(df, energy_kwh=GRID_TASK_KWH, as_of=as_of)
    if window is None:
        st.info("No complete future one-hour window in this forecast.")
    else:
        base, best = window["baseline_kgco2"], window["best_kgco2"]
        less = f" ({(base - best) / base:.0%} less)" if base > 0 else ""
        text = (f"**{_london(window['best_start'], '%d %b %H:%M')}–{_london(window['best_end'], '%H:%M %Z')}**: "
                f"{best:,.1f} kgCO2 instead of {base:,.1f} kgCO2 if started at "
                f"{_london(window['baseline_start'], '%H:%M %Z')}{less}.")
        if live:
            st.success(f"Best upcoming hour {text}", icon=":material/eco:")
        else:
            st.info(f"Cleanest hour in the saved forecast {text}", icon=":material/history:")

    local = df["from"].dt.tz_convert(LONDON).dt.tz_localize(None)
    fig = go.Figure(go.Scatter(x=local, y=df["forecast_gco2_per_kwh"], mode="lines", line_shape="hv",
                               name="Forecast"))
    has_actual = bool(df["actual_gco2_per_kwh"].notna().any())  # plotly rejects numpy bools
    if has_actual:
        fig.add_trace(go.Scatter(x=local, y=df["actual_gco2_per_kwh"], mode="lines", line_shape="hv", name="Actual"))
    if window is not None:
        fig.add_vrect(x0=pd.Timestamp(window["best_start"]).tz_convert(LONDON).tz_localize(None),
                      x1=pd.Timestamp(window["best_end"]).tz_convert(LONDON).tz_localize(None),
                      fillcolor="green", opacity=0.15, line_width=0)
    fig.update_layout(height=240, margin=dict(l=10, r=10, t=30 if has_actual else 10, b=10), yaxis_title="gCO2/kWh",
                      showlegend=has_actual, legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom"))
    st.plotly_chart(fig, width="stretch", alt="GB grid carbon intensity forecast, cleanest hour highlighted")
    st.caption(f"{status} Times are UK time. GB-average forecast generation CO2 (kgCO2), not lifecycle CO2e or a "
               "depot-specific figure; never added to corporate totals. Source: Carbon Intensity API "
               f"(NESO, CC BY 4.0) · [request]({snap['source_url']}).")


def _sources(ref: dict, factor: dict) -> None:
    st.markdown(
        f"- **Company figures:** [{ref['title']}]({ref['source_url']}) (reported historical)\n"
        f"- **Electricity factor:** [GOV.UK conversion factors {factor['year']}]({factor['publication_url']}) · "
        f"[flat workbook v{factor['version']}]({factor['source_url']})\n"
        f"- **Grid forecast:** [Carbon Intensity API]({CARBON_INTENSITY_DOCS}) (NESO, CC BY 4.0), used for "
        "scheduling only\n"
        f"- **Cloud:** [Cloud Carbon Footprint]({CCF_URL}) ([methodology]({CCF_METHOD_URL})) — "
        "**planned; current cloud estimates illustrative**"
    )
    st.caption(f"{factor['license']} The six-action optimizer on this page still analyses a synthetic demo "
               "company with illustrative costs; it is not grounded in Wincanton records.")
