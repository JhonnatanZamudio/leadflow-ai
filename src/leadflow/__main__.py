"""CLI: python -m leadflow {run,report,serve}"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from leadflow.config import Settings
from leadflow.ingest import read_leads
from leadflow.pipeline import RunStats, build_pipeline
from leadflow.report import write_report
from leadflow.store import LeadStore


def _print_stats(stats: RunStats, provider: str) -> None:
    s = stats.by_status
    rows = [
        ("LLM provider", provider),
        ("Inputs received", stats.received),
        ("Rejected at validation", s.get("invalid", 0)),
        ("Duplicates removed", s.get("duplicate", 0)),
        ("Spam filtered before the model", s.get("spam_filtered", 0)),
        ("Classified by the model", s.get("processed", 0)),
        ("Dead letters", s.get("dead_letter", 0)),
        ("LLM calls (incl. retries)", stats.llm_calls),
        ("Tiers", ", ".join(f"{k}={v}" for k, v in sorted(stats.by_tier.items()))),
        ("Total time", f"{stats.total_seconds:.3f} s"),
        ("Avg time per input", f"{stats.avg_ms_per_lead:.2f} ms"),
    ]
    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        print(f"{key:<{width}}  {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="leadflow", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="process a JSONL or CSV file of leads")
    run.add_argument("--input", required=True, type=Path)
    run.add_argument("--db", type=Path, help="override DB_PATH")
    run.add_argument("--fresh", action="store_true", help="delete the database first")
    rep = sub.add_parser("report", help="write out/report.md and out/report.html")
    rep.add_argument("--out", type=Path, default=Path("out"))
    rep.add_argument("--db", type=Path)
    rep.add_argument("--date", type=date.fromisoformat, help="YYYY-MM-DD (default: today UTC)")
    rep.add_argument("--all", action="store_true", help="ignore --date, include everything")
    srv = sub.add_parser("serve", help="run the HTTP API")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    settings = Settings.from_env()
    if getattr(args, "db", None):
        settings = replace(settings, db_path=args.db)

    if args.command == "run":
        if args.fresh:
            settings.db_path.unlink(missing_ok=True)
        pipeline = build_pipeline(settings)
        stats, _ = pipeline.process_many(read_leads(args.input))
        _print_stats(stats, pipeline.classifier.provider.name)
    elif args.command == "report":
        day = None if args.all else (args.date or datetime.now(UTC).date())
        for path in write_report(LeadStore(settings.db_path), args.out, day):
            print(f"wrote {path}")
    else:  # pragma: no cover - blocking server
        import uvicorn  # noqa: PLC0415

        uvicorn.run("leadflow.api:create_app", factory=True, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
