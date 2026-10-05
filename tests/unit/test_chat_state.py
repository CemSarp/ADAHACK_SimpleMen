"""Conversation persistence, stale-context handling, failures without mock fallback."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.dashboard.chat_state import MAX_USER_CHARS, ChatState
from src.dashboard.state import DashboardState
from src.integration import run_analysis
from src.llm.context import AnalysisContext
from src.llm.providers import ChatConnectionError, MockChatProvider, OllamaChatProvider
from src.llm.config import ChatbotConfig
from tests.unit.test_chat_config_providers import FakeTransport
from tests.unit.test_chat_assistant import Scripted
from src.llm.types import ModelResponse, ToolCall
from tests.mocks import make_services


@pytest.fixture
def ctx(mock_services, request_ok):
    a = run_analysis(request_ok, services=mock_services)
    return AnalysisContext(mock_services, request_ok, a.baseline, a, a.optimization.strategies[a.recommendation.strategy_id])


def ask(chat, text, provider, ctx, config_error=None):
    turn = chat.submit(text)
    chat.process(turn, provider, ctx, config_error)
    return turn


def test_conversation_persists_across_open_close_and_reruns(ctx):
    store = {}
    chat = ChatState(store)
    ask(chat, "Show the baseline forecast.", MockChatProvider(), ctx)
    chat.set_open(True); chat.set_open(False); chat.set_open(True)
    again = ChatState(store)  # a later script run sees the same session store
    assert [m["role"] for m in again.messages] == ["user", "assistant"]
    assert again.messages[1]["is_mock"] is True and again.messages[1]["cards"][0]["data"]["kind"] == "baseline"


def test_clear_resets_chat_only_not_the_dashboard(ctx, mock_services, request_ok):
    store = {}
    dash = DashboardState(store)
    dash.sync_services(mock_services)
    dash.ensure_baseline(request_ok, mock_services)
    dash.run_optimize(request_ok, mock_services)
    chat = ChatState(store)
    ask(chat, "Show the baseline forecast.", MockChatProvider(), ctx)
    chat.clear()
    assert chat.messages == [] and dash.analysis is not None and dash.baseline is not None
    # and a dashboard provider change does not delete the conversation
    ask(chat, "hello", MockChatProvider(), ctx)
    dash.sync_services(make_services({"simulator": "fixture"}))
    assert len(chat.messages) == 2


def test_empty_and_overlong_messages(ctx):
    chat = ChatState({})
    assert chat.submit("   ") is None and chat.messages == []
    chat.submit("x" * 5000)
    assert len(chat.messages[0]["content"]) == MAX_USER_CHARS


def test_cards_store_the_context_version_that_produced_them(ctx):
    chat = ChatState({})
    ask(chat, "What if EV share becomes 80%?", MockChatProvider(), ctx)
    card = chat.messages[-1]["cards"][0]
    assert card["context_version"] == ctx.version
    other = replace(ctx, request=replace(ctx.request, constraints=replace(ctx.request.constraints, budget_gbp=1.0)))
    assert card["context_version"] != other.version  # the UI marks this card stale and disables Apply


def test_card_numbers_match_direct_service_output(ctx):
    chat = ChatState({})
    ask(chat, "What if EV share becomes 80%?", MockChatProvider(), ctx)
    card = chat.messages[-1]["cards"][0]["data"]
    direct = ctx.services.simulate(ctx.baseline, replace(ctx.selected.config, ev_adoption=0.8))
    assert card["strategy_id"] == direct.strategy_id
    assert card["metrics"]["total_co2e_tco2e"] == direct.metrics["total_co2e_tco2e"]
    assert card["metrics"]["total_profit_gbp"] == direct.metrics["total_profit_gbp"]
    assert card["metrics"]["total_cost_gbp"] == direct.metrics["total_cost_gbp"]


def test_remote_failure_is_visible_keeps_message_and_never_falls_back_to_mock(ctx):
    cfg = ChatbotConfig.from_env({"CHATBOT_PROVIDER": "ollama", "OLLAMA_BASE_URL": "http://llm.example.test"})
    provider = OllamaChatProvider(cfg, transport=FakeTransport(error=ChatConnectionError("connection refused")))
    chat = ChatState({})
    turn = ask(chat, "Show the baseline forecast.", provider, ctx)
    user, answer = chat.messages
    assert user["content"] == "Show the baseline forecast."
    assert answer["error"] == {"type": "ChatConnectionError", "message": "connection refused"}
    assert answer["is_mock"] is False and answer["cards"] == [] and answer["content"] == ""
    assert chat.pending_turn() is None


def test_configuration_error_is_a_visible_message(ctx):
    chat = ChatState({})
    ask(chat, "hello", None, ctx, config_error="CHATBOT_PROVIDER=ollama requires OLLAMA_BASE_URL")
    assert chat.messages[1]["error"]["type"] == "ChatConfigurationError"


def test_retry_reprocesses_the_same_turn_without_rerunning_tools(ctx, monkeypatch):
    from src.llm import assistant
    runs = []
    real = assistant.execute_tool
    monkeypatch.setattr(assistant, "execute_tool", lambda *a, **k: (runs.append(a[0]), real(*a, **k))[1])
    chat = ChatState({})
    failing = Scripted(ModelResponse("", (ToolCall("get_baseline", {}),)), fail_at=2)
    turn = ask(chat, "baseline", failing, ctx)
    assert chat.messages[-1]["error"]["type"] == "ChatServerError" and runs == ["get_baseline"]
    chat.retry(turn)
    assert chat.pending_turn() == turn and [m["role"] for m in chat.messages] == ["user"]
    chat.process(turn, Scripted(ModelResponse("", (ToolCall("get_baseline", {}),)), ModelResponse("Done.")), ctx)
    assert runs == ["get_baseline"]  # not executed twice
    assert chat.messages[-1]["content"] == "Done." and chat.messages[-1]["error"] is None
    assert len(chat.messages[-1]["cards"]) == 1


def test_history_excludes_failed_answers_and_later_turns(ctx):
    chat = ChatState({})
    ask(chat, "first", MockChatProvider(), ctx)
    t2 = chat.submit("second")
    hist = chat._history(t2)
    assert [(m.role, m.content[:5]) for m in hist] == [("user", "first"), ("assistant", "I can")]
