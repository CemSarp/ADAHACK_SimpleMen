"""CarbonOpt AI — Streamlit entry point.

Run from the repository root:  python -m streamlit run app.py

Provider mode defaults to `mock` (development doubles, visibly labelled).
`CARBONOPT_PROVIDER_MODE=real` runs the integrated application: WS1 forecast from the
configured company CSV (config/integration.json), WS2 simulation/optimization, WS3
risk and benchmark, all real providers, with the input data labelled by its own
provenance (synthetic for data/synthetic_data.csv). `hybrid` mixes providers
explicitly (src/integration/services.py HYBRID_PRESETS). Real mode never falls
back to mock output.
"""

from __future__ import annotations

import os

import streamlit as st

from src.contracts.errors import ProviderConfigurationError
from src.contracts.types import AnalysisRequest, ConstraintConfig, OptimizerConfig, RiskConfig
from src.dashboard import components
from src.dashboard.chat_ui import render_chat
from src.dashboard.state import DashboardState
from src.integration.services import (
    DEFAULT_HYBRID_PRESET,
    HYBRID_PRESETS,
    OPTIONAL_SLOTS,
    P0_SLOTS,
    Services,
    create_services,
    preset_overrides,
)

MODES = ("mock", "real", "hybrid")
DEFAULT_COMPANY_ID = os.environ.get("CARBONOPT_COMPANY_ID", "demo-company")
DEMO_DEFAULTS = {"budget_gbp": 500_000.0, "min_total_profit_gbp": 1_000_000.0, "min_co2_reduction_ratio": 0.2,
                 "optimizer_max_evaluations": 2048, "risk_trials": 1000}
CUSTOM_PRESET = "custom"
PRESET_LABELS = {
    "fixture-forecast-real-ws2": "Fixture forecast + real WS2 (integration)",
    CUSTOM_PRESET: "Custom: choose each provider",
}


@st.cache_resource(show_spinner=False)
def _services(mode: str, overrides: tuple[tuple[str, str], ...]) -> Services:
    # Providers are stateless and hold no session or credential data, so one
    # instance per configuration can be shared across sessions.
    return create_services(mode=mode, provider_overrides=dict(overrides) or None)


def company_and_defaults(services: Services) -> tuple[str, dict]:
    """Company ID comes from the bound forecast provider; constraint defaults from
    config/integration.json for the real CSV company, demo defaults otherwise."""
    company = getattr(services.forecast, "company_id", None) or DEFAULT_COMPANY_ID
    if services.providers["forecast"].kind == "real":
        return company, {**DEMO_DEFAULTS, **services.forecast.config.dashboard_defaults}
    return company, dict(DEMO_DEFAULTS)


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


def sidebar_providers() -> tuple[str, tuple[tuple[str, str], ...]]:
    env_mode = os.environ.get("CARBONOPT_PROVIDER_MODE", "mock")
    st.sidebar.markdown("### Providers")
    mode = st.sidebar.selectbox(
        "Provider mode", MODES, index=MODES.index(env_mode) if env_mode in MODES else 0, key="co_widget_mode",
        help="mock: development doubles. real: WS1–WS3 implementations only. hybrid: a named mix, by default the "
             "labelled fixture forecast with the real WS2 simulator and optimizer.",
    )
    overrides: list[tuple[str, str]] = []
    if mode == "hybrid":
        presets = [*HYBRID_PRESETS, CUSTOM_PRESET]
        env_preset = os.environ.get("CARBONOPT_HYBRID_PRESET", DEFAULT_HYBRID_PRESET)
        preset = st.sidebar.selectbox(
            "Hybrid configuration", presets, index=presets.index(env_preset) if env_preset in presets else 0,
            format_func=lambda name: PRESET_LABELS.get(name, name), key="co_widget_preset",
        )
        if preset != CUSTOM_PRESET:
            return mode, tuple(sorted(preset_overrides(preset).items()))
        for slot in P0_SLOTS + OPTIONAL_SLOTS[:-1]:
            choices = ["mock", "real"] + (["disabled"] if slot in OPTIONAL_SLOTS else [])
            overrides.append((slot, st.sidebar.selectbox(f"{slot} provider", choices, key=f"co_widget_hybrid_{slot}")))
    return mode, tuple(overrides)


