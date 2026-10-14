"""CRM output port and its adapters."""

from __future__ import annotations

import csv
import sqlite3
import threading
from pathlib import Path
from typing import Any, Protocol

from leadflow.config import Settings
from leadflow.models import ProcessedLead

CRM_COLUMNS = (
    "dedupe_key",
    "processed_at",
    "received_at",
    "source",
    "name",
    "email",
    "company",
    "phone",
    "intent",
    "budget_band",
    "urgency",
    "fit_score",
    "language",
    "tier",
    "route",
    "summary",
    "suggested_first_reply",
)


def crm_row(p: ProcessedLead) -> dict[str, Any]:
    lead, c, d = p.lead, p.classification, p.decision
    return {
        "dedupe_key": lead.dedupe_key,
        "processed_at": p.processed_at.isoformat(),
        "received_at": lead.received_at.isoformat(),
        "source": lead.source.value,
        "name": lead.name,
        "email": lead.email,
        "company": lead.company or "",
        "phone": lead.phone or "",
        "intent": c.intent.value,
        "budget_band": c.budget_band.value,
        "urgency": c.urgency.value,
        "fit_score": c.fit_score,
        "language": c.language.value,
        "tier": d.tier.value,
        "route": d.route.value,
        "summary": c.summary,
        "suggested_first_reply": c.suggested_first_reply,
    }


class CrmSink(Protocol):
    def upsert(self, lead: ProcessedLead) -> None: ...


class SQLiteCrmSink:
    """Default 'CRM': a table you can open in any SQLite browser."""

    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        cols = ", ".join(f"{c} TEXT" for c in CRM_COLUMNS[1:])
        with self._lock, self._conn:
            self._conn.execute(
                f"CREATE TABLE IF NOT EXISTS crm_leads (dedupe_key TEXT PRIMARY KEY, {cols})"
            )

    def upsert(self, lead: ProcessedLead) -> None:
        row = crm_row(lead)
        placeholders = ", ".join("?" for _ in CRM_COLUMNS)
        with self._lock, self._conn:
            self._conn.execute(
                f"INSERT OR REPLACE INTO crm_leads ({', '.join(CRM_COLUMNS)})"  # noqa: S608
                f" VALUES ({placeholders})",
                [row[c] for c in CRM_COLUMNS],
            )

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM crm_leads").fetchone()[0])


class CsvExportSink:
    """Append-only CSV, e.g. for a weekly import into an existing CRM."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def upsert(self, lead: ProcessedLead) -> None:
        with self._lock:
            new_file = not self.path.exists() or self.path.stat().st_size == 0
            with self.path.open("a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=CRM_COLUMNS)
                if new_file:
                    writer.writeheader()
                writer.writerow(crm_row(lead))


class GoogleSheetsSink:  # pragma: no cover - needs real credentials, never called in tests
    """Appends one row per lead to a Google Sheet via a service account."""

    def __init__(self, service_account_file: str, sheet_id: str, worksheet: str) -> None:
        import gspread  # noqa: PLC0415 - optional dependency

        client = gspread.service_account(filename=service_account_file)
        self._ws = client.open_by_key(sheet_id).worksheet(worksheet)
        if not self._ws.row_values(1):
            self._ws.append_row(list(CRM_COLUMNS))

    def upsert(self, lead: ProcessedLead) -> None:
        row = crm_row(lead)
        self._ws.append_row([str(row[c]) for c in CRM_COLUMNS], value_input_option="RAW")


def build_sink(settings: Settings) -> CrmSink:
    if settings.crm_sink == "sqlite":
        return SQLiteCrmSink(settings.db_path)
    if settings.crm_sink == "csv":
        return CsvExportSink(settings.csv_export_path)
    if settings.crm_sink == "sheets":
        return GoogleSheetsSink(
            settings.require("google_service_account_file"),
            settings.require("google_sheet_id"),
            settings.google_worksheet,
        )
    raise ValueError(f"Unknown CRM_SINK={settings.crm_sink!r} (sqlite|csv|sheets)")
