"""Floating assistant: circular bottom-left bubble and an expandable panel.

Built from documented Streamlit pieces: st.container(key=...) (Streamlit adds
the CSS class `st-key-<key>`), st.button, st.chat_message, st.chat_input and
st.html for a small stylesheet. If the stylesheet is not applied the same widgets
render inline and stay usable. All model requests and tool execution happen in
Python on the server; the browser never receives credentials or calls tools.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

import streamlit as st

from src.contracts.errors import CarbonOptError
from src.contracts.types import ActionConfig, AnalysisRequest
from src.integration.services import Services
from src.llm.config import ChatbotConfig, ChatConfigurationError
from src.llm.context import AnalysisContext
from src.llm.providers import ChatModelProvider, create_chat_provider
from src.llm.summaries import gbp, pct, tonnes

from .chat_state import SUGGESTIONS, ChatState
from .state import DashboardState

LAUNCHER_KEY = "cc_launcher"
PANEL_KEY = "cc_panel"


def _css(dark: bool) -> str:
    bg, fg, border = ("#1a1a19", "#ffffff", "#383835") if dark else ("#fcfcfb", "#0b0b0b", "#c3c2b7")
    return f"""<style>
.st-key-{LAUNCHER_KEY} {{ position: fixed; left: 16px; bottom: 16px; z-index: 1000100; width: auto; }}
.st-key-{LAUNCHER_KEY} button {{ width: 56px; height: 56px; min-height: 56px; border-radius: 50%; padding: 0;
  box-shadow: 0 2px 10px rgba(0,0,0,.3); font-size: 1.5rem; }}
.st-key-{PANEL_KEY} {{ position: fixed; left: 16px; bottom: 84px; z-index: 1000100; width: min(380px, calc(100vw - 32px));
  max-height: calc(100vh - 108px); overflow-y: auto; padding: 12px; border-radius: 12px; background: {bg}; color: {fg};
  border: 1px solid {border}; box-shadow: 0 6px 24px rgba(0,0,0,.28); }}
