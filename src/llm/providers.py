"""Model providers: remote Ollama (native /api/chat) and a deterministic mock.

Transport details stay in this module. Nothing here touches the network at
import time or constructs a connection until `chat()` / `check_connection()` is
called explicitly. A remote failure raises a typed ChatProviderError; the mock
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
from .types import ChatMessage, ConnectionStatus, ModelResponse, ToolCall, ToolSpec

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

    def check_connection(self) -> ConnectionStatus: ...


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


class OllamaChatProvider:
    def __init__(self, config: ChatbotConfig, *, transport: Transport = urllib_transport) -> None:
        if config.provider != "ollama":
            raise ChatConfigurationError("OllamaChatProvider needs CHATBOT_PROVIDER=ollama")
        config.validate()
        self._config = config
        self._transport = transport
        self._base = (config.base_url or "").rstrip("/")
        self.info = ProviderInfo(slot="chat", name=f"ollama:{config.model}", version=config.model, is_mock=False,
                                 kind="real")

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
                detail = str(json.loads(text).get("error", text))
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
        calls = []
        for i, raw in enumerate(message.get("tool_calls") or []):
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
            calls.append(ToolCall(name=fn["name"], arguments=args))
        if not content.strip() and not calls:
            raise ChatInvalidResponse("model returned neither text nor a tool call")
        return ModelResponse(text=content, tool_calls=tuple(calls))

    def check_connection(self) -> ConnectionStatus:
        """Explicit user action: list models and confirm the configured tag exists."""
        data = self._request("GET", "/api/tags", None)
        names = tuple(str(m.get("name") or m.get("model")) for m in data.get("models", []) if isinstance(m, dict))
        wanted = self._config.model
        present = wanted in names or (":" not in wanted and f"{wanted}:latest" in names)
        if present:
            return ConnectionStatus(True, f"Connected; model {wanted} is available.", names)
        return ConnectionStatus(False, f"Connected, but model {wanted} is not listed on the server.", names)


# --------------------------------------------------------------------------- #
# Mock
# --------------------------------------------------------------------------- #

_HELP = (
    "I can help with: explaining the selected strategy, showing the baseline forecast, previewing a what-if "
    "(for example 'EV share becomes 80%'), finding a plan within a budget (for example 'within a £500k budget'), "
    "and showing risk for the selected strategy. Tell me which one you want."
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

    def check_connection(self) -> ConnectionStatus:
        return ConnectionStatus(True, "Mock model: no network connection is used.")

    def chat(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]) -> ModelResponse:
        last_user = max((i for i, m in enumerate(messages) if m.role == "user"), default=None)
        if last_user is None:
            return ModelResponse(text=_HELP)
        tool_msgs = [m for m in messages[last_user + 1:] if m.role == "tool"]
        if tool_msgs:
            return ModelResponse(text="\n\n".join(summarize_payload(json.loads(m.content)) for m in tool_msgs))
        return self._interpret(messages[last_user].content, messages[:last_user])

    def _interpret(self, text: str, history: Sequence[ChatMessage]) -> ModelResponse:
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
        if re.search(r"\b(baseline|forecast)\b", t):
            return ModelResponse(text="", tool_calls=(ToolCall("get_baseline", {}),))
        return ModelResponse(text=_HELP)


def create_chat_provider(config: ChatbotConfig, *, transport: Transport = urllib_transport) -> ChatModelProvider:
    config.validate()
    if config.provider == "mock":
        return MockChatProvider()
    return OllamaChatProvider(config, transport=transport)