def sidebar_inputs(services: Services) -> AnalysisRequest:
    caps = services.capabilities
    company, defaults = company_and_defaults(services)
    apply_defaults(company, defaults)
    st.sidebar.markdown("### Analysis inputs")
    horizon = st.sidebar.selectbox(
        "Forecast horizon (months)", caps.supported_horizons, key="co_widget_horizon",
        help="Only horizons advertised by the forecast provider are offered (P0: 12 months).",
    )
    budget = st.sidebar.number_input(
        "Implementation budget (£, horizon total)", min_value=0.0, step=10_000.0, format="%.0f",
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
    with st.sidebar.expander("Optimizer settings"):
        seed = int(st.number_input("Seed", min_value=0, value=42, step=1, key="co_widget_seed"))
        max_evals = int(st.number_input("Max evaluations", min_value=16, max_value=10_000, step=64,
                                        key="co_widget_evals"))

    st.sidebar.markdown("### Optional (P1)")
    risk_on = st.sidebar.checkbox("Risk (Monte Carlo)", key="co_widget_risk", disabled=not caps.risk_available,
                                  help=None if caps.risk_available else services.unavailable.get("risk"))
    tolerance = "balanced"
    trials = 1000
    if risk_on and caps.risk_available:
        tolerance = st.sidebar.radio("Risk tolerance", ("conservative", "balanced", "aggressive"), index=1,
                                     key="co_widget_tolerance", horizontal=True)
        trials = int(st.sidebar.number_input("Trials", min_value=100, max_value=5000, step=100,
                                             key="co_widget_trials"))
    shap_on = st.sidebar.checkbox("Forecast SHAP", key="co_widget_shap", disabled=not caps.shap_available_targets,
                                  help=None if caps.shap_available_targets else services.unavailable.get("shap"))
    bench_on = st.sidebar.checkbox("Benchmark", key="co_widget_bench", disabled=not caps.benchmark_available,
                                   help=None if caps.benchmark_available else services.unavailable.get("benchmark"))

    request = AnalysisRequest(
        company_id=company,
        horizon_months=int(horizon),
        constraints=ConstraintConfig(
            budget_gbp=float(budget), min_total_profit_gbp=float(min_profit), min_co2_reduction_ratio=target_pct / 100.0
        ),
        optimizer_config=OptimizerConfig(seed=seed, max_evaluations=max_evals),
        risk_enabled=bool(risk_on and caps.risk_available),
        risk_config=RiskConfig(n_simulations=trials),
        tolerance=tolerance,
        benchmark_enabled=bool(bench_on and caps.benchmark_available),
        explanation_enabled=bool(shap_on and caps.shap_available_targets),
    )
    return request


def main() -> None:
    st.set_page_config(page_title="CarbonOpt AI", page_icon="🌱", layout="wide")
    st.title("CarbonOpt AI")
    st.caption("Single-company decision support: business-as-usual forecast, intervention what-if, and constrained "
               "emissions/profit trade-offs.")

    mode, overrides = sidebar_providers()
    try:
        services = _services(mode, overrides)
    except ProviderConfigurationError as exc:
        st.error(f"**Provider configuration error.** {exc}", icon="🛑")
        st.info("Real mode needs every P0 provider (WS1 forecast, WS2 simulator and optimizer) and never substitutes a "
                "fixture. Select **hybrid** to mix providers explicitly, or **mock** for development doubles.")
        st.stop()

    state = DashboardState(st.session_state)
    state.sync_services(services)
    request = sidebar_inputs(services)
    with st.spinner("Loading the baseline forecast (the first real run trains WS1 models; later runs reuse them)…"):
        state.ensure_baseline(request, services)
    state.sync_inputs(request, services)
    optimize = st.sidebar.button("Optimize", type="primary", width="stretch", disabled=state.baseline is None)
    if optimize:
        with st.spinner("Optimizing…"):
            state.run_optimize(request, services)

    dark = _is_dark()
    components.provenance_banner(services)
    components.data_provenance_line(state.baseline)
    components.company_context(state, dark)
    if state.baseline is not None:
        components.backtest_panel(state, dark)
        st.divider()
        components.optimization_panel(state, services, request, dark)
        components.selected_strategy_panel(state, services, request)
        st.divider()
        components.whatif_panel(state, services, request)
        components.monthly_panel(state, dark)
        st.divider()
        components.optional_panels(state, services, request, dark)
        st.divider()
        components.assumptions_panel(services.assumptions, services.providers["simulator"].is_mock)
        components.provenance_details(state, services)
    # Reserve room so the floating bubble never covers the Optimize button.
    st.sidebar.html('<div style="height:88px"></div>')
    render_chat(state, services, request, dark=dark)


main()
