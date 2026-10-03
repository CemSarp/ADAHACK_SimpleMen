"""Chatbot configuration from environment variables. Pure: no network, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

PROVIDERS = ("mock", "ollama", "lmstudio")
DEFAULT_MODEL = "llama3.1:8b"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_OUTPUT_TOKENS = 512
# Env-var prefix and defaults per provider: (base_url, model, timeout_seconds, max_output_tokens).
ENV_PREFIX = {"mock": "OLLAMA", "ollama": "OLLAMA", "lmstudio": "LMSTUDIO"}
PROVIDER_DEFAULTS = {
    "mock": (None, DEFAULT_MODEL, DEFAULT_TIMEOUT_SECONDS, DEFAULT_MAX_OUTPUT_TOKENS),
    "ollama": (None, DEFAULT_MODEL, DEFAULT_TIMEOUT_SECONDS, DEFAULT_MAX_OUTPUT_TOKENS),
    # LM Studio's OpenAI-compatible server on this machine. Reasoning models such as Gemma 4 spend output tokens
    # thinking before they answer, so the budget and timeout leave room for that.
    "lmstudio": ("http://localhost:1234/v1", "google/gemma-4-12b", 300.0, 4096),
}
MAX_TIMEOUT_SECONDS = 600.0
MAX_OUTPUT_TOKENS_LIMIT = 8192


class ChatConfigurationError(ValueError):
    """Chatbot configuration is invalid or incomplete. Never replaced by mock."""


@dataclass(frozen=True)
class ChatbotConfig:
    provider: str = "mock"
    base_url: str | None = None
    model: str = DEFAULT_MODEL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    api_key: str | None = None

    def __repr__(self) -> str:  # never leak the token
        key = "<set>" if self.api_key else None
        return (f"ChatbotConfig(provider={self.provider!r}, base_url={self.base_url!r}, model={self.model!r}, "
                f"timeout_seconds={self.timeout_seconds!r}, max_output_tokens={self.max_output_tokens!r}, api_key={key})")

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "ChatbotConfig":
        provider = (environ.get("CHATBOT_PROVIDER") or "mock").strip().lower()
        if provider not in PROVIDERS:
            raise ChatConfigurationError(f"CHATBOT_PROVIDER must be one of {list(PROVIDERS)}, got {provider!r}")
        env = ENV_PREFIX[provider]
        default_url, default_model, default_timeout, default_tokens = PROVIDER_DEFAULTS[provider]
        base_url = (environ.get(f"{env}_BASE_URL") or "").strip() or default_url
        model = (environ.get(f"{env}_MODEL") or "").strip() or default_model
        timeout = _number(environ, f"{env}_TIMEOUT_SECONDS", default_timeout, float)
        tokens = _number(environ, f"{env}_MAX_OUTPUT_TOKENS", default_tokens, int)
        api_key = (environ.get(f"{env}_API_KEY") or "").strip() or None
        config = cls(provider=provider, base_url=base_url, model=model, timeout_seconds=timeout,
                     max_output_tokens=tokens, api_key=api_key)
        config.validate()
        return config

    def validate(self) -> "ChatbotConfig":
        if self.provider not in PROVIDERS:
            raise ChatConfigurationError(f"CHATBOT_PROVIDER must be one of {list(PROVIDERS)}")
        env = ENV_PREFIX[self.provider]
        if not 0 < self.timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ChatConfigurationError(f"{env}_TIMEOUT_SECONDS must be within (0, {MAX_TIMEOUT_SECONDS:g}]")
        if not 0 < self.max_output_tokens <= MAX_OUTPUT_TOKENS_LIMIT:
            raise ChatConfigurationError(f"{env}_MAX_OUTPUT_TOKENS must be within (0, {MAX_OUTPUT_TOKENS_LIMIT}]")
        if self.provider != "mock":
            if not self.base_url:
                raise ChatConfigurationError(
                    f"CHATBOT_PROVIDER={self.provider} requires {env}_BASE_URL; "
                    "the mock is not used as a fallback")
            parts = urlsplit(self.base_url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ChatConfigurationError(f"{env}_BASE_URL must look like http(s)://host[:port]")
            if parts.username or parts.password:
                raise ChatConfigurationError(f"{env}_BASE_URL must not contain credentials; use {env}_API_KEY")
            if parts.query or parts.fragment:
                raise ChatConfigurationError(f"{env}_BASE_URL must not contain a query or fragment")
        return self


def _number(environ: Mapping[str, str], name: str, default: float | int, cast: type) -> float | int:
    raw = (environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ChatConfigurationError(f"{name} must be a number, got {raw!r}") from None
