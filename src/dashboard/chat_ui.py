"""Floating assistant: circular bottom-left bubble and an expandable panel.

Built from documented Streamlit pieces: st.container(key=...) (Streamlit adds
the CSS class `st-key-<key>`), st.button, st.chat_message, st.chat_input and
st.html for a small stylesheet. If the stylesheet is not applied the same widgets
render inline and stay usable. All model requests and tool execution happen in
Python on the server; the browser never receives credentials or calls tools.
"""

from __future__ import annotations

import os
import logging
from typing import Any, Mapping

import streamlit as st

from src.contracts.types import ActionConfig, AnalysisRequest
from src.integration.services import Services
from src.llm.config import ChatbotConfig, ChatConfigurationError
from src.llm.context import AnalysisContext
from src.llm.providers import ChatModelProvider, create_chat_provider
from src.llm.summaries import gbp, pct, tonnes

from .chat_state import SUGGESTIONS, ChatState
from .state import DashboardState
from .theme import BG, GREEN, INK, MUTED

logger = logging.getLogger(__name__)

LAUNCHER_KEY = "cc_launcher"
PANEL_KEY = "cc_panel"
SIZE_KEY = "cc_size"
# Panel width (px, capped to the viewport) and conversation height (px) per size preset.
SIZES = {"compact": (380, 300), "large": (620, 460), "full": (1000, 600)}
SIZE_ICONS = {"compact": ":material/close_fullscreen:", "large": ":material/open_in_full:",
              "full": ":material/fullscreen:"}


