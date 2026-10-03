"""Provider-neutral chat types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]
    id: str | None = None  # OpenAI-style providers pair each tool result with its call id


@dataclass(frozen=True)
class ChatMessage:
    """role: system | user | assistant | tool. Tool messages name their tool."""

    role: str
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class ConnectionStatus:
    ok: bool
    detail: str
    models: tuple[str, ...] = field(default_factory=tuple)
