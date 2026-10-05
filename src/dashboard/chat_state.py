"""Chat conversation state over a session mapping (no Streamlit import).

Uses its own key prefix (`coc_`), separate from the dashboard's `cos_`, so
clearing chat never resets the dashboard and a dashboard provider change never
deletes the conversation (old result cards are marked stale instead).
"""

from __future__ import annotations

from typing import Any, MutableMapping

from src.contracts.errors import CarbonOptError
from src.llm.assistant import TurnRecord, run_turn
from src.llm.config import ChatConfigurationError
from src.llm.context import AnalysisContext
from src.llm.providers import ChatModelProvider
from src.llm.tools import tool_result_payload
from src.llm.types import ChatMessage

PREFIX = "coc_"
MAX_USER_CHARS = 1000

SUGGESTIONS = (
    "Explain the selected strategy.",
    "Show the baseline forecast.",
    "What if EV share becomes 80%?",
    "Find a plan within a £500k budget.",
    "How likely are we to meet our target?",
    "Where do our emissions come from?",
    "Which action cuts the most CO₂?",
)


class ChatState:
    def __init__(self, store: MutableMapping[str, Any]) -> None:
        self.store = store

    def _get(self, name: str, default: Any = None) -> Any:
        return self.store.get(PREFIX + name, default)

    def _set(self, name: str, value: Any) -> None:
        self.store[PREFIX + name] = value

    @property
    def is_open(self) -> bool:
        return bool(self._get("open", False))

    def set_open(self, value: bool) -> None:
        self._set("open", bool(value))

    @property
    def messages(self) -> list[dict[str, Any]]:
        return self._get("messages", [])

    def clear(self) -> None:
        for name in ("messages", "turns", "counter"):
            self.store.pop(PREFIX + name, None)

    def _next_id(self) -> int:
        n = int(self._get("counter", 0)) + 1
        self._set("counter", n)
        return n

    def _turns(self) -> dict[int, TurnRecord]:
        return self.store.setdefault(PREFIX + "turns", {})

    def submit(self, text: str) -> int | None:
        """Append a user message and return its turn id (None if empty/over limit)."""
        text = (text or "").strip()
        if not text:
            return None
        text = text[:MAX_USER_CHARS]
        turn = self._next_id()
        self._turns()[turn] = TurnRecord()
        self.store.setdefault(PREFIX + "messages", []).append(
            {"id": f"u{turn}", "role": "user", "content": text, "turn": turn, "cards": [], "error": None})
        return turn

    def _user_text(self, turn: int) -> str:
        return next(m["content"] for m in self.messages if m["role"] == "user" and m["turn"] == turn)

    def _history(self, turn: int) -> list[ChatMessage]:
        out: list[ChatMessage] = []
        for m in self.messages:
            if m["role"] == "user" and m["turn"] == turn:
                break
            if m["error"] is None:
                out.append(ChatMessage(m["role"], m["content"]))
        return out

    def pending_turn(self) -> int | None:
        """A user turn that has no assistant answer (or error) yet."""
        answered = {m["turn"] for m in self.messages if m["role"] == "assistant"}
        for m in self.messages:
            if m["role"] == "user" and m["turn"] not in answered:
                return m["turn"]
        return None

    def retry(self, turn: int) -> None:
        """Drop the failed answer so the turn is processed again with its record."""
        self._set("messages", [m for m in self.messages if not (m["role"] == "assistant" and m["turn"] == turn)])

    def process(self, turn: int, provider: ChatModelProvider | None, context: AnalysisContext | None,
                config_error: str | None = None) -> None:
        """Run one turn. Failures become a visible error message; user text is kept."""
        error: dict[str, str] | None = None
        outcome = None
        if config_error is not None:
            error = {"type": "ChatConfigurationError", "message": config_error}
        elif provider is None or context is None:
            error = {"type": "ContextUnavailable", "message": "The assistant needs a loaded baseline; wait for the dashboard to finish loading."}
        else:
            try:
                outcome = run_turn(provider=provider, history=self._history(turn), user_text=self._user_text(turn),
                                   context=context, record=self._turns()[turn])
            except (CarbonOptError, ChatConfigurationError) as exc:
                error = {"type": type(exc).__name__, "message": str(exc)}
        message: dict[str, Any] = {"id": f"a{turn}-{self._next_id()}", "role": "assistant", "turn": turn,
                                   "content": "", "cards": [], "error": error,
                                   "provider": None if provider is None else provider.info.name,
                                   "is_mock": bool(provider.info.is_mock) if provider is not None else False}
        if outcome is not None:
            message["content"] = outcome.text
            message["cards"] = [
                {"id": f"c{turn}-{i}", "context_version": context.version, **tool_result_payload(r)}
                for i, r in enumerate(outcome.results) if r.status == "ok"
            ]
            message["notices"] = [f"{r.tool_name}: {r.error}" for r in outcome.results if r.status != "ok"]
        self.store.setdefault(PREFIX + "messages", []).append(message)
