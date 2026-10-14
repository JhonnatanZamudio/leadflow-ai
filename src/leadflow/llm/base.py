"""The LLM port. Providers return raw text; validation happens in one place
(the classifier), so every provider is held to the same contract."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class LLMProviderError(RuntimeError):
    """Transport/API failure (timeouts, rate limits, refusals). Retryable."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete_structured(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        """Return a JSON string that *should* match `schema`. It may not."""
        ...
