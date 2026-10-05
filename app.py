"""CarbonOpt AI — Streamlit entry point.

Run from the repository root:  python -m streamlit run app.py

The configured company CSV feeds forecasting, simulation, optimization, risk
and benchmarking. Computational services never fall back to test doubles.
"""

from __future__ import annotations

import logging

import streamlit as st

from src.contracts.errors import CarbonOptError
from src.contracts.types import AnalysisRequest, ConstraintConfig, OptimizerConfig, RiskConfig
from src.dashboard import components
from src.dashboard.chat_ui import render_chat
from src.dashboard.grounding_panel import render_grounding_panel
from src.dashboard.state import DashboardState
from src.dashboard.theme import apply_theme
from src.integration.services import Services, create_services

logger = logging.getLogger(__name__)


@st.cache_resource(show_spinner=False)
def _services() -> Services:
    # Providers are stateless and hold no session or credential data, so one
    # instance per configuration can be shared across sessions.
    return create_services()


def company_and_defaults(services: Services) -> tuple[str, dict]:
    """Use the same company configuration as the forecast and action services."""
    return services.forecast.company_id, dict(services.forecast.config.dashboard_defaults)


def apply_defaults(company: str, defaults: dict) -> None:
    """Seed widget values once per company (never while the user is editing them)."""
    if st.session_state.get("co_defaults_company") == company:
        return
    st.session_state["co_defaults_company"] = company
    st.session_state["co_widget_budget"] = float(defaults["budget_gbp"])
    st.session_state["co_widget_profit"] = float(defaults["min_total_profit_gbp"])
    st.session_state["co_widget_target"] = int(round(float(defaults["min_co2_reduction_ratio"]) * 100))
    st.session_state["co_widget_evals"] = int(defaults["optimizer_max_evaluations"])
    st.session_state["co_widget_trials"] = int(defaults["risk_trials"])


def _is_dark() -> bool:
    theme = getattr(st.context, "theme", None)
    return getattr(theme, "type", None) == "dark"


def sidebar_inputs(services: Services) -> AnalysisRequest:
    caps = services.capabilities
    company, defaults = company_and_defaults(services)
    apply_defaults(company, defaults)
    st.sidebar.markdown("### Planning goals")
    if len(caps.supported_horizons) == 1:
        horizon = caps.supported_horizons[0]
        st.sidebar.caption(f"Planning period: {horizon} months")
    else:
        horizon = st.sidebar.selectbox("Planning period (months)", caps.supported_horizons, key="co_widget_horizon")
    budget = st.sidebar.number_input(
        "Implementation budget (£)", min_value=0.0, step=10_000.0, format="%.0f",
        key="co_widget_budget", help="Gross outlay over the whole horizon: capex + incremental opex. Savings excluded.",
    )
    min_profit = st.sidebar.number_input(
        "Minimum cumulative operating profit (£)", step=10_000.0, format="%.0f",
        key="co_widget_profit", help="Floor on operating profit summed over the horizon (not annual). May be negative.",
    )
    target_pct = st.sidebar.slider(
        "Minimum CO₂ reduction vs baseline (%)", min_value=0, max_value=100, step=1, key="co_widget_target",
        help="Strategy horizon emissions compared with baseline horizon emissions.",
    )
    with st.sidebar.expander("Search depth"):
        st.caption("A larger search explores more action mixes and takes longer.")
        max_evals = int(st.number_input("Action mixes to evaluate", min_value=16, max_value=10_000, step=64,
                                        key="co_widget_evals"))

    st.sidebar.markdown("### Supporting analysis")
    risk_on = st.sidebar.checkbox("Assess uncertainty", key="co_widget_risk", disabled=not caps.risk_available,
                                  help="Estimate how often a plan meets your goals when action assumptions vary.")
    tolerance = "balanced"
    trials = 1000
    if risk_on and caps.risk_available:
        tolerance = st.sidebar.radio("Risk tolerance", ("conservative", "balanced", "aggressive"), index=1,
                                     key="co_widget_tolerance", horizontal=True)
        with st.sidebar.expander("Uncertainty detail"):
            trials = int(st.number_input("Uncertainty trials", min_value=100, max_value=5000, step=100,
                                         key="co_widget_trials"))
    shap_on = False
    if caps.shap_available_targets:
        shap_on = st.sidebar.checkbox("Explain the forecast", key="co_widget_shap")
    bench_on = st.sidebar.checkbox("Compare with peers", key="co_widget_bench", disabled=not caps.benchmark_available)

    request = AnalysisRequest(
        company_id=company,
        horizon_months=int(horizon),
        constraints=ConstraintConfig(
            budget_gbp=float(budget), min_total_profit_gbp=float(min_profit), min_co2_reduction_ratio=target_pct / 100.0
        ),
        optimizer_config=OptimizerConfig(seed=42, max_evaluations=max_evals),
        risk_enabled=bool(risk_on and caps.risk_available),
        risk_config=RiskConfig(n_simulations=trials),
        tolerance=tolerance,
        benchmark_enabled=bool(bench_on and caps.benchmark_available),
        explanation_enabled=bool(shap_on and caps.shap_available_targets),
    )
    return request


