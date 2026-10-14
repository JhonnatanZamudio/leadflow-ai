"""HTTP adapter. Run with: uvicorn leadflow.api:create_app --factory"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from leadflow import __version__
from leadflow.config import Settings
from leadflow.models import LeadOutcome, LeadStatus, RawLead
from leadflow.pipeline import LeadPipeline, RunStats, build_pipeline

MAX_BATCH = 500
_HTTP_STATUS = {
    LeadStatus.PROCESSED: 200,
    LeadStatus.DUPLICATE: 200,  # idempotent: resubmitting is not an error
    LeadStatus.SPAM_FILTERED: 200,
    LeadStatus.INVALID: 422,
    LeadStatus.DEAD_LETTER: 202,  # accepted, parked for review
}


class BatchResult(BaseModel):
    stats: RunStats
    outcomes: list[LeadOutcome]


def create_app(pipeline: LeadPipeline | None = None) -> FastAPI:
    pipe = pipeline or build_pipeline(Settings.from_env())
    app = FastAPI(title="LeadFlow AI", version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "llm_provider": pipe.classifier.provider.name}

    @app.post("/leads", response_model=LeadOutcome)
    def ingest_lead(lead: RawLead, response: Response) -> LeadOutcome:
        outcome = pipe.process(lead)
        response.status_code = _HTTP_STATUS[outcome.status]
        return outcome

    @app.post("/leads/batch", response_model=BatchResult)
    def ingest_batch(leads: list[RawLead]) -> BatchResult:
        if len(leads) > MAX_BATCH:
            raise HTTPException(413, f"batch limit is {MAX_BATCH} leads")
        stats, outcomes = pipe.process_many(leads)
        return BatchResult(stats=stats, outcomes=outcomes)

    return app
