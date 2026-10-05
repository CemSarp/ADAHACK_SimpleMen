"""Model providers: Ollama (native /api/chat), LM Studio (OpenAI-compatible /v1) and a deterministic mock.

Transport details stay in this module. Nothing here touches the network at
import time or constructs a connection until `chat()` is called. A remote failure raises a typed ChatProviderError; the mock
is never substituted for it.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from src.contracts.errors import CarbonOptError
from src.contracts.types import ProviderInfo

from .config import ChatbotConfig, ChatConfigurationError
from .summaries import summarize_payload
from .types import ChatMessage, ModelResponse, ToolCall, ToolSpec

MOCK_VERSION = "mock-chat-v1"


class ChatProviderError(CarbonOptError, RuntimeError):
    """Base class for model-provider failures."""


class ChatConnectionError(ChatProviderError):
    """Endpoint unreachable (DNS, refused, TLS)."""


class ChatTimeoutError(ChatProviderError):
    """The request exceeded the configured timeout."""


class ChatServerError(ChatProviderError):
    """HTTP error status from the server (including unknown model)."""

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        super().__init__(f"HTTP {status}: {detail}")


class ChatInvalidResponse(ChatProviderError):
    """The server answered, but not with a usable chat response."""


@runtime_checkable
class ChatModelProvider(Protocol):
    info: ProviderInfo

    def chat(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]) -> ModelResponse: ...


# --------------------------------------------------------------------------- #
# Ollama
# --------------------------------------------------------------------------- #

# (method, url, json_body_or_None, headers, timeout_seconds) -> (status, body_bytes)
Transport = Callable[[str, str, "dict[str, Any] | None", Mapping[str, str], float], "tuple[int, bytes]"]


def urllib_transport(method: str, url: str, body: dict[str, Any] | None, headers: Mapping[str, str],
                     timeout: float) -> tuple[int, bytes]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme validated in config
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except TimeoutError as exc:
        raise ChatTimeoutError(f"request timed out after {timeout:g}s") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ChatTimeoutError(f"request timed out after {timeout:g}s") from exc
        raise ChatConnectionError(f"cannot reach the Ollama endpoint: {exc.reason}") from exc
    except OSError as exc:
        raise ChatConnectionError(f"cannot reach the Ollama endpoint: {exc}") from exc


def _tool_to_wire(tool: ToolSpec) -> dict[str, Any]:
    return {"type": "function", "function": {"name": tool.name, "description": tool.description,
                                              "parameters": dict(tool.parameters)}}


def _message_to_wire(m: ChatMessage) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.role == "tool" and m.tool_name:
        wire["tool_name"] = m.tool_name
    if m.tool_calls:
        wire["tool_calls"] = [{"type": "function", "function": {"name": c.name, "arguments": dict(c.arguments)}}
                              for c in m.tool_calls]
    return wire


def _parse_tool_calls(raw_calls: Any) -> list[ToolCall]:
    """Shared validation of model tool calls; arguments may arrive as an object or a JSON string."""
    calls = []
    for i, raw in enumerate(raw_calls or []):
        fn = raw.get("function") if isinstance(raw, dict) else None
        if not isinstance(fn, dict) or not isinstance(fn.get("name"), str) or not fn["name"]:
            raise ChatInvalidResponse(f"tool_calls[{i}] has no function name")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError as exc:
                raise ChatInvalidResponse(f"tool_calls[{i}] arguments are not valid JSON") from exc
        if not isinstance(args, dict):
            raise ChatInvalidResponse(f"tool_calls[{i}] arguments must be an object")
        call_id = raw.get("id")
        calls.append(ToolCall(name=fn["name"], arguments=args, id=call_id if isinstance(call_id, str) else None))
    return calls


class OllamaChatProvider:
    PROVIDER = "ollama"

    def __init__(self, config: ChatbotConfig, *, transport: Transport = urllib_transport) -> None:
        if config.provider != self.PROVIDER:
            raise ChatConfigurationError(f"{type(self).__name__} needs CHATBOT_PROVIDER={self.PROVIDER}")
        config.validate()
        self._config = config
        self._transport = transport
        self._base = (config.base_url or "").rstrip("/")
        self.info = ProviderInfo(slot="chat", name=f"{self.PROVIDER}:{config.model}", version=config.model,
                                 is_mock=False, kind="real")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        status, raw = self._transport(method, f"{self._base}{path}", body, self._headers(), self._config.timeout_seconds)
        text = raw.decode("utf-8", errors="replace") if raw else ""
        if status >= 400:
            detail = text
            try:
                err = json.loads(text).get("error", text)
                detail = str(err.get("message", err) if isinstance(err, dict) else err)
            except (ValueError, AttributeError):
                pass
            raise ChatServerError(status, detail[:300] or "no detail")
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ChatInvalidResponse("server returned non-JSON content") from exc
        if not isinstance(data, dict):
            raise ChatInvalidResponse("server returned an unexpected JSON shape")
        return data

    def chat(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]) -> ModelResponse:
        body = {
            "model": self._config.model,
            "messages": [_message_to_wire(m) for m in messages],
            "tools": [_tool_to_wire(t) for t in tools],
            "stream": False,
            "options": {"temperature": 0, "num_predict": self._config.max_output_tokens},
        }
        data = self._request("POST", "/api/chat", body)
        message = data.get("message")
        if not isinstance(message, dict):
            raise ChatInvalidResponse("response has no 'message' object")
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ChatInvalidResponse("message.content must be a string")
        calls = _parse_tool_calls(message.get("tool_calls"))
        if not content.strip() and not calls:
            raise ChatInvalidResponse("model returned neither text nor a tool call")
        return ModelResponse(text=content, tool_calls=tuple(calls))


# --------------------------------------------------------------------------- #
# LM Studio (OpenAI-compatible chat completions)
# --------------------------------------------------------------------------- #

_THINKING = re.compile(r"<think>.*?</think>", re.DOTALL)
OUT_OF_BUDGET = ("I ran out of room while working this out, so I have no answer yet. Please ask a narrower question, "
                 "for example one topic at a time, or raise LMSTUDIO_MAX_OUTPUT_TOKENS.")


def _message_to_openai(m: ChatMessage, index: int) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.role == "tool":
        wire["tool_call_id"] = m.tool_call_id
    if m.tool_calls:
        wire["tool_calls"] = [{"id": c.id or f"call_{index}_{i}", "type": "function",
                               "function": {"name": c.name, "arguments": json.dumps(dict(c.arguments))}}
                              for i, c in enumerate(m.tool_calls)]
    return wire


class LMStudioChatProvider(OllamaChatProvider):
    """LM Studio's local server. Same validation and errors as Ollama; OpenAI wire format."""

    PROVIDER = "lmstudio"

    def chat(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]) -> ModelResponse:
        wire = [_message_to_openai(m, i) for i, m in enumerate(messages)]
        # Every tool result must echo the id of the call it answers; pair id-less results in call order.
        pending: list[str] = []
        for i, w in enumerate(wire):
            if w.get("tool_calls"):
                pending = [c["id"] for c in w["tool_calls"]]
            elif w["role"] == "tool":
                if w["tool_call_id"] in pending:
                    pending.remove(w["tool_call_id"])
                else:
                    w["tool_call_id"] = pending.pop(0) if pending else f"call_{i}"
        body = {
            "model": self._config.model,
            "messages": wire,
            "tools": [_tool_to_wire(t) for t in tools],
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": self._config.max_output_tokens,
            "stream": False,
        }
        data = self._request("POST", "/chat/completions", body)
        choices = data.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise ChatInvalidResponse("response has no choices[0].message object")
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ChatInvalidResponse("message.content must be a string")
        content = _THINKING.sub("", content).strip()  # some local models inline their reasoning
        calls = _parse_tool_calls(message.get("tool_calls"))
        calls = [c if c.id else ToolCall(c.name, c.arguments, id=f"call_{i}") for i, c in enumerate(calls)]
        if not content and not calls and choices[0].get("finish_reason") == "length":
            return ModelResponse(text=OUT_OF_BUDGET)  # spent the whole budget thinking; say so instead of failing
        if not content and not calls:
            raise ChatInvalidResponse("model returned neither text nor a tool call")
        return ModelResponse(text=content, tool_calls=tuple(calls))


