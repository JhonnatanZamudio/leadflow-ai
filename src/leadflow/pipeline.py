"""The use case: one lead in, one LeadOutcome out. Every input ends in exactly
one recorded status; nothing is dropped silently."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError, computed_field

from leadflow.classifier import ClassificationFailedError, LeadClassifier
from leadflow.config import Settings
from leadflow.llm import build_provider
from leadflow.models import (
    Lead,
    LeadOutcome,
    LeadStatus,
    ProcessedLead,
    RawLead,
    Route,
    Tier,
)
from leadflow.normalize import SPAM_THRESHOLD, LeadValidationError, build_lead, spam_check
from leadflow.notify import Notifier, build_notifier
from leadflow.rules import RoutingRules
from leadflow.sinks import CrmSink, build_sink
from leadflow.store import LeadStore


class RunStats(BaseModel):
    received: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_tier: dict[str, int] = Field(default_factory=dict)
    llm_calls: int = 0
    total_seconds: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def avg_ms_per_lead(self) -> float:
        return 1000 * self.total_seconds / self.received if self.received else 0.0


@dataclass
class LeadPipeline:
    classifier: LeadClassifier
    store: LeadStore
    sink: CrmSink
    notifier: Notifier
    rules: RoutingRules = field(default_factory=RoutingRules)
    default_country: str = "57"

    def process(self, payload: Mapping[str, Any] | RawLead) -> LeadOutcome:
        started = time.perf_counter()
        outcome = self._process(payload)
        outcome.duration_ms = round((time.perf_counter() - started) * 1000, 3)
        self.store.record_event(outcome)
        return outcome

    def process_many(
        self, payloads: Iterable[Mapping[str, Any] | RawLead]
    ) -> tuple[RunStats, list[LeadOutcome]]:
        started = time.perf_counter()
        outcomes = [self.process(payload) for payload in payloads]
        stats = RunStats(
            received=len(outcomes),
            by_status=dict(Counter(o.status.value for o in outcomes)),
            by_tier=dict(Counter(o.tier.value for o in outcomes if o.tier)),
            llm_calls=sum(o.llm_attempts for o in outcomes),
            total_seconds=time.perf_counter() - started,
        )
        return stats, outcomes

    def _process(self, payload: Mapping[str, Any] | RawLead) -> LeadOutcome:
        try:
            raw = payload if isinstance(payload, RawLead) else RawLead.model_validate(payload)
            lead = build_lead(raw, self.default_country)
        except LeadValidationError as exc:
            return LeadOutcome(
                status=LeadStatus.INVALID,
                errors=exc.errors,
                email=_get(payload, "email"),
                name=_get(payload, "name"),
            )
        except ValidationError as exc:
            return LeadOutcome(
                status=LeadStatus.INVALID, errors=[str(e["msg"]) for e in exc.errors()]
            )

        ids: dict[str, Any] = {
            "dedupe_key": lead.dedupe_key,
            "name": lead.name,
            "email": lead.email,
            "company": lead.company,
        }
        if not self.store.claim(lead.dedupe_key):
            return LeadOutcome(status=LeadStatus.DUPLICATE, reasons=["same email + message"], **ids)

        score, signals = spam_check(lead)
        if score >= SPAM_THRESHOLD:
            return LeadOutcome(
                status=LeadStatus.SPAM_FILTERED,
                tier=Tier.ARCHIVED,
                route=Route.ARCHIVE,
                reasons=signals,
                **ids,
            )

        try:
            classification, attempts = self.classifier.classify(lead)
        except ClassificationFailedError as exc:
            attempts = len(exc.errors)
            self._dead_letter("classification", lead, exc.errors, attempts)
            return LeadOutcome(
                status=LeadStatus.DEAD_LETTER, errors=exc.errors, llm_attempts=attempts, **ids
            )

        decision = self.rules.decide(classification)
        processed = ProcessedLead(
            lead=lead,
            classification=classification,
            decision=decision,
            processed_at=datetime.now(UTC),
        )
        if decision.route is not Route.ARCHIVE:
            try:
                self.sink.upsert(processed)
            except Exception as exc:  # any adapter failure must land in the DLQ
                errors = [f"{type(exc).__name__}: {exc}"]
                self._dead_letter("crm_sink", lead, errors, 1)
                return LeadOutcome(
                    status=LeadStatus.DEAD_LETTER,
                    errors=errors,
                    classification=classification,
                    llm_attempts=attempts,
                    **ids,
                )
        if decision.tier is Tier.HOT:
            self.notifier.notify(
                f"HOT lead: {lead.company or lead.name} (fit {classification.fit_score})",
                f"{classification.summary} | {lead.email} {lead.phone or ''}".strip(),
            )
        return LeadOutcome(
            status=LeadStatus.PROCESSED,
            tier=decision.tier,
            route=decision.route,
            classification=classification,
            reasons=decision.reasons,
            llm_attempts=attempts,
            **ids,
        )

    def _dead_letter(self, stage: str, lead: Lead, errors: list[str], attempts: int) -> None:
        self.store.release(lead.dedupe_key)  # a later resubmission is retried, not deduped
        self.store.add_dead_letter(
            stage=stage,
            dedupe_key=lead.dedupe_key,
            errors=errors,
            payload=lead.model_dump(mode="json"),
            attempts=attempts,
        )
        self.notifier.notify(f"Dead letter ({stage}): {lead.email}", errors[-1])


def _get(payload: Mapping[str, Any] | RawLead, key: str) -> str | None:
    value = getattr(payload, key, None) if isinstance(payload, RawLead) else payload.get(key)
    return str(value) if value is not None else None


def build_pipeline(settings: Settings) -> LeadPipeline:
    return LeadPipeline(
        classifier=LeadClassifier(
            build_provider(settings), settings.llm_max_retries, settings.llm_retry_base_delay
        ),
        store=LeadStore(settings.db_path),
        sink=build_sink(settings),
        notifier=build_notifier(settings),
        rules=RoutingRules(hot_fit_threshold=settings.hot_fit_threshold),
        default_country=settings.default_phone_country,
    )
