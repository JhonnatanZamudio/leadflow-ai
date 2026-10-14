"""OpenAI adapter using the `json_schema` response format."""

from __future__ import annotations

from typing import Any

from leadflow.llm.base import LLMProviderError


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout: float = 30.0) -> None:
        try:
            import openai  # noqa: PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover
            raise LLMProviderError("pip install 'leadflow-ai[openai]'") from exc
        self._openai = openai
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=0)
        self._model = model

    def complete_structured(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={
                    "type": "json_schema",
                    # strict=False: our own Pydantic validation is the source of truth.
                    "json_schema": {
                        "name": "lead_classification",
                        "schema": schema,
                        "strict": False,
                    },
                },
            )
        except self._openai.OpenAIError as exc:
            raise LLMProviderError(f"openai: {exc}") from exc
        content: str | None = response.choices[0].message.content
        if not content:
            raise LLMProviderError("openai: empty response")
        return content
