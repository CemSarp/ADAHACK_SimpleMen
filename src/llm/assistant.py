"""Turn orchestration: model -> validated tool calls -> existing services -> grounded text.

Limits and safety implemented here:
- at most MAX_TOOL_EXECUTIONS_PER_MESSAGE backend executions per user message;
- identical tool calls in the same context are answered from the turn record
  (no second execution, no second count), which also makes Retry safe;
- invalid arguments are returned to the model without consuming an execution;
- provider failures raise and leave the turn record intact for a retry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Sequence

from src.contracts.identity import canonical_hash
from src.contracts.types import ToolResult

from .context import AnalysisContext
from .prompt import build_system_message
from .providers import ChatModelProvider
from .summaries import summarize_payload
from .tools import (
    MAX_TOOL_EXECUTIONS_PER_MESSAGE,
    TOOL_SPECS,
    ToolArgumentError,
    execute_tool,
    tool_result_payload,
    validate_arguments,
)
from .types import ChatMessage, ToolCall

MAX_MODEL_ROUNDS = 4
HISTORY_MESSAGES = 12
LIMIT_ERROR = f"tool execution limit reached ({MAX_TOOL_EXECUTIONS_PER_MESSAGE} per user message)"


@dataclass
class TurnRecord:
    """Mutable per-user-message record; survives a failed attempt for Retry."""

    executed: int = 0
    results: dict[str, ToolResult] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TurnOutcome:
    text: str
    results: tuple[ToolResult, ...]
    executed: int
    limit_hit: bool


def dispatch_key(call: ToolCall, context_version: str) -> str:
    return canonical_hash([call.name, _plain(call.arguments), context_version])


def _plain(value):
    return json.loads(json.dumps(value, default=str))


def run_turn(
    *,
    provider: ChatModelProvider,
    history: Sequence[ChatMessage],
    user_text: str,
    context: AnalysisContext,
    record: TurnRecord,
) -> TurnOutcome:
    messages: list[ChatMessage] = [
        ChatMessage("system", build_system_message(context.summary())),
        *list(history)[-HISTORY_MESSAGES:],
        ChatMessage("user", user_text),
    ]
    limit_hit = False
    final_text = ""
    for _ in range(MAX_MODEL_ROUNDS):
        response = provider.chat(messages, TOOL_SPECS)
        if not response.tool_calls:
            final_text = response.text.strip()
            break
        messages.append(ChatMessage("assistant", response.text, tool_calls=response.tool_calls))
        for call in response.tool_calls:
            key = dispatch_key(call, context.version)
            if key in record.results:
                result = record.results[key]  # duplicate or retry: no re-execution, no extra count
            else:
                try:
                    validate_arguments(call.name, dict(call.arguments))
                    valid = True
                except ToolArgumentError:
                    valid = False
                if valid and record.executed >= MAX_TOOL_EXECUTIONS_PER_MESSAGE:
                    limit_hit = True
                    result = ToolResult("error", call.name, {}, None, LIMIT_ERROR)
                else:
                    result = execute_tool(call.name, dict(call.arguments), context=context, services=context.services)
                    if valid:
                        record.executed += 1
                record.results[key] = result
                record.order.append(key)
            messages.append(ChatMessage("tool", json.dumps(tool_result_payload(result), allow_nan=False),
                                        tool_name=call.name, tool_call_id=call.id))
    results = tuple(record.results[k] for k in record.order)
    if not final_text:
        last = results[-1] if results else None
        final_text = summarize_payload(tool_result_payload(last)) if last else (
            "I could not produce an answer. Please rephrase your request.")
    if limit_hit:
        final_text += f"\n\nNote: I stopped after {MAX_TOOL_EXECUTIONS_PER_MESSAGE} tool executions for this message."
    return TurnOutcome(text=final_text, results=results, executed=record.executed, limit_hit=limit_hit)

