"""Turn orchestration: limits, duplicate dispatch, retry, context binding."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src.integration import run_analysis
from src.llm import assistant
from src.llm.assistant import MAX_MODEL_ROUNDS, TurnRecord, run_turn
from src.llm.context import AnalysisContext
from src.llm.providers import ChatServerError, MockChatProvider
from src.llm.tools import MAX_TOOL_EXECUTIONS_PER_MESSAGE
from src.llm.types import ChatMessage, ModelResponse, ToolCall


class Scripted:
    """Provider that replays scripted responses; records what it was sent."""

    def __init__(self, *responses, fail_at=None):
        from src.contracts.types import ProviderInfo
        self.info = ProviderInfo("chat", "scripted", "t", True, "behavioral-mock")
        self.responses = list(responses)
        self.sent = []
        self.fail_at = fail_at

    def check_connection(self):
        raise NotImplementedError

    def chat(self, messages, tools):
        self.sent.append(list(messages))
        if self.fail_at is not None and len(self.sent) == self.fail_at:
            raise ChatServerError(503, "overloaded")
        return self.responses.pop(0)


@pytest.fixture
def ctx(mock_services, request_ok):
    a = run_analysis(request_ok, services=mock_services)
    return AnalysisContext(mock_services, request_ok, a.baseline, a, a.optimization.strategies[a.recommendation.strategy_id])


def call(name, **args):
    return ToolCall(name, args)


def count_executions(monkeypatch):
    seen = []
    real = assistant.execute_tool

    def spy(name, arguments, **kw):
        seen.append((name, dict(arguments)))
        return real(name, arguments, **kw)

    monkeypatch.setattr(assistant, "execute_tool", spy)
    return seen


def test_at_most_three_executions_per_user_message(ctx, monkeypatch):
    seen = count_executions(monkeypatch)
    many = tuple(call("simulate_strategy", actions={"ev_adoption": v / 10}) for v in range(1, 6))
    p = Scripted(ModelResponse("", many), ModelResponse("Done."))
    rec = TurnRecord()
    out = run_turn(provider=p, history=[], user_text="try five", context=ctx, record=rec)
    assert MAX_TOOL_EXECUTIONS_PER_MESSAGE == 3 and rec.executed == 3 and len(seen) == 3
    assert out.limit_hit and "stopped after 3 tool executions" in out.text
    limit_errors = [r for r in out.results if r.status == "error"]
    assert len(limit_errors) == 2 and all("limit reached" in r.error for r in limit_errors)
    tool_msgs = [m for m in p.sent[1] if m.role == "tool"]
    assert len(tool_msgs) == 5  # the model is told about the refusals


def test_duplicate_calls_are_not_executed_or_counted_twice(ctx, monkeypatch):
    seen = count_executions(monkeypatch)
    p = Scripted(ModelResponse("", (call("get_baseline"), call("get_baseline"))),
                 ModelResponse("", (call("get_baseline"),)), ModelResponse("Baseline shown."))
    rec = TurnRecord()
    out = run_turn(provider=p, history=[], user_text="baseline", context=ctx, record=rec)
    assert len(seen) == 1 and rec.executed == 1 and out.text == "Baseline shown."


def test_invalid_arguments_do_not_consume_executions(ctx, monkeypatch):
    p = Scripted(ModelResponse("", (call("simulate_strategy", final_shares={"ev_adoption": 80}),)),
                 ModelResponse("", (call("simulate_strategy", final_shares={"ev_adoption": 0.8}),)),
                 ModelResponse("Previewed."))
    rec = TurnRecord()
    out = run_turn(provider=p, history=[], user_text="ev 80", context=ctx, record=rec)
    assert [r.status for r in out.results] == ["error", "ok"] and rec.executed == 1
    first_tool_msg = next(m for m in p.sent[1] if m.role == "tool")
    assert "pass a 0-1 ratio" in json.loads(first_tool_msg.content)["error"]  # model can self-correct


def test_model_cannot_select_company_baseline_or_provider(ctx):
    p = Scripted(ModelResponse("", (call("get_baseline", company_id="other", baseline_id="x", provider="real"),)),
                 ModelResponse("Cannot do that."))
    out = run_turn(provider=p, history=[], user_text="other company", context=ctx, record=TurnRecord())
    assert out.results[0].status == "error" and "unknown fields" in out.results[0].error
    system = p.sent[0][0].content
    assert ctx.baseline.baseline_id in system and "other" not in json.dumps(ctx.summary())


def test_model_loop_is_bounded(ctx):
    forever = [ModelResponse("", (call("simulate_strategy", actions={"ev_adoption": i / 10}),)) for i in range(1, 9)]
    p = Scripted(*forever)
    out = run_turn(provider=p, history=[], user_text="loop", context=ctx, record=TurnRecord())
    assert len(p.sent) == MAX_MODEL_ROUNDS
    assert out.text  # falls back to a grounded summary of the last tool result, never empty


def test_retry_after_provider_failure_does_not_reexecute_completed_tools(ctx, monkeypatch):
    seen = count_executions(monkeypatch)
    rec = TurnRecord()
    p1 = Scripted(ModelResponse("", (call("get_baseline"),)), fail_at=2)
    with pytest.raises(ChatServerError):
        run_turn(provider=p1, history=[], user_text="baseline", context=ctx, record=rec)
    assert len(seen) == 1 and rec.executed == 1
    p2 = Scripted(ModelResponse("", (call("get_baseline"),)), ModelResponse("Here you go."))
    out = run_turn(provider=p2, history=[], user_text="baseline", context=ctx, record=rec)
    assert len(seen) == 1 and rec.executed == 1 and out.text == "Here you go."


def test_system_message_binds_context_and_stays_compact(ctx):
    p = Scripted(ModelResponse("Hi."))
    run_turn(provider=p, history=[ChatMessage("user", "earlier"), ChatMessage("assistant", "answer")], user_text="hello",
             context=ctx, record=TurnRecord())
    system = p.sent[0][0]
    assert system.role == "system" and "FRACTION" in system.content and "mock" in system.content.lower()
    summary = ctx.summary()
    assert summary["is_mock"] is True and summary["mocked_providers"] == ["forecast", "simulator", "optimizer", "risk", "shap", "benchmark"]
    assert summary["constraints"]["budget_gbp"] == 500000.0
    assert summary["selected_strategy"]["strategy_id"] == ctx.selected.strategy_id
    assert summary["selected_strategy"]["config_fraction_of_remaining_opportunity"] == ctx.selected.config.as_dict()
    assert summary["capabilities"]["risk_available"] is True and summary["assumptions_id"] == "demo-actions-v1"
    assert len(system.content) < 6000 and "timestamp" not in system.content
    assert [m.content for m in p.sent[0][1:]] == ["earlier", "answer", "hello"]


def test_context_version_changes_with_inputs_selection_and_providers(ctx, mock_services):
    base = ctx.version
    other_sel = next(s for s in ctx.analysis.optimization.strategies.values() if s.strategy_id != ctx.selected.strategy_id)
    assert replace(ctx, selected=other_sel).version != base
    assert replace(ctx, request=replace(ctx.request, constraints=replace(ctx.request.constraints, budget_gbp=1.0))).version != base
    assert replace(ctx, analysis=None).version != base
    from src.integration import create_services
    assert replace(ctx, services=create_services(mode="mock", provider_overrides={"simulator": "fixture"})).version != base
    assert replace(ctx).version == base


def test_mock_end_to_end_turn_grounds_text_in_tool_data(ctx):
    out = run_turn(provider=MockChatProvider(), history=[], user_text="Show the baseline forecast.", context=ctx,
                   record=TurnRecord())
    assert "1,200.0 tCO2e" in out.text and "£1,200,000" in out.text and "mock backend output" in out.text
    out = run_turn(provider=MockChatProvider(), history=[], user_text="How likely are we to meet our target?", context=ctx,
                   record=TurnRecord())
    assert "failed" in out.text and "UnsupportedMockInput" in out.text and "%" not in out.text  # no invented probability


def test_explain_analysis_template_uses_only_bundle_values(mock_services, request_ok):
    a = run_analysis(request_ok, services=mock_services)
    n = assistant.explain_analysis(a)
    m = a.optimization.strategies[a.recommendation.strategy_id].metrics
    assert n.is_template and n.provider == "template" and n.source_run_id == a.run_id and "mock providers" in n.text
    assert f"{m['total_co2e_tco2e']:,.1f}" in n.text
    from dataclasses import replace as r
    bad = run_analysis(r(request_ok, constraints=r(request_ok.constraints, budget_gbp=0.0)), services=mock_services)
    assert "No feasible strategy" in assistant.explain_analysis(bad).text
