"""Domain models: what comes in, what the LLM must return, and what goes out."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Source(StrEnum):
    WEB_FORM = "web_form"
    EMAIL = "email"
    API = "api"


class Intent(StrEnum):
    QUOTE_REQUEST = "quote_request"
    SUPPORT = "support"
    PARTNERSHIP = "partnership"
    JOB_APPLICATION = "job_application"
    SPAM = "spam"
    OTHER = "other"


class BudgetBand(StrEnum):
    UNKNOWN = "unknown"
    UNDER_1K = "<1k"
    FROM_1K_TO_5K = "1k-5k"
    FROM_5K_TO_20K = "5k-20k"
    OVER_20K = ">20k"


class Urgency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Language(StrEnum):
    ES = "es"
    EN = "en"
    PT = "pt"


class Tier(StrEnum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    ROUTED = "routed"
    ARCHIVED = "archived"


class Route(StrEnum):
    SALES = "sales"
    PARTNERSHIPS = "partnerships"
    SUPPORT = "support"
    HR = "hr"
    ARCHIVE = "archive"


class LeadStatus(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    INVALID = "invalid"
    SPAM_FILTERED = "spam_filtered"
    DEAD_LETTER = "dead_letter"


class RawLead(BaseModel):
    """Loosely typed payload, exactly as a form, mailbox or webhook delivers it."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str | None = None
    email: str | None = None
    company: str | None = None
    phone: str | None = None
    message: str | None = None
    source: str = Source.API.value
    received_at: datetime | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value


class Lead(BaseModel):
    """A validated, normalized lead. Only these ever reach the LLM."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    company: str | None = Field(default=None, max_length=160)
    phone: str | None = None  # E.164, e.g. +573001234567
    message: str = Field(min_length=10, max_length=5000)
    source: Source
    received_at: datetime
    dedupe_key: str


class Classification(BaseModel):
    """The structured output contract for the LLM. Anything else is rejected."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    budget_band: BudgetBand
    urgency: Urgency
    fit_score: int = Field(ge=0, le=100, description="How well the lead fits our services")
    language: Language
    summary: str = Field(min_length=1, max_length=200, description="One line, in English")
    suggested_first_reply: str = Field(
        min_length=1, max_length=1200, description="Short first reply in the lead's language"
    )


class RoutingDecision(BaseModel):
    tier: Tier
    route: Route
    reasons: list[str] = Field(default_factory=list)


class ProcessedLead(BaseModel):
    lead: Lead
    classification: Classification
    decision: RoutingDecision
    processed_at: datetime


class LeadOutcome(BaseModel):
    """What the pipeline reports back for every input, whatever happened to it."""

    status: LeadStatus
    dedupe_key: str | None = None
    name: str | None = None
    email: str | None = None
    company: str | None = None
    tier: Tier | None = None
    route: Route | None = None
    classification: Classification | None = None
    reasons: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    llm_attempts: int = 0
    duration_ms: float = 0.0
