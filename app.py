"""CarbonOpt — Streamlit entry point.

Run from the repository root:  python -m streamlit run app.py

The demo company (config/integration.json) or an uploaded monthly CSV feeds forecasting,
simulation, optimization, risk and benchmarking. Computational services never fall back
to test doubles.
"""

from __future__ import annotations

import hashlib
import json
import logging

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from src.contracts.errors import CarbonOptError
from src.contracts.types import AnalysisRequest, ConstraintConfig, OptimizerConfig, RiskConfig
from src.dashboard import components, data_panel
from src.dashboard.chat_ui import render_chat
from src.dashboard.presentation import short_gbp
from src.dashboard.state import DashboardState
from src.dashboard.theme import apply_theme
from src.integration.services import Services, create_dataset_services, create_services

logger = logging.getLogger(__name__)
TOLERANCE_LABELS = {"conservative": "Cautious", "balanced": "Balanced", "aggressive": "Bold"}


@st.cache_resource(show_spinner=False, max_entries=6)
def _demo_services(model: str | None) -> Services:
    # Providers are stateless and hold no session or credential data, so one
    # instance per configuration and forecasting model can be shared across sessions.
    return create_services(model=model)


@st.cache_resource(show_spinner=False, max_entries=8)
def _upload_services(data: bytes, mapping: str, name: str, model: str | None) -> Services:
    return create_dataset_services(data_panel.read_table(data), json.loads(mapping), name=name,
                                   sha256=hashlib.sha256(data).hexdigest(), model=model)


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


def sidebar_inputs(services: Services) -> tuple[DeltaGenerator, DeltaGenerator, AnalysisRequest]:
    caps = services.capabilities
    company = services.forecast.company_id
    apply_defaults(company, services.forecast.config.dashboard_defaults)
    sb = st.sidebar
    sb.markdown("### Goals")
    horizon = caps.supported_horizons[0]
    sb.caption(f"Planning over the next {horizon} months.")
    budget = sb.number_input("Budget for new actions (£)", min_value=0.0, step=10_000.0, format="%.0f",
                             key="co_widget_budget",
                             help="Up-front investment plus extra running costs over the period. Savings are not deducted.")
    budget_note = sb.empty()  # filled once the forecast is known
    min_profit = sb.number_input("Lowest acceptable operating profit (£)", step=10_000.0, format="%.0f",
                                 key="co_widget_profit", help="Total over the period, not per year. May be negative.")
    profit_note = sb.empty()
    target_pct = sb.slider("Cut emissions by at least (%)", min_value=0, max_value=100, step=1, key="co_widget_target",
                           help="Compared with the forecast without new actions.")
    with sb.expander("Search depth"):
        st.caption("Trying more mixes finds slightly better plans and takes longer.")
        max_evals = int(st.number_input("Mixes to try", min_value=16, max_value=10_000, step=64, key="co_widget_evals"))

    sb.markdown("### Also check")
    risk_on = sb.checkbox("Uncertainty", key="co_widget_risk", disabled=not caps.risk_available,
                          help="How often each plan still meets your goals when costs and effects vary "
                               "(Monte Carlo simulation).")
    tolerance, trials = "balanced", 1000
    if risk_on and caps.risk_available:
        tolerance = sb.radio("Risk appetite", tuple(TOLERANCE_LABELS), index=1, key="co_widget_tolerance",
                             horizontal=True, format_func=TOLERANCE_LABELS.get)
        with sb.expander("Uncertainty detail"):
            trials = int(st.number_input("Trials per plan", min_value=100, max_value=5000, step=100, key="co_widget_trials"))
    shap_on = sb.checkbox("Forecast drivers", key="co_widget_shap") if caps.shap_available_targets else False
    bench_on = sb.checkbox("Peers", key="co_widget_bench", disabled=not caps.benchmark_available)

    return budget_note, profit_note, AnalysisRequest(
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


def goal_limits(state: DashboardState, services: Services, request: AnalysisRequest, budget_note: DeltaGenerator,
                profit_note: DeltaGenerator) -> None:
    """What the budget and profit floor accept, sized to this company's forecast."""
    c = request.constraints
    if state.baseline is None:
        budget_note.caption(short_gbp(c.budget_gbp))
        profit_note.caption(short_gbp(c.min_total_profit_gbp))
        return
    budget_note.caption(f"{short_gbp(c.budget_gbp)} · £0 or more; above "
                        f"{short_gbp(components.full_mix_cost(state, services))} makes no difference (every action "
                        "at full take-up).")
    profit_note.caption(f"{short_gbp(c.min_total_profit_gbp)} · Any amount, can be negative; "
                        f"{short_gbp(state.baseline.totals['operating_profit_gbp'])} without new actions.")


def main() -> None:
    st.set_page_config(page_title="CarbonOpt", page_icon=":material/eco:", layout="wide")
    dark = _is_dark()
    apply_theme(dark)

    source = data_panel.source_selector()
    dataset = data_panel.confirmed() if source == data_panel.OWN else None
    if source == data_panel.OWN and dataset is None:
        components.header(None, None)
        data_panel.upload_step()
        return
    if dataset is not None:
        data_panel.sidebar_summary(dataset)

    model = st.session_state.get("co_widget_forecast_model")
    model = None if model in (None, "auto") else model
    try:
        with st.spinner("Loading the company data…"):
            services = (_demo_services(model) if dataset is None
                        else _upload_services(dataset["bytes"], data_panel.mapping_json(dataset), dataset["name"], model))
    except (CarbonOptError, ImportError, OSError, ValueError):
        logger.exception("Cannot initialize company analysis services")
        st.error("Company analysis could not be loaded. Please contact the application administrator.")
        st.stop()

    state = DashboardState(st.session_state)
    state.sync_services(services)
    budget_note, profit_note, request = sidebar_inputs(services)
    with st.spinner("Fitting the forecast. The first time for new data or a new model takes a few seconds…"):
        state.ensure_baseline(request, services)
    state.sync_inputs(request, services)
    goal_limits(state, services, request, budget_note, profit_note)
    if st.sidebar.button("Find plans", type="primary", width="stretch", disabled=state.baseline is None,
                         icon=":material/search:"):
        with st.spinner("Searching for plans…"):
            state.run_optimize(request, services)

    components.header(services, state)
    components.baseline_section(state, services, dark)
    if state.baseline is not None:
        components.plans_section(state, services, request, dark)
        components.whatif_section(state, services, request, dark)
        components.confidence_section(state, services, request, dark)
        components.timing_section(state, dark)
        components.assumptions_section(services.assumptions, state)
    render_chat(state, services, request, dark=dark)


main()
