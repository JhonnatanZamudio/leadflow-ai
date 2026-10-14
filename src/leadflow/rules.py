"""Deterministic business rules applied after the model.

The LLM proposes, the rules decide: tiering and routing are plain code that
sales can read, test and change without touching a prompt."""

from __future__ import annotations

from dataclasses import dataclass

from leadflow.models import (
    BudgetBand,
    Classification,
    Intent,
    Route,
    RoutingDecision,
    Tier,
    Urgency,
)


@dataclass(frozen=True)
class RoutingRules:
    hot_fit_threshold: int = 70
    warm_fit_threshold: int = 40

    def decide(self, c: Classification) -> RoutingDecision:
        if c.intent is Intent.SPAM:
            return _decision(Tier.ARCHIVED, Route.ARCHIVE, "model classified as spam")
        if c.intent is Intent.JOB_APPLICATION:
            return _decision(Tier.ROUTED, Route.HR, "job application goes to HR, not sales")
        if c.intent is Intent.SUPPORT:
            return _decision(Tier.ROUTED, Route.SUPPORT, "existing-customer support request")

        route = Route.PARTNERSHIPS if c.intent is Intent.PARTNERSHIP else Route.SALES
        fit = c.fit_score
        if c.intent is Intent.QUOTE_REQUEST and fit >= self.hot_fit_threshold:
            if c.urgency is Urgency.LOW:
                return _decision(Tier.WARM, route, f"fit {fit} qualifies, but urgency is low")
            if c.budget_band is BudgetBand.UNDER_1K:
                return _decision(Tier.WARM, route, f"fit {fit} qualifies, but budget is <1k")
            return _decision(
                Tier.HOT, route, f"quote_request, fit {fit} >= {self.hot_fit_threshold}"
            )
        if fit >= self.warm_fit_threshold:
            return _decision(Tier.WARM, route, f"fit {fit} >= {self.warm_fit_threshold}")
        return _decision(Tier.COLD, route, f"fit {fit} < {self.warm_fit_threshold}")


def _decision(tier: Tier, route: Route, reason: str) -> RoutingDecision:
    return RoutingDecision(tier=tier, route=route, reasons=[reason])