# --------------------------------------------------------------------------- #
# Mock
# --------------------------------------------------------------------------- #

_HELP = (
    "I can help with: where your emissions come from, comparing the six actions, explaining the selected "
    "strategy, showing the baseline forecast, previewing a what-if (for example 'EV share becomes 80%'), finding a "
    "plan within a budget (for example 'within a £500k budget'), risk for the selected strategy, and the Wincanton "
    "real-data reference. Tell me which one you want."
)
_NUM = r"(\d+(?:\.\d+)?)"


def _money(text: str) -> float | None:
    m = re.search(r"[£$]?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|million)?\b", text)
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    return value * {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}.get(unit, 1.0)


class MockChatProvider:
    """Deterministic rule-based stand-in. It is NOT a language model."""

    def __init__(self) -> None:
        self.info = ProviderInfo(slot="chat", name="mock-chat-model", version=MOCK_VERSION, is_mock=True,
                                 kind="behavioral-mock")

    def chat(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]) -> ModelResponse:
        last_user = max((i for i, m in enumerate(messages) if m.role == "user"), default=None)
        if last_user is None:
            return ModelResponse(text=_HELP)
        tool_msgs = [m for m in messages[last_user + 1:] if m.role == "tool"]
        if tool_msgs:
            return ModelResponse(text="\n\n".join(summarize_payload(json.loads(m.content)) for m in tool_msgs))
        return self._interpret(messages[last_user].content)

    def _interpret(self, text: str) -> ModelResponse:
        t = text.lower().strip()
        share = re.search(rf"\b(ev|electric|renewable)\w*\b[^0-9]*{_NUM}\s*(%|percent)?", t)
        if share:
            action = "renewable_energy" if share.group(1) == "renewable" else "ev_adoption"
            number, has_pct = float(share.group(2)), bool(share.group(3))
            fraction_wording = "fraction" in t or "of the remaining" in t or "of remaining" in t
            if not has_pct and number > 1.0:
                return ModelResponse(text=f"Do you mean a final share of {number:g}% or {number:g}? "
                                          f"Please state it as a percentage (for example {number:g}%) or a 0-1 ratio.")
            ratio = number / 100.0 if has_pct else number
            key = "actions" if fraction_wording else "final_shares"
            return ModelResponse(text="", tool_calls=(ToolCall("simulate_strategy", {key: {action: ratio}}),))
        if re.search(r"\b(budget|optimi[sz]e|find a plan|best plan)\b", t):
            amount = _money(t)
            args = {} if amount is None else {"budget_gbp": amount}
            return ModelResponse(text="", tool_calls=(ToolCall("optimize_strategies", args),))
        if re.search(r"\b(likely|probab\w*|chance|risk)\b", t):
            return ModelResponse(text="", tool_calls=(ToolCall("get_risk_summary", {}),))
        if re.search(r"\b(explain|describe)\b", t) and re.search(r"\b(selected|strategy|plan)\b", t):
            return ModelResponse(text="", tool_calls=(ToolCall("simulate_strategy", {"start_from": "selected_strategy"}),))
        if re.search(r"\b(wincanton|real data|scopes?)\b", t):
            return ModelResponse(text="", tool_calls=(ToolCall("get_public_reference", {}),))
        if re.search(r"\b(which action|actions|levers?|most effective|cheapest)\b", t):
            return ModelResponse(text="", tool_calls=(ToolCall("compare_actions", {}),))
        if re.search(r"(come from|\bcompany\b|\bprofile\b|\btrend|\bhistory\b|last 12 months)", t):
            return ModelResponse(text="", tool_calls=(ToolCall("get_company_profile", {}),))
        if re.search(r"\b(baseline|forecast)\b", t):
            return ModelResponse(text="", tool_calls=(ToolCall("get_baseline", {}),))
        return ModelResponse(text=_HELP)


def create_chat_provider(config: ChatbotConfig, *, transport: Transport = urllib_transport) -> ChatModelProvider:
    config.validate()
    if config.provider == "mock":
        return MockChatProvider()
    if config.provider == "lmstudio":
        return LMStudioChatProvider(config, transport=transport)
    return OllamaChatProvider(config, transport=transport)
