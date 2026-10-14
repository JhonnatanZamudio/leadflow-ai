from __future__ import annotations

import pytest

from leadflow.models import RawLead
from leadflow.normalize import (
    SPAM_THRESHOLD,
    LeadValidationError,
    build_lead,
    dedupe_key,
    normalize_phone,
    spam_check,
    strip_html,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+57 300 123 4567", "+573001234567"),
        ("3001234567", "+573001234567"),
        ("(+57) 300-123-4567", "+573001234567"),
        ("0057 312 555 0123", "+573125550123"),
        ("601 555 0142", "+576015550142"),  # Bogotá landline
        ("+57 123 456 7890", None),  # not a valid Colombian number
        ("12345", None),
        ("+1 415 555 0134", "+14155550134"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_phone(raw: str | None, expected: str | None) -> None:
    assert normalize_phone(raw) == expected


def test_strip_html_removes_tags_scripts_and_entities() -> None:
    html = "<p>Hola&nbsp;equipo,</p><script>alert('x')</script><p>Quisi&eacute;ramos<br>ayuda</p>"
    assert strip_html(html) == "Hola equipo, Quisiéramos ayuda"


def test_dedupe_key_ignores_case_and_whitespace() -> None:
    a = dedupe_key("Ana@Example.com", "Hola,  necesito   una cotización ")
    b = dedupe_key("ana@example.com", "hola, necesito una cotización")
    assert a == b
    assert a != dedupe_key("ana@example.com", "otro mensaje distinto")


def test_build_lead_normalizes_fields() -> None:
    lead = build_lead(
        RawLead(
            name="<b>Ana</b>",
            email=" ANA@Cafetal.example ",
            phone="310 555 0101",
            message="<p>Necesitamos automatizar reportes</p>",
            source="email",
        )
    )
    assert lead.name == "Ana"
    assert lead.email == "ana@cafetal.example"
    assert lead.phone == "+573105550101"
    assert lead.message == "Necesitamos automatizar reportes"
    assert lead.source == "email"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "carlos.rios@", "message": "Necesitamos cotizar una automatización"},
        {"email": "a@@b.example", "message": "Necesitamos cotizar una automatización"},
        {"email": "ok@valid.example", "message": "Hola"},
    ],
)
def test_build_lead_rejects_invalid_input(payload: dict[str, str]) -> None:
    with pytest.raises(LeadValidationError) as exc:
        build_lead(RawLead(**payload))
    assert exc.value.errors


def test_spam_check_flags_obvious_spam_and_spares_ambiguous() -> None:
    spam = build_lead(
        RawLead(email="x@mailinator.com", message="You have won a prize! Click here to claim it.")
    )
    ambiguous = build_lead(
        RawLead(email="y@agency.example", message="Do you need help with your SEO ranking?")
    )
    assert spam_check(spam)[0] >= SPAM_THRESHOLD
    assert spam_check(ambiguous)[0] < SPAM_THRESHOLD  # left for the model to judge
