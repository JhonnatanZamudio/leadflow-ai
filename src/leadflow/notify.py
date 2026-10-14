"""Notification port: hot leads and dead letters must reach a human."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from leadflow.config import Settings

log = logging.getLogger("leadflow.notify")


class Notifier(Protocol):
    def notify(self, title: str, body: str) -> None: ...


class ConsoleNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def notify(self, title: str, body: str) -> None:
        self.sent.append((title, body))
        log.info("[notify] %s | %s", title, body)


class SlackWebhookNotifier:  # pragma: no cover - network, never called in tests
    def __init__(self, webhook_url: str, timeout: float = 5.0) -> None:
        self._url = webhook_url
        self._timeout = timeout

    def notify(self, title: str, body: str) -> None:
        try:
            response = httpx.post(
                self._url, json={"text": f"*{title}*\n{body}"}, timeout=self._timeout
            )
            response.raise_for_status()
        except httpx.HTTPError:
            # A failed alert must not fail the lead; log it loudly instead.
            log.exception("Slack notification failed: %s", title)


def build_notifier(settings: Settings) -> Notifier:
    choice = settings.notifier or ("slack" if settings.slack_webhook_url else "console")
    if choice == "slack":
        return SlackWebhookNotifier(settings.require("slack_webhook_url"))
    return ConsoleNotifier()
