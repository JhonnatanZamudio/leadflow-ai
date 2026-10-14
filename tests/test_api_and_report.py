from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import HOT_LEAD
from leadflow.api import create_app
from leadflow.pipeline import LeadPipeline
from leadflow.report import write_report

ROOT = Path(__file__).resolve().parents[1]


def test_post_lead_endpoint(make_pipeline: Callable[..., LeadPipeline]) -> None:
    client = TestClient(create_app(make_pipeline()))
    assert client.get("/health").json() == {"status": "ok", "llm_provider": "fake"}

    first = client.post("/leads", json=HOT_LEAD)
    assert first.status_code == 200
    assert first.json()["tier"] == "hot"
    assert first.json()["classification"]["budget_band"] == "5k-20k"

    again = client.post("/leads", json=HOT_LEAD)
    assert again.status_code == 200 and again.json()["status"] == "duplicate"

    bad = client.post("/leads", json={"email": "nope", "message": "Necesitamos una cotización"})
    assert bad.status_code == 422 and bad.json()["status"] == "invalid"


def test_batch_endpoint(make_pipeline: Callable[..., LeadPipeline]) -> None:
    client = TestClient(create_app(make_pipeline()))
    job = {"email": "dev@correo.example", "message": "Adjunto mi hoja de vida para la vacante."}
    body = client.post("/leads/batch", json=[HOT_LEAD, job, HOT_LEAD]).json()
    assert body["stats"]["by_status"] == {"processed": 2, "duplicate": 1}
    assert [o["route"] for o in body["outcomes"]] == ["sales", "hr", None]
    assert client.post("/leads/batch", json=[HOT_LEAD] * 501).status_code == 413


def test_report_generation(make_pipeline: Callable[..., LeadPipeline], tmp_path: Path) -> None:
    pipeline = make_pipeline()
    pipeline.process(HOT_LEAD)
    pipeline.process(HOT_LEAD)
    pipeline.process({"email": "bad@", "message": "Necesitamos una cotización"})
    md_path, html_path = write_report(pipeline.store, tmp_path)
    md = md_path.read_text(encoding="utf-8")
    assert "| processed | 1 |" in md and "| duplicate | 1 |" in md and "| invalid | 1 |" in md
    assert "| quote_request | 1 |" in md
    assert "Tallo Verde Agro SAS" in md
    assert "Average processing time per lead" in md
    assert html_path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_n8n_workflow_is_importable_shape() -> None:
    workflow = json.loads((ROOT / "n8n" / "leadflow-workflow.json").read_text(encoding="utf-8"))
    names = {node["name"] for node in workflow["nodes"]}
    types = {node["type"] for node in workflow["nodes"]}
    assert {
        "n8n-nodes-base.formTrigger",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.if",
        "n8n-nodes-base.googleSheets",
        "n8n-nodes-base.slack",
    } <= types
    for source, outputs in workflow["connections"].items():
        assert source in names
        targets = [c["node"] for branch in outputs["main"] for c in branch]
        assert set(targets) <= names
    assert len(workflow["connections"]["Is hot?"]["main"]) == 2  # true / false branches