def main() -> None:
    st.set_page_config(page_title="CarbonOpt AI", page_icon="🌱", layout="wide")
    dark = _is_dark()
    apply_theme(dark)
    st.title("CarbonOpt AI")
    st.caption("Plan emissions reductions, compare costs and profit, and choose an action mix that meets your goals.")

    try:
        services = _services()
    except (CarbonOptError, ImportError, OSError, ValueError):
        logger.exception("Cannot initialize company analysis services")
        st.error("Company analysis could not be loaded. Please contact the application administrator.", icon="🛑")
        st.stop()

    state = DashboardState(st.session_state)
    state.sync_services(services)
    baseline_summary = st.sidebar.container()
    request = sidebar_inputs(services)
    with st.spinner("Preparing your forecast. The first analysis may take a few minutes…"):
        state.ensure_baseline(request, services)
    with baseline_summary:
        st.markdown("**Baseline · before new actions**")
        if state.baseline is not None:
            monthly = state.baseline.monthly
            st.caption(f"{monthly['timestamp'].min():%b %Y} – {monthly['timestamp'].max():%b %Y}")
            st.markdown(
                "| Forecast | Total |\n| :--- | ---: |\n"
                f"| Emissions | **{monthly['total_co2e_tco2e'].sum():,.0f} tCO₂e** |\n"
                f"| Revenue | **£{monthly['revenue_gbp'].sum() / 1_000_000:,.2f}m** |\n"
                f"| Profit (EBITDA proxy) | **£{monthly['operating_profit_gbp'].sum() / 1_000_000:,.2f}m** |"
            )
            with st.expander("Data source"):
                st.caption(f"Source: {services.forecast.config.input_csv}. "
                           f"Data type: {state.baseline.data_kind}. Emissions and profit are model forecasts; "
                           "revenue follows the configured seasonal growth projection. "
                           "Profit uses EBITDA as a proxy. EUR values are converted using the configured "
                           "illustrative exchange rate. These figures are separate from the Wincanton reference.")
        else:
            st.caption("Baseline figures are unavailable until the forecast loads.")
    state.sync_inputs(request, services)
    optimize = st.sidebar.button("Optimize", type="primary", width="stretch", disabled=state.baseline is None)
    if optimize:
        with st.spinner("Optimizing…"):
            state.run_optimize(request, services)

    render_grounding_panel()
    components.company_context(state)
    if state.baseline is not None:
        with st.container(border=True):
            components.optimization_panel(state, dark)
            components.selected_strategy_panel(state)
        with st.container(border=True):
            components.whatif_panel(state, services, request)
        with st.container(border=True):
            components.monthly_panel(state, dark)
        with st.container(border=True):
            components.optional_panels(state, services, request, dark)
        with st.container(border=True):
            components.assumptions_panel(services.assumptions)
        components.analysis_download(state)
    # Reserve room so the floating bubble never covers the Optimize button.
    st.sidebar.html('<div style="height:88px"></div>')
    render_chat(state, services, request, dark=dark)


main()
