"""Daily report in Markdown and HTML, built from the operational store."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path

from leadflow.store import LeadStore


@dataclass
class ReportData:
    day: date | None
    status_counts: Counter[str]
    intent_counts: Counter[str]
    hot_leads: list[sqlite3.Row]
    dead_letters: list[sqlite3.Row]
    rejected: list[sqlite3.Row]
    avg_ms_all: float
    avg_ms_classified: float
    total: int


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_report(store: LeadStore, day: date | None = None) -> ReportData:
    events = store.events(day)
    classified = [e for e in events if e["intent"]]
    return ReportData(
        day=day,
        status_counts=Counter(e["status"] for e in events),
        intent_counts=Counter(e["intent"] for e in classified),
        hot_leads=sorted(
            (e for e in events if e["tier"] == "hot"), key=lambda e: -(e["fit_score"] or 0)
        ),
        dead_letters=store.dead_letters(day),
        rejected=[e for e in events if e["status"] == "invalid"],
        avg_ms_all=_avg([e["duration_ms"] for e in events]),
        avg_ms_classified=_avg([e["duration_ms"] for e in classified]),
        total=len(events),
    )


def _sections(r: ReportData) -> list[tuple[str, list[str], list[list[str]]]]:
    """(title, header, rows) tables shared by both renderers."""
    return [
        ("Outcomes", ["status", "count"], [[k, str(v)] for k, v in r.status_counts.most_common()]),
        (
            "Leads per intent (classified by the model)",
            ["intent", "count"],
            [[k, str(v)] for k, v in r.intent_counts.most_common()],
        ),
        (
            "Hot leads",
            ["fit", "company / name", "email", "summary"],
            [
                [str(e["fit_score"]), e["company"] or e["name"], e["email"], e["summary"]]
                for e in r.hot_leads
            ],
        ),
        (
            "Dead letters",
            ["stage", "email", "attempts", "last error"],
            [
                [
                    d["stage"],
                    json.loads(d["payload"]).get("email", ""),
                    str(d["attempts"]),
                    d["error"].splitlines()[-1],
                ]
                for d in r.dead_letters
            ],
        ),
        (
            "Rejected at validation",
            ["email", "errors"],
            [[e["email"] or "", "; ".join(json.loads(e["errors"]))] for e in r.rejected],
        ),
    ]


def _headline(r: ReportData) -> list[str]:
    scope = r.day.isoformat() if r.day else "all time"
    return [
        f"Scope: {scope}",
        f"Inputs: {r.total}",
        f"Average processing time per lead: {r.avg_ms_all:.1f} ms "
        f"(classified leads only: {r.avg_ms_classified:.1f} ms)",
    ]


def render_markdown(r: ReportData) -> str:
    lines = ["# LeadFlow daily report", "", *[f"- {h}" for h in _headline(r)]]
    for title, header, rows in _sections(r):
        lines += ["", f"## {title}", ""]
        if not rows:
            lines.append("_None._")
            continue
        lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(c.replace("|", "\\|") for c in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def render_html(r: ReportData) -> str:
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>LeadFlow daily report</title><style>",
        "body{font:15px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;"
        "color:#1f2328;background:#fff}table{border-collapse:collapse;width:100%;margin:.5rem 0}"
        "th,td{border:1px solid #d0d7de;padding:.35rem .6rem;text-align:left;vertical-align:top}"
        "th{background:#f6f8fa}h2{margin-top:2rem}",
        "</style></head><body><h1>LeadFlow daily report</h1><ul>",
        *[f"<li>{escape(h)}</li>" for h in _headline(r)],
        "</ul>",
    ]
    for title, header, rows in _sections(r):
        parts.append(f"<h2>{escape(title)}</h2>")
        if not rows:
            parts.append("<p><em>None.</em></p>")
            continue
        parts.append("<table><tr>" + "".join(f"<th>{escape(h)}</th>" for h in header) + "</tr>")
        parts += ["<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in rows]
        parts.append("</table>")
    parts.append("</body></html>")
    return "\n".join(parts)


def write_report(store: LeadStore, out_dir: str | Path, day: date | None = None) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = build_report(store, day)
    md, html = out / "report.md", out / "report.html"
    md.write_text(render_markdown(data), encoding="utf-8")
    html.write_text(render_html(data), encoding="utf-8")
    return [md, html]
