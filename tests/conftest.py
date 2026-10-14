from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from leadflow.classifier import LeadClassifier
from leadflow.llm import FakeProvider
from leadflow.llm.base import LLMProvider
from leadflow.notify import ConsoleNotifier
from leadflow.pipeline import LeadPipeline
from leadflow.sinks import SQLiteCrmSink
from leadflow.store import LeadStore

HOT_LEAD: dict[str, Any] = {
    "name": "Laura Méndez",
    "email": "laura@tallo-verde.example",
    "company": "Tallo Verde Agro SAS",
    "phone": "310 555 0101",
    "source": "web_form",
    "message": "Queremos automatizar los pedidos de WhatsApp e integrarlos con el CRM. "
    "Presupuesto USD 8,000, lo necesitamos lo antes posible. ¿Nos envían una cotización?",
}


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Belt and braces: tests never see real provider configuration."""
    for var in ("LLM_PROVIDER", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SLACK_WEBHOOK_URL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "leadflow.db"


@pytest.fixture
def make_pipeline(db_path: Path) -> Callable[..., LeadPipeline]:
    def factory(provider: LLMProvider | None = None, max_retries: int = 3) -> LeadPipeline:
        classifier = LeadClassifier(
            provider or FakeProvider(), max_retries=max_retries, sleep=lambda _: None
        )
        return LeadPipeline(
            classifier=classifier,
            store=LeadStore(db_path),
            sink=SQLiteCrmSink(db_path),
            notifier=ConsoleNotifier(),
        )

    return factory