def _css(dark: bool, size: str) -> str:
    # surface, text, muted text, edge, accent, raised fill (chips/user bubbles), input field
    bg, fg, muted, border, accent, raised, field = (
        ("#151e27", INK, MUTED, "#2f4a3c", GREEN, "#1e2b36", BG) if dark else
        ("#ffffff", "#0b0b0b", "#5b6168", "#b9c4bd", "#1a7f45", "#eef4f0", "#f7f9f8"))
    width = SIZES[size][0]
    return f"""<style>
.st-key-{LAUNCHER_KEY} {{ position: fixed; left: 16px; bottom: 16px; z-index: 1000100; width: auto; }}
.st-key-{LAUNCHER_KEY} button {{ width: 56px; height: 56px; min-height: 56px; border-radius: 50%; padding: 0;
  box-shadow: 0 2px 10px rgba(0,0,0,.3); font-size: 1.5rem; }}
.st-key-{PANEL_KEY} {{ position: fixed; left: 16px; bottom: 84px; z-index: 1000100; width: min({width}px, calc(100vw - 32px));
  max-height: calc(100vh - 108px); overflow-y: auto; padding: 12px 14px; border-radius: 14px; background: {bg}; color: {fg};
  border: 1px solid {border}; box-shadow: 0 10px 36px rgba(0,0,0,.45); }}
.st-key-{PANEL_KEY} [data-testid="stCaptionContainer"] {{ color: {muted}; }}
/* Header and status separated from the conversation by one divider line. */
.st-key-cc_head {{ border-bottom: 1px solid {border}; padding-bottom: 8px; margin-bottom: 2px; }}
/* The message box: accent outline on a darker field so it is easy to find. */
.st-key-{PANEL_KEY} [data-testid="stChatInput"] {{ border: 1.5px solid {accent}; border-radius: 12px; background: {field};
  box-shadow: 0 0 0 3px {accent}22; }}
.st-key-{PANEL_KEY} [data-testid="stChatInput"] textarea {{ color: {fg}; }}
.st-key-{PANEL_KEY} [data-testid="stChatInput"] textarea::placeholder {{ color: {muted}; opacity: 1; }}
.st-key-{PANEL_KEY} button {{ min-height: 32px; padding: 2px 10px; font-size: 0.85rem; }}
/* Drag the bottom-right corner of the conversation to make it taller or shorter. */
.st-key-cc_messages {{ resize: vertical; min-height: 160px; max-height: calc(100vh - 260px); }}
.st-key-cc_suggestions button {{ border-radius: 999px; min-height: 28px; font-size: 0.8rem; background: {raised};
  border: 1px solid {accent}66; color: {fg}; }}
.st-key-cc_suggestions button:hover {{ border-color: {accent}; color: {accent}; }}
/* Result cards: tinted block with an accent bar instead of a second bordered box. */
.st-key-{PANEL_KEY} [class*="st-key-cc_card_"] {{ background: {raised}; border-left: 3px solid {accent};
  border-radius: 8px; padding: 10px 12px; }}
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


DATA_CARD_TITLES = {"company_profile": "Company data used", "action_comparison": "Action comparison used",
                    "public_reference": "Wincanton reference used"}
ACTION_CARD_KINDS = ("baseline", "simulation", "optimization", "risk")


def _data_card(kind: str, data: Mapping[str, Any]) -> None:
    """Compact view of the facts a read-only data tool gave the model, so answers can be checked."""
    if kind == "company_profile":
        f = data["baseline_forecast"]["emissions"]
        st.markdown(f"**Forecast** {data['baseline_forecast']['period']}: {tonnes(f['total_tco2e'])} · Scope 1 "
                    f"{f['share_pct']['scope1']}% · Scope 2 {f['share_pct']['scope2']}% · Scope 3 {f['share_pct']['scope3']}%")
        hist = data.get("history")
        if hist:
            w = hist["last_12_months"]
            line = (f"**Last 12 months** {w['period']}: {tonnes(w['emissions']['total_tco2e'])}, operating profit "
                    f"{gbp(w['operating_profit_gbp'])} ({w['operating_margin_pct']}% margin)")
            change = hist.get("change_last_12_vs_previous_12_pct")
            if change:
                line += f" · emissions {change['total_co2e_tco2e']:+}% vs the year before"
            st.markdown(line)
            if hist["not_reported_in_data"]:
                st.caption("Not reported in the data: " + ", ".join(hist["not_reported_in_data"]))
        st.caption(data["data_note"])
    elif kind == "action_comparison":
        lines = []
        for r in data["actions"]:
            m = r["alone_at_full_adoption_over_horizon"]
            if r["has_effect_for_this_company"]:
                per_t = gbp(m["outlay_per_tonne_cut_gbp"]) if m["outlay_per_tonne_cut_gbp"] is not None else "n/a"
                lines.append(f"- **{r['label']}**: {tonnes(m['co2_cut_tco2e'])} ({m['co2_cut_pct_of_total_baseline']}%) · "
                             f"{per_t}/t")
            else:
                lines.append(f"- {r['label']}: no effect for this company")
        st.markdown("\n".join(lines))
        st.caption("Each action alone at full adoption over the horizon. Costs are illustrative assumptions.")
    elif kind == "public_reference":
        d = data["derived_from_figures"]
        st.markdown(f"**{data['company']}** · {data['period']} · [source]({data['source']['url']})\n"
                    f"- Transport fuel: {d['transport_fuel_share_of_scope1_2_pct']}% of Scope 1+2\n"
                    f"- Scope 1+2 per £m revenue: {d['scope1_2_tco2e_per_gbp_million_revenue']} tCO2e")
        sc = data.get("electricity_scenario")
        if sc:
            st.markdown(f"- {sc['reduction_pct']}% less electricity: {tonnes(sc['co2e_saved_tco2e_per_year'])} saved/year")
        st.caption("A separate real company, used only as a reference.")


def render_card(card: Mapping[str, Any], *, stale: bool, dash: DashboardState) -> None:
    data = card["data"]
    kind = data.get("kind")
    mock = " · test data" if data.get("is_mock") else ""
    if kind in DATA_CARD_TITLES:
        with st.expander(DATA_CARD_TITLES[kind], icon=":material/dataset:"):
            _data_card(kind, data)
        return
    if kind not in ACTION_CARD_KINDS:
        return  # nothing to show; never draw an empty box
    with st.container(key=f"cc_card_{card['id']}"):  # styled as a tinted block with an accent bar, not a box
        if stale:
            st.caption("From a previous analysis context; re-ask to refresh. Apply is disabled.")
        if kind == "baseline":
            t = data["totals"]
            st.markdown(f"**Baseline forecast** · {data['period']}{mock}\n"
                        f"- Emissions: **{tonnes(t['total_co2e_tco2e'])}**\n"
                        f"- Operating profit: **{gbp(t['operating_profit_gbp'])}** · revenue {gbp(t['revenue_gbp'])}")
        elif kind == "simulation":
            st.markdown(f"**What-if preview**{mock}\n" + _metric_lines(data["metrics"]))
            names = {"renewable_energy": "Renewable", "ev_adoption": "EV"}
            st.caption("Final shares (baseline → resulting): " + " · ".join(
                f"{names[n]} {pct(v['baseline'])} → {pct(v['resulting'])}" for n, v in data["resulting_shares"].items()))
            for c in data["conversions"]:
                st.caption(f"{c['action'].replace('_', ' ')}: final share {pct(c['target_final_share'])} = "
                           f"{pct(c['fraction_of_remaining'])} of remaining opportunity")
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
                st.markdown(f"Recommended action mix from {data['pareto_count']} frontier plans\n" + _metric_lines(r["metrics"]))
                st.button("Load recommended into what-if", key=f"apply_{card['id']}", disabled=stale, on_click=_apply,
                          args=(dash, r["config"]))
            st.caption(data["note"])
        elif kind == "risk":
            s = data["summary"]
            st.markdown(f"**Uncertainty** · {data['n_simulations']:,} trials{mock}\n"
                        f"- Chance of meeting CO₂ target: **{pct(s['target_probability'])}**\n"
                        f"- Chance of meeting all goals: **{pct(s['joint_feasibility_probability'])}**\n"
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
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(m["content"])
        return
    with st.chat_message("assistant", avatar=":material/eco:"):
        if m.get("is_mock"):
            st.caption("Guided assistant · recognises preset questions and uses dashboard tools")
        if m["error"]:
            e = m["error"]
            logger.error("Assistant %s: %s", e['type'], e['message'])
            st.error("The assistant could not answer this request. Please try again.", icon="🛑")
            st.caption("Your message has been kept.")
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
    size = st.session_state.get(SIZE_KEY) or "compact"
    st.html(_css(dark, size))
    with st.container(key=LAUNCHER_KEY):
        st.button(":material/close:" if chat.is_open else ":material/chat:", key="cc_toggle",
                  type="primary", on_click=lambda: chat.set_open(not chat.is_open),
                  help="Close the assistant" if chat.is_open else "Open the CarbonOpt assistant")
    if not chat.is_open:
        return

    config, provider, config_error = _provider_from_env()
    context = None
    if dash.baseline is not None:
        context = AnalysisContext(services, request, dash.baseline, dash.analysis, dash.selected_strategy(),
                                  history=dash.history)

    with st.container(key=PANEL_KEY):
        head = st.container(key="cc_head")
        with head.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.markdown("**CarbonOpt assistant**", width="stretch")
            st.button(":material/delete_sweep:", key="cc_clear", on_click=chat.clear,
                      help="Clear this conversation (the dashboard is unchanged)")
            st.button(":material/close:", key="cc_close", on_click=chat.set_open, args=(False,),
                      help="Close the assistant")
        with head.container(horizontal=True, vertical_alignment="center", gap="small"):
            if config_error:
                logger.error("Assistant configuration: %s", config_error)
                st.error("The assistant is currently unavailable. Please contact the application administrator.",
                         icon="🛑", width="stretch")
            elif provider is not None:
                hosts = {"lmstudio": "LM Studio", "ollama": "Ollama"}
                label = ("Guided assistant · recognises preset questions" if provider.info.is_mock else
                         f"AI model · {provider.info.version} via {hosts.get(config.provider, config.provider)}")
                st.caption(f"{label} · answers use your current analysis", width="stretch")
            st.segmented_control("Panel size", list(SIZES), default="compact", required=True, key=SIZE_KEY,
                                 format_func=SIZE_ICONS.get, label_visibility="collapsed",
                                 help="Panel size: compact, large or full width. Drag the conversation's bottom-right corner to change its height.")
        if not services.capabilities.risk_available:
            st.caption("Uncertainty analysis is currently unavailable.")

        area = st.container(height=SIZES[size][1], border=False, key="cc_messages")  # no box inside the box
        with area:
            if not chat.messages:
                # Intro text, not a chat message: the conversation itself stays empty until the user asks.
                st.markdown(":material/eco: **Hi! Ask me in your own words**: where your emissions come from, which "
                            "actions work best, what-ifs, a plan within your budget, or the risk of missing your target.")
                st.caption("Tip: say '80%' for a final share, for example 'What if EV share becomes 80%?'")
                with st.container(horizontal=True, gap="small", key="cc_suggestions"):
                    for i, text in enumerate(SUGGESTIONS):
                        st.button(text, key=f"cc_sugg_{i}", on_click=chat.submit, args=(text,), width="content")
            for m in chat.messages:
                _render_message(m, context=context, dash=dash, chat=chat)
            pending = chat.pending_turn()
            if pending is not None:
                with st.chat_message("assistant"):
                    with st.spinner("Thinking…"):
                        chat.process(pending, provider, context, config_error)
                st.rerun()

        prompt = st.chat_input("Ask the assistant…", key="cc_input")
        if prompt:
            chat.submit(prompt)
            st.rerun()
