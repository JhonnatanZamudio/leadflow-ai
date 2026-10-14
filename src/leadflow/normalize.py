"""Normalization, validation, dedupe keys and pre-model spam heuristics.

Everything here is deterministic and cheap; it runs before any LLM call so we
never pay tokens for garbage, duplicates or obvious spam.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser

from pydantic import ValidationError

from leadflow.models import Lead, RawLead, Source


class LeadValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class _TextExtractor(HTMLParser):
    _SKIP = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skipping += 1
        self.parts.append(" ")  # <br>, <p>, <div> separate words

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def strip_html(text: str) -> str:
    """Remove tags (and script/style bodies), decode entities, collapse whitespace."""
    parser = _TextExtractor()
    parser.feed(text)
    parser.close()
    return re.sub(r"\s+", " ", unescape("".join(parser.parts))).strip()


def normalize_phone(raw: str | None, default_country: str = "57") -> str | None:
    """Return an E.164 number or None. Colombian numbers get strict checks:
    mobiles are 10 digits starting with 3, landlines 10 digits starting with 60."""
    if not raw:
        return None
    raw = raw.strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("00"):
        digits, international = digits[2:], True
    else:
        international = raw.startswith("+")
    if not international and len(digits) == 10 and default_country == "57":
        digits = "57" + digits
    elif not international and default_country != "57":
        digits = default_country + digits
    if digits.startswith("57"):
        national = digits[2:]
        valid_co = len(national) == 10 and (national[0] == "3" or national.startswith("60"))
        return f"+{digits}" if valid_co else None
    return f"+{digits}" if 8 <= len(digits) <= 15 else None


def _normalize_message(message: str) -> str:
    return re.sub(r"\s+", " ", message).strip().lower()


def dedupe_key(email: str, message: str) -> str:
    """Same sender + same message (case/whitespace-insensitive) == same lead."""
    material = f"{email.strip().lower()}\n{_normalize_message(message)}"
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def build_lead(raw: RawLead, default_country: str = "57") -> Lead:
    """Turn a raw payload into a validated Lead or raise LeadValidationError."""
    message = strip_html(raw.message or "")
    email = (raw.email or "").strip().lower()
    name = strip_html(raw.name or "") or email.split("@")[0] or "unknown"
    try:
        source = Source(raw.source)
    except ValueError:
        source = Source.API
    try:
        return Lead(
            name=name,
            email=email,
            company=strip_html(raw.company) if raw.company else None,
            phone=normalize_phone(raw.phone, default_country),
            message=message,
            source=source,
            received_at=raw.received_at or datetime.now(UTC),
            dedupe_key=dedupe_key(email, message),
        )
    except ValidationError as exc:
        errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        raise LeadValidationError(errors) from exc


_SPAM_PATTERNS = {
    "crypto": re.compile(r"\b(crypto|bitcoin|forex)\b"),
    "seo": re.compile(r"backlinks?|first page of google|primera página de google|seo ranking"),
    "pharma": re.compile(r"\b(viagra|cialis)\b"),
    "prize": re.compile(r"\byou (have )?won\b|\bganaste\b|\bganador\b|\bwinner\b"),
    "casino": re.compile(r"\b(casino|apuestas)\b"),
    "clickbait": re.compile(r"click here|haz clic aqu[ií]|limited offer|oferta limitada"),
}
_DISPOSABLE_DOMAINS = frozenset(
    {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.dev", "yopmail.com"}
)
SPAM_THRESHOLD = 2


def spam_check(lead: Lead) -> tuple[int, list[str]]:
    """Score a lead for spam and explain why. Tuned for precision: ambiguous
    messages score low, pass through, and the model gets the final word."""
    text = lead.message.lower()
    signals = [f"keyword:{name}" for name, rx in _SPAM_PATTERNS.items() if rx.search(text)]
    score = len(signals)
    links = len(re.findall(r"https?://", text))
    if links >= 3:
        signals.append(f"{links} links")
        score += 2
    if lead.email.split("@")[-1] in _DISPOSABLE_DOMAINS:
        signals.append("disposable email domain")
        score += 1
    letters = [c for c in lead.message if c.isalpha()]
    if len(letters) > 20 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        signals.append("mostly uppercase")
        score += 1
    return score, signals
