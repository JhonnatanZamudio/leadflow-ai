"""Deterministic, offline stand-in for an LLM.

Keyword heuristics produce a plausible Classification so the whole pipeline can
run without network or API keys. `failure_rate` makes it emit malformed output
(bad JSON, out-of-range values, unknown enums, prose) so the retry and
dead-letter paths can be exercised. Failures are a pure function of
(seed, lead, attempt number), so runs are reproducible regardless of order.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from typing import Any

_LEAD_RE = re.compile(r"<lead>\s*(\{.*\})\s*</lead>", re.S)


def _words(text: str) -> tuple[str, ...]:
    return tuple(w.strip() for w in text.split("|"))


# Checked in this order; the first intent with a keyword hit wins.
_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "spam": _words("crypto|bitcoin|backlink|casino|seo package|guaranteed traffic"),
    "job_application": _words(
        "hoja de vida|my cv|mi cv|resume|vacante|position|trabajar con ustedes|join your team"
        "|currículo|practicante"
    ),
    "support": _words(
        "no funciona|error al|soporte|bug|not working|can't log in|falla|factura duplicada"
        "|invoice issue|getting an error"
    ),
    "quote_request": _words(
        "cotización|cotizar|precio|quote|pricing|presupuesto|proposal|propuesta|automatizar"
        "|automate|orçamento|implementar|how much|cuánto cuesta"
    ),
    "partnership": _words(
        "alianza|partnership|partner|reseller|revender|distribuidor|co-marketing|parceria"
    ),
}
_FIT_KEYWORDS = (
    " ia ",
    " ai ",
    *_words(
        "crm|automat|workflow|n8n|zapier|make.com|chatbot|integra|whatsapp|hubspot|leads|sheets"
    ),
)
_STOPWORDS = {
    "es": set(
        _words(
            "el|la|de|que|y|en|los|para|con|por|una|hola|necesitamos|nuestro|nuestra"
            "|gracias|quisiera|somos"
        )
    ),
    "en": set(_words("the|and|to|we|our|for|with|is|are|hi|hello|need|would|thanks|you")),
    "pt": set(
        _words("não|você|nós|obrigado|olá|gostaria|precisamos|nossa|também|é|uma|com|empresa|vocês")
    ),
}
_URGENT = _words(
    "urgente|asap|this week|esta semana|lo antes posible|cuanto antes|urgent|mañana|tomorrow"
    "|o quanto antes"
)
_RELAXED = _words(
    "next quarter|próximo año|proximo año|no rush|sin afán|sin prisa|next year|explorando|exploring"
)
_REPLIES = {
    "es": {
        "quote_request": "Hola {n}, gracias por escribirnos. Para darte una propuesta "
        "concreta, ¿tienes 20 minutos esta semana para revisar tu proceso "
        "actual? Te envío opciones de horario.",
        "job_application": "Hola {n}, gracias por tu interés. Nuestro equipo de talento "
        "revisará tu perfil y te contactará si hay una vacante afín.",
        "support": "Hola {n}, recibimos tu reporte. Un especialista de soporte te "
        "escribirá hoy con los siguientes pasos.",
        "default": "Hola {n}, gracias por contactarnos. ¿Podrías contarnos un poco más "
        "sobre lo que buscas para dirigirte a la persona correcta?",
    },
    "en": {
        "quote_request": "Hi {n}, thanks for reaching out. To scope this properly, could "
        "we do a 20-minute call this week to walk through your current "
        "process? I'll send a few time slots.",
        "job_application": "Hi {n}, thanks for your interest. Our talent team will review "
        "your profile and get back to you if there is a matching role.",
        "support": "Hi {n}, we got your report. A support specialist will follow up "
        "today with next steps.",
        "default": "Hi {n}, thanks for getting in touch. Could you share a bit more about "
        "what you need so we can route you to the right person?",
    },
    "pt": {
        "quote_request": "Olá {n}, obrigado pelo contato. Podemos fazer uma chamada de 20 "
        "minutos esta semana para entender o processo atual?",
        "default": "Olá {n}, obrigado pelo contato. Pode nos contar um pouco mais sobre o "
        "que precisa?",
    },
}
_COP_PER_USD = 4000


def _budget_usd(text: str) -> float | None:
    if m := re.search(r"(\d[\d.,]*)\s*(millones|millón|millon)", text):
        return float(m.group(1).replace(",", ".")) * 1_000_000 / _COP_PER_USD
    rx = (
        r"(?:usd|us\$|\$)\s?(\d[\d.,]*)\s*(k|mil)?|(\d[\d.,]*)\s*(k|mil)?\s*(?:usd|dólares|dollars)"
    )
    if m := re.search(rx, text):
        number, multiplier = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        if multiplier:
            return float(number.replace(",", ".")) * 1000
        return float(re.sub(r"[.,]", "", number))
    return None


def _band(usd: float | None) -> str:
    if usd is None:
        return "unknown"
    for limit, band in ((1_000, "<1k"), (5_000, "1k-5k"), (20_000, "5k-20k")):
        if usd < limit:
            return band
    return ">20k"


def heuristic_classification(lead: dict[str, Any]) -> dict[str, Any]:
    text = f" {lead.get('message', '')} ".lower()
    words = Counter(re.findall(r"[a-záéíóúñãõçê]+", text))
    language = max(("en", "es", "pt"), key=lambda lang: sum(words[w] for w in _STOPWORDS[lang]))
    intent = next(
        (i for i, kws in _INTENT_KEYWORDS.items() if any(k in text for k in kws)), "other"
    )
    band = _band(_budget_usd(text))
    urgency = (
        "high"
        if any(k in text for k in _URGENT)
        else "low"
        if any(k in text for k in _RELAXED)
        else "medium"
    )

    score = {
        "quote_request": 50,
        "partnership": 40,
        "other": 25,
        "support": 15,
        "job_application": 5,
        "spam": 0,
    }[intent]
    if intent not in {"spam", "job_application"}:
        score += 10 if lead.get("company") else 0
        score += {"unknown": 0, "<1k": -20, "1k-5k": 5, "5k-20k": 15, ">20k": 20}[band]
        score += 10 * min(2, sum(k in text for k in _FIT_KEYWORDS))
        score += {"high": 10, "medium": 0, "low": -5}[urgency]
        score += 5 if len(text) > 250 else 0
    first_name = (lead.get("name") or "").split(" ")[0] or "there"
    replies = _REPLIES[language]
    reply = replies.get(intent, replies["default"]).format(n=first_name)
    if intent == "spam":
        reply = "No reply: archived as spam."
    sentences = re.split(r"(?<=[.!?])\s+", lead.get("message", "").strip())
    sentence = next((x for x in sentences if len(x) >= 25), sentences[0])  # skip greetings
    who = lead.get("company") or lead.get("name") or "unknown sender"
    return {
        "intent": intent,
        "budget_band": band,
        "urgency": urgency,
        "fit_score": max(0, min(100, score)),
        "language": language,
        "summary": f"{intent.replace('_', ' ')} from {who}: {sentence}"[:197],
        "suggested_first_reply": reply,
    }


class FakeProvider:
    name = "fake"

    def __init__(self, failure_rate: float = 0.0, seed: int = 7) -> None:
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError("failure_rate must be within [0, 1]")
        self.failure_rate = failure_rate
        self.seed = seed
        self.calls = 0
        self._attempts: Counter[str] = Counter()

    def complete_structured(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        self.calls += 1
        match = _LEAD_RE.search(user)
        lead = json.loads(match.group(1)) if match else {"message": user}
        key = lead.get("dedupe_key", user)
        self._attempts[key] += 1
        rng = random.Random(f"{self.seed}:{key}:{self._attempts[key]}")  # noqa: S311
        good = heuristic_classification(lead)
        if rng.random() >= self.failure_rate:
            return json.dumps(good, ensure_ascii=False)
        return self._malformed(good, rng)

    @staticmethod
    def _malformed(good: dict[str, Any], rng: random.Random) -> str:
        kind = rng.choice(["truncated", "out_of_range", "bad_enum", "missing", "prose"])
        if kind == "truncated":
            text = json.dumps(good)
            return text[: len(text) // 2]
        if kind == "out_of_range":
            return json.dumps({**good, "fit_score": 140})
        if kind == "bad_enum":
            return json.dumps({**good, "intent": "probably_sales"})
        if kind == "missing":
            return json.dumps({k: v for k, v in good.items() if k != "urgency"})
        return "Sure! This lead looks like a strong sales opportunity."
