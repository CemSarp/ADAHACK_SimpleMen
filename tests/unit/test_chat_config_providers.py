"""Chatbot configuration and model providers, fully offline (fake transport)."""

from __future__ import annotations

import json

import pytest

from src.llm.config import ChatbotConfig, ChatConfigurationError
from src.llm.providers import (
    ChatConnectionError,
    ChatInvalidResponse,
    ChatServerError,
    ChatTimeoutError,
    MockChatProvider,
    OllamaChatProvider,
    create_chat_provider,
)
from src.llm.tools import TOOL_SPECS
from src.llm.types import ChatMessage, ToolCall


def cfg(**env) -> ChatbotConfig:
    return ChatbotConfig.from_env({"CHATBOT_PROVIDER": "ollama", "OLLAMA_BASE_URL": "https://llm.example.test:11434", **env})


class FakeTransport:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append({"method": method, "url": url, "body": body, "headers": dict(headers), "timeout": timeout})
        if self.error:
            raise self.error
        status, payload = self.responses.pop(0)
        return status, payload if isinstance(payload, bytes) else json.dumps(payload).encode()


# ----------------------------- configuration ----------------------------- #


def test_defaults_are_mock_with_documented_model():
    c = ChatbotConfig.from_env({})
    assert (c.provider, c.model, c.base_url) == ("mock", "llama3.1:8b", None)
    assert (c.timeout_seconds, c.max_output_tokens, c.api_key) == (60.0, 512, None)


def test_ollama_config_from_env():
    c = cfg(OLLAMA_MODEL="llama3.1:8b", OLLAMA_TIMEOUT_SECONDS="30", OLLAMA_MAX_OUTPUT_TOKENS="256", OLLAMA_API_KEY="s3cret")
    assert (c.provider, c.base_url, c.timeout_seconds, c.max_output_tokens) == ("ollama", "https://llm.example.test:11434", 30.0, 256)
    assert "s3cret" not in repr(c) and "<set>" in repr(c)


@pytest.mark.parametrize("env,match", [
    ({"CHATBOT_PROVIDER": "openai"}, "CHATBOT_PROVIDER"),
    ({"CHATBOT_PROVIDER": "ollama"}, "requires OLLAMA_BASE_URL"),
    ({"CHATBOT_PROVIDER": "ollama", "OLLAMA_BASE_URL": "ftp://x"}, "http"),
    ({"CHATBOT_PROVIDER": "ollama", "OLLAMA_BASE_URL": "http://user:pw@host"}, "credentials"),
    ({"CHATBOT_PROVIDER": "ollama", "OLLAMA_BASE_URL": "http://host?x=1"}, "query"),
    ({"CHATBOT_PROVIDER": "ollama", "OLLAMA_BASE_URL": "http://host", "OLLAMA_TIMEOUT_SECONDS": "abc"}, "number"),
    ({"CHATBOT_PROVIDER": "ollama", "OLLAMA_BASE_URL": "http://host", "OLLAMA_TIMEOUT_SECONDS": "0"}, "TIMEOUT"),
    ({"CHATBOT_PROVIDER": "ollama", "OLLAMA_BASE_URL": "http://host", "OLLAMA_MAX_OUTPUT_TOKENS": "99999"}, "TOKENS"),
])
def test_invalid_configuration_is_rejected(env, match):
    with pytest.raises(ChatConfigurationError, match=match):
        ChatbotConfig.from_env(env)


def test_ollama_without_endpoint_never_falls_back_to_mock():
    with pytest.raises(ChatConfigurationError):
        create_chat_provider(ChatbotConfig(provider="ollama"))


# ------------------------------ ollama adapter ----------------------------- #


def test_request_shape_follows_native_chat_api():
    t = FakeTransport([(200, {"message": {"role": "assistant", "content": "hi"}, "done": True})])
    provider = OllamaChatProvider(cfg(OLLAMA_API_KEY="tok", OLLAMA_MAX_OUTPUT_TOKENS="200"), transport=t)
    history = [ChatMessage("system", "sys"), ChatMessage("user", "q"),
               ChatMessage("assistant", "", tool_calls=(ToolCall("get_baseline", {}),)),
               ChatMessage("tool", '{"status":"ok"}', tool_name="get_baseline")]
    provider.chat(history, TOOL_SPECS)
    call = t.calls[0]
    assert (call["method"], call["url"]) == ("POST", "https://llm.example.test:11434/api/chat")
    body = call["body"]
    assert body["model"] == "llama3.1:8b" and body["stream"] is False
    assert body["options"] == {"temperature": 0, "num_predict": 200}
    assert body["messages"][-1] == {"role": "tool", "content": '{"status":"ok"}', "tool_name": "get_baseline"}
    assert body["messages"][2]["tool_calls"] == [{"type": "function", "function": {"name": "get_baseline", "arguments": {}}}]
    assert [t_["function"]["name"] for t_ in body["tools"]] == [s.name for s in TOOL_SPECS]
    assert all(t_["type"] == "function" and t_["function"]["parameters"]["type"] == "object" for t_ in body["tools"])
    assert call["headers"]["Authorization"] == "Bearer tok" and call["timeout"] == 60.0


def test_no_auth_header_without_key():
    t = FakeTransport([(200, {"message": {"content": "x"}})])
    OllamaChatProvider(cfg(), transport=t).chat([ChatMessage("user", "q")], [])
    assert "Authorization" not in t.calls[0]["headers"]


