"""Structured-output validation, retry with backoff, and the dead-letter path."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from conftest import HOT_LEAD
from leadflow.classifier import (
    CLASSIFICATION_SCHEMA,
    ClassificationFailedError,
    LeadClassifier,
    parse_classification,
)
from leadflow.llm import FakeProvider, LLMProviderError
from leadflow.llm.fake import heuristic_classification
from leadflow.models import RawLead
from leadflow.normalize import build_lead
from leadflow.pipeline import LeadPipeline

VALID = json.dumps(heuristic_classification(HOT_LEAD))


class ScriptedProvider:
    """Returns (or raises) the scripted responses in order."""

    name = "scripted"

    def __init__(self, *responses: str | Exception) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete_structured(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        self.prompts.append(user)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_schema_is_self_contained_and_strict() -> None:
    assert "$defs" not in json.dumps(CLASSIFICATION_SCHEMA)
    assert CLASSIFICATION_SCHEMA["additionalProperties"] is False
    assert CLASSIFICATION_SCHEMA["properties"]["fit_score"]["maximum"] == 100


def test_parse_accepts_json_fence() -> None:
    assert parse_classification(f"```json\n{VALID}\n```").fit_score >= 0


def test_retries_with_exponential_backoff_then_succeeds() -> None:
    sleeps: list[float] = []
    provider = ScriptedProvider(
        "not json",
        json.dumps({**json.loads(VALID), "fit_score": 140}),
        LLMProviderError("429"),
        VALID,
    )
    classifier = LeadClassifier(provider, max_retries=3, base_delay=0.5, sleep=sleeps.append)
    result, attempts = classifier.classify(build_lead(RawLead(**HOT_LEAD)))
    assert attempts == 4
    assert sleeps == [0.5, 1.0, 2.0]
    assert "rejected by the validator" in provider.prompts[1]  # error fed back to the model
    assert result.intent == "quote_request"


def test_gives_up_after_max_retries() -> None:
    provider = ScriptedProvider(*["{}"] * 4)
    classifier = LeadClassifier(provider, max_retries=3, sleep=lambda _: None)
    with pytest.raises(ClassificationFailedError) as exc:
        classifier.classify(build_lead(RawLead(**HOT_LEAD)))
    assert len(exc.value.errors) == 4
    assert "Field required" in exc.value.errors[-1]


def test_failed_classification_lands_in_dead_letter_queue(
    make_pipeline: Callable[..., LeadPipeline], db_path: Path
) -> None:
    pipeline = make_pipeline(ScriptedProvider(*["oops"] * 4))
    outcome = pipeline.process(HOT_LEAD)
    assert outcome.status == "dead_letter"
    assert outcome.llm_attempts == 4

    rows = (
        sqlite3.connect(db_path)
        .execute("SELECT stage, error, payload FROM dead_letters")
        .fetchall()
    )
    assert len(rows) == 1
    stage, error, payload = rows[0]
    assert stage == "classification"
    assert "attempt 4" in error
    assert json.loads(payload)["email"] == HOT_LEAD["email"]
    assert pipeline.notifier.sent[-1][0].startswith("Dead letter")  # type: ignore[attr-defined]

    # The claim was released: resubmitting retries instead of being deduped.
    pipeline.classifier.provider = ScriptedProvider(VALID)
    assert pipeline.process(HOT_LEAD).status == "processed"


def test_fake_provider_failures_are_seeded_and_reproducible() -> None:
    def run(seed: int) -> list[str]:
        provider = FakeProvider(failure_rate=0.5, seed=seed)
        user = f"<lead>\n{json.dumps({**HOT_LEAD, 'dedupe_key': 'k'})}\n</lead>"
        return [provider.complete_structured(system="", user=user, schema={}) for _ in range(6)]

    assert run(1) == run(1)
    assert run(1) != run(2)
