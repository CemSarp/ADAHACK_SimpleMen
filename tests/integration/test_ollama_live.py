"""Opt-in remote smoke check. Skipped unless RUN_OLLAMA_LIVE_SMOKE=1 and an endpoint is configured.

    RUN_OLLAMA_LIVE_SMOKE=1 CHATBOT_PROVIDER=ollama OLLAMA_BASE_URL=https://<host> \
        python -m pytest tests/integration/test_ollama_live.py -q

Never run in CI by default. A pass here is the first real evidence of live model
behavior; until then the remote path is verified only against a fake transport.
"""

from __future__ import annotations

import os

import pytest

from src.integration import run_analysis
from src.llm.assistant import TurnRecord, run_turn
from src.llm.config import ChatbotConfig
from src.llm.context import AnalysisContext
from src.llm.providers import create_chat_provider
from tests.mocks import make_services

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_OLLAMA_LIVE_SMOKE") != "1" or not os.environ.get("OLLAMA_BASE_URL"),
    reason="live Ollama smoke test is opt-in (RUN_OLLAMA_LIVE_SMOKE=1 and OLLAMA_BASE_URL)",
)


def test_live_tool_call(request_ok):
    provider = create_chat_provider(ChatbotConfig.from_env({**os.environ, "CHATBOT_PROVIDER": "ollama"}))
    services = make_services()
    analysis = run_analysis(request_ok, services=services)
    ctx = AnalysisContext(services, request_ok, analysis.baseline, analysis, None)
    out = run_turn(provider=provider, history=[], user_text="Show the baseline forecast.", context=ctx, record=TurnRecord())
    assert out.text and any(r.tool_name == "get_baseline" and r.status == "ok" for r in out.results)
