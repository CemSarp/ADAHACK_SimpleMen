"""Chat data tools: company profile, action comparison, public reference, and an LM Studio turn end to end."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.contracts.types import ActionConfig
from src.integration.pipeline import run_analysis
from src.llm.assistant import TurnRecord, run_turn
from src.llm.config import ChatbotConfig
from src.llm.context import AnalysisContext
from src.llm.insights import company_profile, compare_actions, public_reference
from src.llm.providers import LMStudioChatProvider
from src.llm.tools import execute_tool


@pytest.fixture
def ctx(mock_services, request_ok):
    a = run_analysis(request_ok, services=mock_services)
    return AnalysisContext(mock_services, request_ok, a.baseline, a, None, history=_history(a.baseline))


def _history(baseline) -> pd.DataFrame:
    """24 months: the later year has exactly 10% more emissions and revenue than the earlier one."""
    year = baseline.monthly.copy()
    later = year.copy()
    earlier = year.copy()
    earlier["timestamp"] = year["timestamp"] - pd.DateOffset(years=2)
    later["timestamp"] = year["timestamp"] - pd.DateOffset(years=1)
    for col in ("scope1_tco2e", "scope2_tco2e", "scope3_tco2e", "total_co2e_tco2e", "revenue_gbp"):
        later[col] = earlier[col] * 1.1
    out = pd.concat([earlier, later], ignore_index=True)
    out["gas_kwh"] = 0.0
    out["employees"] = 0
    return out


def test_company_profile_reports_shares_changes_and_missing_data(ctx):
    p = company_profile(ctx.history, ctx.baseline, ctx.services.assumptions)
    w = p["history"]["last_12_months"]
    e = w["emissions"]
    assert sum(e["share_pct"].values()) == pytest.approx(100, abs=0.2)
    assert e["total_tco2e"] == pytest.approx(e["scope1_tco2e"] + e["scope2_tco2e"] + e["scope3_tco2e"], abs=0.2)
    assert p["history"]["change_last_12_vs_previous_12_pct"]["total_co2e_tco2e"] == pytest.approx(10.0)
    assert p["history"]["change_last_12_vs_previous_12_pct"]["revenue_gbp"] == pytest.approx(10.0)
    assert {"gas (kWh)", "employees"} <= set(p["history"]["not_reported_in_data"])
    assert "gas (kWh)" not in w["activity"]
    assert p["baseline_forecast"]["horizon_months"] == 12 and p["data_kind"] == ctx.baseline.data_kind
    no_history = company_profile(None, ctx.baseline, ctx.services.assumptions)
    assert no_history["history"] is None and "No company history" in no_history["history_note"]


def test_compare_actions_ranks_by_simulated_cut_and_flags_no_effect(ctx):
    c = compare_actions(ctx.baseline, ctx.services)
    rows = {r["action"]: r for r in c["actions"]}
    assert len(rows) == 6
    cuts = [r["alone_at_full_adoption_over_horizon"]["co2_cut_tco2e"] for r in c["actions"]]
    assert cuts == sorted(cuts, reverse=True)
    assert c["ranked_by_co2_cut"] == [r["action"] for r in c["actions"] if r["has_effect_for_this_company"]]
    for name, r in rows.items():
        m = r["alone_at_full_adoption_over_horizon"]
        assert r["has_effect_for_this_company"] == (m["co2_cut_tco2e"] > 0)
        if not r["has_effect_for_this_company"]:
            assert name in c["no_effect_for_this_company"] and m["outlay_per_tonne_cut_gbp"] is None
    # The numbers are the simulator's, not estimates.
    top = c["actions"][0]
    sim = ctx.services.simulate(ctx.baseline, ActionConfig.from_mapping({**dict.fromkeys(rows, 0.0), top["action"]: 1.0}))
    assert top["alone_at_full_adoption_over_horizon"]["co2_cut_tco2e"] == pytest.approx(sim.metrics["co2_reduction_tco2e"], abs=0.05)


def test_public_reference_is_labelled_separate_and_reproduces_the_scenario():
    r = public_reference(0.10)
    assert r["data_kind"] == "reported_historical" and "NOT the dashboard company" in r["relationship"]
    assert r["derived_from_figures"] == {"transport_fuel_share_of_scope1_2_pct": 90.2,
                                         "electricity_share_of_scope1_2_pct": 6.8,
                                         "scope1_2_tco2e_per_gbp_million_revenue": 185.2,
                                         "scope3_vs_scope1_2_pct": 25.7}
    sc = r["electricity_scenario"]
    assert (sc["co2e_saved_tco2e_per_year"], sc["gross_energy_cost_saving_gbp_per_year"]) == (1014.74, 1937125)
    assert sc["share_of_reported_scope1_2_pct"] == 0.4 and "0.225" in sc["why_baseline_differs_from_reported"]
    assert "electricity_scenario" not in public_reference()
    assert set(r["scopes_explained"]) >= {"scope1", "scope2", "scope3"}


def test_new_tools_validate_arguments(ctx):
    bad = execute_tool("get_public_reference", {"electricity_reduction_ratio": 10}, context=ctx, services=ctx.services)
    assert bad.status == "error" and "0.1 for 10%" in bad.error
    assert execute_tool("compare_actions", {"x": 1}, context=ctx, services=ctx.services).status == "error"
    ok = execute_tool("get_company_profile", {}, context=ctx, services=ctx.services)
    assert ok.status == "ok" and json.dumps(ok.data, allow_nan=False)  # model payload must be valid JSON


def test_lmstudio_turn_calls_a_data_tool_and_returns_the_grounded_answer(ctx):
    replies = [
        {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "compare_actions", "arguments": "{}"}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "Fleet electrification cuts the most."}}]},
    ]
    sent = []

    def transport(method, url, body, headers, timeout):
        sent.append(body)
        return 200, json.dumps(replies.pop(0)).encode()

    provider = LMStudioChatProvider(ChatbotConfig.from_env({"CHATBOT_PROVIDER": "lmstudio"}), transport=transport)
    out = run_turn(provider=provider, history=[], user_text="Which action cuts the most CO2?", context=ctx,
                   record=TurnRecord())
    assert out.text == "Fleet electrification cuts the most." and out.executed == 1
    assert [r.tool_name for r in out.results] == ["compare_actions"]
    follow_up = sent[1]["messages"]
    tool_msg = follow_up[-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "t1"
    assert json.loads(tool_msg["content"])["data"]["kind"] == "action_comparison"
    assert "get_company_profile" in sent[0]["messages"][0]["content"]  # the prompt teaches the new tools


def test_mock_rule_only_when_backends_are_mock():
    from src.llm.prompt import MOCK_RULE, build_system_message
    assert MOCK_RULE in build_system_message({"is_mock": True})
    assert MOCK_RULE not in build_system_message({"is_mock": False})
    assert "mock backends" not in build_system_message({"is_mock": False})


def test_prompt_points_to_find_plans_and_follows_the_data_kind():
    from src.llm.prompt import build_system_message

    demo = build_system_message({"is_mock": False, "data_kind": "synthetic"})
    upload = build_system_message({"is_mock": False, "data_kind": "reported"})
    for prompt in (demo, upload):
        assert "Find plans" in prompt and "Optimize" not in prompt and "Real data and sources" not in prompt
        assert "get_forecast_drivers" in prompt
        assert 'What-if questions do not need a selected plan: without one use start_from="no_action"' in prompt
        assert '"All of the remaining" or "all remaining" means 1.0 in actions' in prompt
    assert "synthetic" in demo and "synthetic" not in upload and "uploaded" in upload


def test_context_tells_the_model_where_plans_come_from(mock_services, request_ok):
    from src.llm.context import AnalysisContext
    from tests.mocks import fixtures

    summary = AnalysisContext(mock_services, request_ok, fixtures.baseline(), None, None).summary()
    assert "Find plans" in summary["selected_strategy_note"]


@pytest.mark.parametrize("question,tool", [
    ("How accurate is the forecast?", "get_baseline"),
    ("Which model makes the forecast?", "get_baseline"),
    ("What drives the emissions forecast?", "get_forecast_drivers"),
])
def test_guided_assistant_routes_forecast_questions(question, tool):
    from src.llm.providers import MockChatProvider
    from src.llm.types import ChatMessage

    response = MockChatProvider().chat([ChatMessage("user", question)], ())
    assert [c.name for c in response.tool_calls] == [tool]


def test_summaries_cover_drivers_model_accuracy_and_infeasible_hints(ctx):
    from src.llm.summaries import summarize_payload
    from src.llm.tools import execute_tool, tool_result_payload

    def text(name, args):
        return summarize_payload(tool_result_payload(execute_tool(name, args, context=ctx, services=ctx.services)))

    assert "fixture-illustrative" in text("get_baseline", {})
    drivers = text("get_forecast_drivers", {"top_k": 1})
    assert "moves the emissions forecast most" in drivers
    infeasible = text("optimize_strategies", {"budget_gbp": 0.0})
    assert "No plan" in infeasible and ("budget of about" in infeasible or "deepest cut" in infeasible)


def test_a_scope_missing_from_the_data_is_reported_as_not_available(ctx):
    history = ctx.history.assign(scope3_tco2e=0.0)
    history["total_co2e_tco2e"] = history["scope1_tco2e"] + history["scope2_tco2e"]
    p = company_profile(history, ctx.baseline, ctx.services.assumptions)
    assert "scope 3 emissions" in p["history"]["not_reported_in_data"]
    assert "scope 3 emissions" not in company_profile(ctx.history, ctx.baseline, ctx.services.assumptions)[
        "history"]["not_reported_in_data"]
