"""Streamlit AppTest coverage of the floating assistant (offline, mock model)."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("CHATBOT_PROVIDER", "OLLAMA_BASE_URL", "OLLAMA_MODEL", "OLLAMA_API_KEY", "CARBONOPT_PROVIDER_MODE"):
        monkeypatch.delenv(name, raising=False)


APP = str(Path(__file__).resolve().parents[2] / "app.py")


def start() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def optimize(at):
    [b for b in at.button if b.label == "Optimize"][0].click().run()
    assert not at.exception


def texts(at):
    return [m.markdown[0].value for m in at.chat_message if m.markdown]


def test_p0_startup_without_any_chatbot_configuration():
    at = start()
    assert any("MOCK OUTPUT" in w.value for w in at.warning)
    assert at.button(key="cc_toggle") is not None  # closed bubble is present
    assert not at.chat_message and not at.chat_input  # panel not rendered while closed


def test_bubble_opens_closes_and_preserves_conversation():
    at = start()
    at.button(key="cc_toggle").click().run()
    assert at.chat_input and any("MOCK MODEL" in c.value for c in at.caption)
    at.button(key="cc_sugg_1").click().run()  # "Show the baseline forecast."
    assert not at.exception and "1,200.0 tCO2e" in " ".join(texts(at))
    at.button(key="cc_close").click().run()
    assert not at.chat_message and not at.chat_input
    at.button(key="cc_toggle").click().run()
    assert "1,200.0 tCO2e" in " ".join(texts(at))  # history survived close/reopen


@pytest.mark.parametrize("index", range(5))
def test_each_suggested_question_runs_without_error(index):
    at = start()
    optimize(at)
    at.button(key="cc_toggle").click().run()
    at.button(key=f"cc_sugg_{index}").click().run()
    assert not at.exception
    assert len(texts(at)) == 2  # the question and an answer (an error answer would be an st.error, not text)


def test_typed_message_returns_a_result_card():
    at = start()
    optimize(at)
    at.button(key="cc_toggle").click().run()
    at.chat_input[0].set_value("What if EV share becomes 80%?").run()
    assert not at.exception
    body = " ".join(texts(at))
    assert "80.0%" in body and "mock backend output" in body
    assert [b for b in at.button if b.label == "Apply to dashboard"]
    at.button(key="cc_clear").click().run()
    assert not at.chat_message


def test_what_if_is_a_preview_until_applied():
    at = start()
    optimize(at)
    selected = at.selectbox(key="co_widget_select").value
    at.button(key="cc_toggle").click().run()
    at.chat_input[0].set_value("What if EV share becomes 80%?").run()
    assert at.slider(key="co_slider_ev_adoption").value != 0.8  # nothing changed yet
    assert at.selectbox(key="co_widget_select").value == selected
    [b for b in at.button if b.label == "Apply to dashboard"][0].click().run()
    assert not at.exception
    assert at.slider(key="co_slider_ev_adoption").value == pytest.approx(0.8)
    assert at.selectbox(key="co_widget_select").value == selected  # selected plan never overwritten


def test_cards_become_stale_when_dashboard_inputs_change():
    at = start()
    optimize(at)
    at.button(key="cc_toggle").click().run()
    at.chat_input[0].set_value("What if EV share becomes 80%?").run()
    apply_btn = [b for b in at.button if b.label == "Apply to dashboard"][0]
    assert not apply_btn.disabled
    at.number_input(key="co_widget_budget").set_value(400000.0).run()
    assert not at.exception
    apply_btn = [b for b in at.button if b.label == "Apply to dashboard"][0]
    assert apply_btn.disabled
    assert any("previous analysis context" in c.value for c in at.caption)


def test_ollama_without_endpoint_shows_error_and_dashboard_keeps_working(monkeypatch):
    monkeypatch.setenv("CHATBOT_PROVIDER", "ollama")
    at = start()
    optimize(at)  # dashboard unaffected
    at.button(key="cc_toggle").click().run()
    assert any("Chatbot configuration error" in e.value for e in at.error)
    at.chat_input[0].set_value("hello").run()
    assert any("requires OLLAMA_BASE_URL" in e.value for e in at.error)
    assert not any("MOCK MODEL" in c.value and "answers use" in c.value for c in at.caption)  # no silent mock


def test_ollama_unreachable_endpoint_is_a_visible_error_with_retry(monkeypatch):
    monkeypatch.setenv("CHATBOT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")  # closed port; connection refused
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "2")
    at = start()
    at.button(key="cc_toggle").click().run()
    at.chat_input[0].set_value("Show the baseline forecast.").run()
    assert not at.exception
    assert any("ChatConnectionError" in e.value for e in at.error)
    assert any(b.label == "Retry" for b in at.button)
    assert not any(c.value.startswith(":orange-badge[MOCK MODEL]") for c in at.caption)


def test_invalid_provider_value_does_not_break_startup(monkeypatch):
    monkeypatch.setenv("CHATBOT_PROVIDER", "gpt")
    at = start()
    at.button(key="cc_toggle").click().run()
    assert any("CHATBOT_PROVIDER" in e.value for e in at.error)
