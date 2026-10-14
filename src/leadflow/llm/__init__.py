"""LLM providers behind a single port."""

from __future__ import annotations

from leadflow.config import Settings
from leadflow.llm.base import LLMProvider, LLMProviderError
from leadflow.llm.fake import FakeProvider

__all__ = ["FakeProvider", "LLMProvider", "LLMProviderError", "build_provider"]


def build_provider(settings: Settings) -> LLMProvider:
    """Real providers are strictly opt-in via LLM_PROVIDER so a stray API key in
    the environment never turns a local demo into billable traffic."""
    if settings.llm_provider == "fake":
        return FakeProvider(settings.fake_failure_rate, settings.fake_seed)
    if settings.llm_provider == "anthropic":
        from leadflow.llm.anthropic_provider import AnthropicProvider  # noqa: PLC0415

        key = settings.require("anthropic_api_key")
        return AnthropicProvider(key, settings.llm_model or "claude-sonnet-4-5")
    if settings.llm_provider == "openai":
        from leadflow.llm.openai_provider import OpenAIProvider  # noqa: PLC0415

        return OpenAIProvider(
            settings.require("openai_api_key"), settings.llm_model or "gpt-4o-mini"
        )
    raise ValueError(f"Unknown LLM_PROVIDER={settings.llm_provider!r} (fake|anthropic|openai)")
