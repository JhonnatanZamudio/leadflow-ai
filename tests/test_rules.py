from __future__ import annotations

from typing import Any

import pytest

from leadflow.models import Classification, Route, Tier
from leadflow.rules import RoutingRules


def classification(**overrides: Any) -> Classification:
    base = {
        "intent": "quote_request",
        "budget_band": "5k-20k",
        "urgency": "medium",
        "fit_score": 80,
        "language": "es",
        "summary": "s",
        "suggested_first_reply": "r",
    }
    return Classification.model_validate(base | overrides)


@pytest.mark.parametrize(
    ("overrides", "tier", "route"),
    [
        ({}, Tier.HOT, Route.SALES),
        ({"fit_score": 70}, Tier.HOT, Route.SALES),
        ({"fit_score": 69}, Tier.WARM, Route.SALES),
        ({"budget_band": "<1k"}, Tier.WARM, Route.SALES),
        ({"urgency": "low"}, Tier.WARM, Route.SALES),
        ({"fit_score": 10}, Tier.COLD, Route.SALES),
        ({"intent": "spam", "fit_score": 95}, Tier.ARCHIVED, Route.ARCHIVE),
        ({"intent": "job_application"}, Tier.ROUTED, Route.HR),
        ({"intent": "support"}, Tier.ROUTED, Route.SUPPORT),
        ({"intent": "partnership", "fit_score": 90}, Tier.WARM, Route.PARTNERSHIPS),
    ],
)
def test_routing(overrides: dict[str, Any], tier: Tier, route: Route) -> None:
    decision = RoutingRules().decide(classification(**overrides))
    assert (decision.tier, decision.route) == (tier, route)
    assert decision.reasons


def test_threshold_is_configurable() -> None:
    assert RoutingRules(hot_fit_threshold=90).decide(classification()).tier is Tier.WARM