.st-key-{PANEL_KEY} button {{ min-height: 32px; padding: 2px 10px; font-size: 0.85rem; }}
@media (max-width: 640px) {{
  .st-key-{PANEL_KEY} {{ left: 8px; width: calc(100vw - 16px); bottom: 76px; max-height: calc(100vh - 92px); }}
  .st-key-{LAUNCHER_KEY} {{ left: 8px; bottom: 8px; }}
}}
</style>"""


# --------------------------------------------------------------------------- #
# Result cards (rendered from serialized backend outputs only)
# --------------------------------------------------------------------------- #


def _apply(dash: DashboardState, config: Mapping[str, float]) -> None:
    dash.load_whatif(ActionConfig.from_mapping(config))


def _metric_lines(m: Mapping[str, Any]) -> str:
    return (f"- Emissions: **{tonnes(m['total_co2e_tco2e'])}** ({pct(m['co2_reduction_ratio'])} vs baseline)\n"
            f"- Operating profit: **{gbp(m['total_profit_gbp'])}** ({gbp(m['profit_change_gbp'])} vs baseline)\n"
            f"- Gross outlay: **{gbp(m['total_cost_gbp'])}** · net cash {gbp(m['net_cash_impact_gbp'])}")


def render_card(card: Mapping[str, Any], *, stale: bool, dash: DashboardState) -> None:
    data = card["data"]
    kind = data.get("kind")
    mock = " · :orange-badge[MOCK]" if data.get("is_mock") else ""
    with st.container(border=True):
        if stale:
            st.caption("From a previous analysis context; re-ask to refresh. Apply is disabled.")
        if kind == "baseline":
            t = data["totals"]
            st.markdown(f"**Baseline forecast** · {data['period']}{mock}\n"
                        f"- Emissions: **{tonnes(t['total_co2e_tco2e'])}**\n"
                        f"- Operating profit: **{gbp(t['operating_profit_gbp'])}** · revenue {gbp(t['revenue_gbp'])}")
        elif kind == "simulation":
            st.markdown(f"**What-if preview** · `{data['strategy_id']}`{mock}\n" + _metric_lines(data["metrics"]))
            sh = data["resulting_shares"]
            names = {"renewable_energy": "Renewable", "ev_adoption": "EV"}
            st.caption("Final shares (baseline → resulting): " + " · ".join(
                f"{names[n]} {pct(v['baseline'])} → {pct(v['resulting'])}" for n, v in data["resulting_shares"].items()))
            for c in data["conversions"]:
                st.caption(f"{c['action'].replace('_', ' ')}: final share {pct(c['target_final_share'])} = "
                           f"{c['fraction_of_remaining']:.3f} of remaining opportunity")
            f = data.get("feasibility")
            if f is not None:
                st.caption("✅ Meets current constraints" if f["feasible"] else "⚠️ Does not meet: " + ", ".join(f["failed"]))
            for note in data.get("notes", []):
                st.caption(note)
            st.button("Apply to dashboard", key=f"apply_{card['id']}", disabled=stale, on_click=_apply,
                      args=(dash, data["config"]), help="Loads this exact action mix into the what-if sliders.")
        elif kind == "optimization":
            c = data["constraints"]
            st.markdown(f"**Optimization preview** · budget {gbp(c['budget_gbp'])}, profit floor "
                        f"{gbp(c['min_total_profit_gbp'])}, target {pct(c['min_co2_reduction_ratio'])}{mock}")
            if data["status"] != "ok":
                st.warning("No feasible plan found within the search budget.", icon="🚫")
            else:
                r = data["recommended"]
                st.markdown(f"Recommended `{r['strategy_id']}` of {data['pareto_count']} frontier plans\n" + _metric_lines(r["metrics"]))
                st.button("Load recommended into what-if", key=f"apply_{card['id']}", disabled=stale, on_click=_apply,
                          args=(dash, r["config"]))
            st.caption(data["note"])
        elif kind == "risk":
            s = data["summary"]
            st.markdown(f"**Risk** · `{data['strategy_id']}` · {data['n_simulations']:,} trials{mock}\n"
                        f"- P(target met): **{pct(s['target_probability'])}**\n"
                        f"- P(all constraints): **{pct(s['joint_feasibility_probability'])}**\n"
                        f"- Emissions p05–p95: {tonnes(s['co2_p05_tco2e'])} – {tonnes(s['co2_p95_tco2e'])}")
            st.caption("Empirical trial outcomes conditional on the baseline forecast; not guarantees.")


# --------------------------------------------------------------------------- #
# Panel
# --------------------------------------------------------------------------- #


def _provider_from_env() -> tuple[ChatbotConfig | None, ChatModelProvider | None, str | None]:
    try:
        config = ChatbotConfig.from_env(os.environ)
        return config, create_chat_provider(config), None
    except ChatConfigurationError as exc:
        return None, None, str(exc)


def _render_message(m: Mapping[str, Any], *, context: AnalysisContext | None, dash: DashboardState, chat: ChatState) -> None:
    if m["role"] == "user":
        with st.chat_message("user"):
            st.markdown(m["content"])
        return
    with st.chat_message("assistant"):
        if m.get("is_mock"):
            st.caption(":orange-badge[MOCK MODEL] rule-based stand-in, not a language model")
        if m["error"]:
            e = m["error"]
            st.error(f"**{e['type']}**: {e['message']}", icon="🛑")
            st.caption("Your message is kept. Nothing was replaced with mock output.")
            st.button("Retry", key=f"retry_{m['id']}", on_click=chat.retry, args=(m["turn"],),
                      help="Re-runs this message; completed tools are not executed again.")
            return
        st.markdown(m["content"])
        for note in m.get("notices", []):
            st.caption(f"ℹ️ {note}")
        for card in m["cards"]:
            render_card(card, stale=context is None or card["context_version"] != context.version, dash=dash)


def render_chat(dash: DashboardState, services: Services, request: AnalysisRequest, *, dark: bool) -> None:
    chat = ChatState(st.session_state)
    st.html(_css(dark))
    with st.container(key=LAUNCHER_KEY):
        st.button(":material/close:" if chat.is_open else ":material/chat:", key="cc_toggle",
                  type="primary", on_click=lambda: chat.set_open(not chat.is_open),
                  help="Close the assistant" if chat.is_open else "Open the CarbonOpt assistant")
    if not chat.is_open:
        return

    config, provider, config_error = _provider_from_env()
    context = None
    if dash.baseline is not None:
        context = AnalysisContext(services, request, dash.baseline, dash.analysis, dash.selected_strategy())

    with st.container(key=PANEL_KEY):
        head, clear, close = st.columns([5, 3, 3], vertical_alignment="center")
        head.markdown("**CarbonOpt assistant**")
        clear.button("Clear", key="cc_clear", on_click=chat.clear, help="Clear this conversation (the dashboard is unchanged)")
        close.button("Close", key="cc_close", on_click=chat.set_open, args=(False,), help="Close the assistant")
        if config_error:
            st.error(f"Chatbot configuration error: {config_error}", icon="🛑")
        elif provider is not None:
            label = ":orange-badge[MOCK MODEL]" if provider.info.is_mock else f"`{provider.info.name}`"
            st.caption(f"Model: {label} · answers use the dashboard's current analysis")
            if not provider.info.is_mock:
                st.button("Check connection", key="cc_check", help="Explicit request to the configured endpoint")
                if st.session_state.get("cc_check"):
                    try:
                        status = provider.check_connection()
                        chat.set_connection(status.ok, status.detail)
                    except CarbonOptError as exc:
                        chat.set_connection(False, f"{type(exc).__name__}: {exc}")
                conn = chat.connection
                if conn:
                    (st.success if conn["ok"] else st.error)(conn["detail"])
        if services.is_mock:
            st.caption("Backend providers are mocked: " + ", ".join(services.mocked_slots) + ".")
        if not services.capabilities.risk_available:
            st.caption("Risk questions are unavailable: " + services.unavailable.get("risk", "no provider") + ".")

        area = st.container(height=240, key="cc_messages")
        with area:
            if not chat.messages:
                st.caption("Ask about the baseline, the selected strategy, a what-if, a plan under a budget, or risk. "
                           "Action values are fractions of remaining opportunity; say '80%' for a final share.")
            for m in chat.messages:
                _render_message(m, context=context, dash=dash, chat=chat)
            pending = chat.pending_turn()
            if pending is not None:
                with st.chat_message("assistant"):
                    with st.spinner("Thinking…"):
                        chat.process(pending, provider, context, config_error)
                st.rerun()

        if not chat.messages:
            for i, text in enumerate(SUGGESTIONS):
                st.button(text, key=f"cc_sugg_{i}", on_click=chat.submit, args=(text,), width="stretch")
        prompt = st.chat_input("Ask the assistant…", key="cc_input")
        if prompt:
            chat.submit(prompt)
            st.rerun()
