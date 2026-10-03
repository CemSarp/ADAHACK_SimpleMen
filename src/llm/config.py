"""Chatbot configuration from environment variables. Pure: no network, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

PROVIDERS = ("mock", "ollama")
DEFAULT_MODEL = "llama3.1:8b"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_OUTPUT_TOKENS = 512
MAX_TIMEOUT_SECONDS = 600.0
MAX_OUTPUT_TOKENS_LIMIT = 4096


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
        base_url = (environ.get("OLLAMA_BASE_URL") or "").strip() or None
        model = (environ.get("OLLAMA_MODEL") or "").strip() or DEFAULT_MODEL
        timeout = _number(environ, "OLLAMA_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, float)
        tokens = _number(environ, "OLLAMA_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS, int)
        api_key = (environ.get("OLLAMA_API_KEY") or "").strip() or None
        config = cls(provider=provider, base_url=base_url, model=model, timeout_seconds=timeout,
                     max_output_tokens=tokens, api_key=api_key)
        config.validate()
        return config

    def validate(self) -> "ChatbotConfig":
        if self.provider not in PROVIDERS:
            raise ChatConfigurationError(f"CHATBOT_PROVIDER must be one of {list(PROVIDERS)}")
        if not 0 < self.timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ChatConfigurationError(f"OLLAMA_TIMEOUT_SECONDS must be within (0, {MAX_TIMEOUT_SECONDS:g}]")
        if not 0 < self.max_output_tokens <= MAX_OUTPUT_TOKENS_LIMIT:
            raise ChatConfigurationError(f"OLLAMA_MAX_OUTPUT_TOKENS must be within (0, {MAX_OUTPUT_TOKENS_LIMIT}]")
        if self.provider == "ollama":
            if not self.base_url:
                raise ChatConfigurationError(
                    "CHATBOT_PROVIDER=ollama requires OLLAMA_BASE_URL (the remote Ollama endpoint); "
                    "no local server is assumed and the mock is not used as a fallback")
            parts = urlsplit(self.base_url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ChatConfigurationError("OLLAMA_BASE_URL must look like http(s)://host[:port]")
            if parts.username or parts.password:
                raise ChatConfigurationError("OLLAMA_BASE_URL must not contain credentials; use OLLAMA_API_KEY")
            if parts.query or parts.fragment:
                raise ChatConfigurationError("OLLAMA_BASE_URL must not contain a query or fragment")
        return self


def _number(environ: Mapping[str, str], name: str, default: float | int, cast: type) -> float | int:
    raw = (environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ChatConfigurationError(f"{name} must be a number, got {raw!r}") from None
