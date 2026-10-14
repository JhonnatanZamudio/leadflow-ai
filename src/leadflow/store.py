"""Operational state in SQLite: idempotency keys, an event log for every input,
and the dead-letter queue. (The CRM is a separate port, see sinks.py.)"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from leadflow.models import LeadOutcome

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lead_keys (
    dedupe_key TEXT PRIMARY KEY,
    claimed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lead_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    dedupe_key TEXT,
    name TEXT, email TEXT, company TEXT,
    intent TEXT, tier TEXT, route TEXT, fit_score INTEGER, summary TEXT,
    reasons TEXT, errors TEXT,
    llm_attempts INTEGER NOT NULL DEFAULT 0,
    duration_ms REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS dead_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    stage TEXT NOT NULL,
    dedupe_key TEXT,
    error TEXT NOT NULL,
    payload TEXT NOT NULL,
    attempts INTEGER NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class LeadStore:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def claim(self, dedupe_key: str) -> bool:
        """Atomically claim a key. False means another request already has it."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO lead_keys (dedupe_key, claimed_at) VALUES (?, ?)",
                (dedupe_key, _now()),
            )
            return cur.rowcount == 1

    def release(self, dedupe_key: str) -> None:
        """Un-claim after a failure so the same lead can be retried later."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM lead_keys WHERE dedupe_key = ?", (dedupe_key,))

    def record_event(self, o: LeadOutcome) -> None:
        c = o.classification
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO lead_events (created_at, status, dedupe_key, name, email, company,"
                " intent, tier, route, fit_score, summary, reasons, errors, llm_attempts,"
                " duration_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _now(),
                    o.status,
                    o.dedupe_key,
                    o.name,
                    o.email,
                    o.company,
                    c.intent if c else None,
                    o.tier,
                    o.route,
                    c.fit_score if c else None,
                    c.summary if c else None,
                    json.dumps(o.reasons),
                    json.dumps(o.errors),
                    o.llm_attempts,
                    o.duration_ms,
                ),
            )

    def add_dead_letter(
        self,
        *,
        stage: str,
        dedupe_key: str | None,
        errors: list[str],
        payload: dict[str, Any],
        attempts: int,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO dead_letters (created_at, stage, dedupe_key, error, payload, attempts)"
                " VALUES (?,?,?,?,?,?)",
                (
                    _now(),
                    stage,
                    dedupe_key,
                    "\n".join(errors),
                    json.dumps(payload, default=str, ensure_ascii=False),
                    attempts,
                ),
            )

    def _rows(self, table: str, day: date | None) -> list[sqlite3.Row]:
        query = f"SELECT * FROM {table}"  # noqa: S608 - table name is internal, never user input
        args: tuple[str, ...] = ()
        if day:
            query += " WHERE substr(created_at, 1, 10) = ?"
            args = (day.isoformat(),)
        with self._lock:
            return list(self._conn.execute(query + " ORDER BY id", args))

    def events(self, day: date | None = None) -> list[sqlite3.Row]:
        return self._rows("lead_events", day)

    def dead_letters(self, day: date | None = None) -> list[sqlite3.Row]:
        return self._rows("dead_letters", day)