def test_tool_call_normalization_object_and_string_arguments():
    t = FakeTransport([(200, {"message": {"role": "assistant", "content": "", "tool_calls": [
        {"type": "function", "function": {"index": 0, "name": "simulate_strategy", "arguments": {"final_shares": {"ev_adoption": 0.8}}}},
        {"function": {"name": "get_baseline", "arguments": "{}"}}]}})])
    r = OllamaChatProvider(cfg(), transport=t).chat([ChatMessage("user", "q")], TOOL_SPECS)
    assert r.tool_calls == (ToolCall("simulate_strategy", {"final_shares": {"ev_adoption": 0.8}}), ToolCall("get_baseline", {}))


@pytest.mark.parametrize("payload,match", [
    ({"nomessage": 1}, "no 'message'"),
    ({"message": {"content": ""}}, "neither text nor"),
    ({"message": {"content": "x", "tool_calls": [{"function": {"arguments": {}}}]}}, "no function name"),
    ({"message": {"content": "x", "tool_calls": [{"function": {"name": "a", "arguments": "{bad"}}]}}, "not valid JSON"),
    ({"message": {"content": "x", "tool_calls": [{"function": {"name": "a", "arguments": [1]}}]}}, "must be an object"),
    ({"message": {"content": 5}}, "must be a string"),
])
def test_invalid_model_responses_raise_typed_error(payload, match):
    provider = OllamaChatProvider(cfg(), transport=FakeTransport([(200, payload)]))
    with pytest.raises(ChatInvalidResponse, match=match):
        provider.chat([ChatMessage("user", "q")], [])


def test_non_json_body_and_http_errors():
    with pytest.raises(ChatInvalidResponse, match="non-JSON"):
        OllamaChatProvider(cfg(), transport=FakeTransport([(200, b"<html>")])).chat([ChatMessage("user", "q")], [])
    with pytest.raises(ChatServerError, match="model 'llama3.1:8b' not found") as exc:
        OllamaChatProvider(cfg(), transport=FakeTransport([(404, {"error": "model 'llama3.1:8b' not found"})])).chat(
            [ChatMessage("user", "q")], [])
    assert exc.value.status == 404
    with pytest.raises(ChatServerError) as exc:
        OllamaChatProvider(cfg(), transport=FakeTransport([(503, b"busy")])).chat([ChatMessage("user", "q")], [])
    assert exc.value.status == 503


def test_transport_failures_propagate_and_are_never_mocked():
    for err in (ChatTimeoutError("timed out"), ChatConnectionError("refused")):
        with pytest.raises(type(err)):
            OllamaChatProvider(cfg(), transport=FakeTransport(error=err)).chat([ChatMessage("user", "q")], [])


def test_connection_check_is_explicit_and_checks_model_tag():
    t = FakeTransport([(200, {"models": [{"name": "llama3.1:8b"}, {"name": "other:latest"}]}),
                       (200, {"models": [{"name": "other:latest"}]})])
    p = OllamaChatProvider(cfg(), transport=t)
    assert t.calls == []  # constructing makes no request
    ok = p.check_connection()
    assert ok.ok and t.calls[0]["method"] == "GET" and t.calls[0]["url"].endswith("/api/tags")
    missing = p.check_connection()
    assert not missing.ok and "not listed" in missing.detail


# --------------------------------- mock ---------------------------------- #


def test_mock_is_labelled_and_deterministic():
    p = MockChatProvider()
    assert p.info.is_mock and p.info.kind == "behavioral-mock"
    msg = [ChatMessage("user", "What if EV share becomes 80%?")]
    assert p.chat(msg, TOOL_SPECS) == p.chat(msg, TOOL_SPECS)
    assert p.chat(msg, TOOL_SPECS).tool_calls == (ToolCall("simulate_strategy", {"final_shares": {"ev_adoption": 0.8}}),)


@pytest.mark.parametrize("text,call", [
    ("Explain the selected strategy.", ("simulate_strategy", {"start_from": "selected_strategy"})),
    ("Show the baseline forecast.", ("get_baseline", {})),
    ("Find a plan within a £500k budget.", ("optimize_strategies", {"budget_gbp": 500000.0})),
    ("budget of 1.2m please", ("optimize_strategies", {"budget_gbp": 1200000.0})),
    ("How likely are we to meet our target?", ("get_risk_summary", {})),
    ("set renewable share to 60 percent", ("simulate_strategy", {"final_shares": {"renewable_energy": 0.6}})),
    ("EV adoption fraction 0.5 of the remaining", ("simulate_strategy", {"actions": {"ev_adoption": 0.5}})),
])
def test_mock_intents(text, call):
    r = MockChatProvider().chat([ChatMessage("user", text)], TOOL_SPECS)
    assert r.tool_calls == (ToolCall(*call),)


def test_mock_asks_for_clarification_on_ambiguous_percent_and_unknown_requests():
    p = MockChatProvider()
    r = p.chat([ChatMessage("user", "EV share 80")], TOOL_SPECS)
    assert not r.tool_calls and "Do you mean" in r.text
    r = p.chat([ChatMessage("user", "tell me a joke")], TOOL_SPECS)
    assert not r.tool_calls and "I can help with" in r.text


def test_mock_connection_check_has_no_network():
    assert MockChatProvider().check_connection().ok
