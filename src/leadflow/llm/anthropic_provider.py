"""Anthropic adapter. Structured output is enforced with a forced tool call whose
input_schema is the Classification JSON schema."""

from __future__ import annotations

import json
from typing import Any

from leadflow.llm.base import LLMProviderError

_TOOL_NAME = "record_lead_classification"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float = 30.0) -> None:
        try:
            import anthropic  # noqa: PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover
            raise LLMProviderError("pip install 'leadflow-ai[anthropic]'") from exc
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=0)
        self._model = model

    def complete_structured(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[
                    {
                        "name": _TOOL_NAME,
                        "description": "Record the triage classification of one inbound lead.",
                        "input_schema": schema,
                    }
                ],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
            )
        except self._anthropic.APIError as exc:
            raise LLMProviderError(f"anthropic: {exc}") from exc
        for block in response.content:
            if block.type == "tool_use" and block.name == _TOOL_NAME:
                return json.dumps(block.input)
        raise LLMProviderError(f"anthropic: no tool_use block (stop_reason={response.stop_reason})")
