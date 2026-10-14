from __future__ import annotations

import csv
import sqlite3
from collections.abc import Callable
from pathlib import Path

from conftest import HOT_LEAD
from leadflow.ingest import read_leads
from leadflow.llm import FakeProvider
from leadflow.models import LeadStatus
from leadflow.pipeline import LeadPipeline
from leadflow.sinks import CsvExportSink

DATA = Path(__file__).resolve().parents[1] / "data"


def test_hot_lead_is_classified_stored_and_notified(
    make_pipeline: Callable[..., LeadPipeline], db_path: Path
) -> None:
    pipeline = make_pipeline()
    outcome = pipeline.process(HOT_LEAD)
    assert outcome.status is LeadStatus.PROCESSED
    assert outcome.tier == "hot"
    assert outcome.classification and outcome.classification.language == "es"
    row = sqlite3.connect(db_path).execute("SELECT tier, phone FROM crm_leads").fetchone()
    assert row == ("hot", "+573105550101")
    assert pipeline.notifier.sent[0][0].startswith("HOT lead")  # type: ignore[attr-defined]


def test_duplicates_are_removed_within_and_across_batches(
    make_pipeline: Callable[..., LeadPipeline],
) -> None:
    pipeline = make_pipeline()
    variant = {
        **HOT_LEAD,
        "email": HOT_LEAD["email"].upper(),
        "message": HOT_LEAD["message"] + "  ",
    }
    stats, _ = pipeline.process_many([HOT_LEAD, variant])
    assert stats.by_status == {"processed": 1, "duplicate": 1}
    assert make_pipeline().process(HOT_LEAD).status is LeadStatus.DUPLICATE  # persisted


def test_spam_is_filtered_before_the_model(make_pipeline: Callable[..., LeadPipeline]) -> None:
    provider = FakeProvider()
    pipeline = make_pipeline(provider)
    spam = {"email": "a@mailinator.com", "message": "You have won! Click here: http://x.example"}
    outcome = pipeline.process(spam)
    assert outcome.status is LeadStatus.SPAM_FILTERED
    assert provider.calls == 0


def test_job_applications_are_routed_to_hr_and_spam_never_reaches_crm(
    make_pipeline: Callable[..., LeadPipeline], db_path: Path
) -> None:
    pipeline = make_pipeline()
    job = {"email": "dev@correo.example", "message": "Adjunto mi hoja de vida para la vacante."}
    model_spam = {"email": "s@seo.example", "message": "We offer an SEO package for your site."}
    assert pipeline.process(job).route == "hr"
    assert pipeline.process(model_spam).tier == "archived"
    routes = sqlite3.connect(db_path).execute("SELECT route FROM crm_leads").fetchall()
    assert routes == [("hr",)]


def test_sample_files_run_end_to_end(make_pipeline: Callable[..., LeadPipeline]) -> None:
    stats, outcomes = make_pipeline().process_many(read_leads(DATA / "sample_leads.jsonl"))
    assert stats.received == len(outcomes) == 40
    assert all(o.status is not LeadStatus.DEAD_LETTER for o in outcomes)  # no faults injected
    assert stats.by_status["duplicate"] >= 4 and stats.by_status["invalid"] >= 3

    csv_stats, _ = make_pipeline().process_many(read_leads(DATA / "sample_leads.csv"))
    assert csv_stats.by_status == {"processed": 3, "spam_filtered": 1, "invalid": 1}


def test_malformed_jsonl_line_becomes_invalid_record(
    tmp_path: Path, make_pipeline: Callable[..., LeadPipeline]
) -> None:
    path = tmp_path / "leads.jsonl"
    path.write_text('{"email": "a@b.example", "message": "Necesitamos una cotización"}\n{oops\n')
    stats, _ = make_pipeline().process_many(read_leads(path))
    assert stats.by_status == {"processed": 1, "invalid": 1}


def test_csv_export_sink(tmp_path: Path, make_pipeline: Callable[..., LeadPipeline]) -> None:
    pipeline = make_pipeline()
    pipeline.sink = CsvExportSink(tmp_path / "crm.csv")
    pipeline.process(HOT_LEAD)
    rows = list(csv.DictReader((tmp_path / "crm.csv").open(encoding="utf-8")))
    assert len(rows) == 1 and rows[0]["tier"] == "hot"
