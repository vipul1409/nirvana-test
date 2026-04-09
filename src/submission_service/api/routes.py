from __future__ import annotations

from fastapi import APIRouter, HTTPException

from submission_service.config import settings
from submission_service.database import (
    create_submission,
    get_submission,
    update_submission_status,
)
from submission_service.models import (
    FleetIngestionInput,
    IngestResponse,
    SubmissionCreate,
    SubmissionResponse,
)
from submission_service.temporal.client import get_temporal_client
from submission_service.temporal.workflows import FleetIngestionWorkflow

router = APIRouter()


@router.post("/submissions", response_model=SubmissionResponse, status_code=201)
async def create_submission_endpoint(body: SubmissionCreate) -> dict:
    row = await create_submission(
        agent_id=body.agent_id,
        account_id=body.account_id,
        product_line=body.product_line,
        vehicle_vins=body.vehicle_vins,
        samsara_api_token=body.samsara_api_token,
    )
    return row


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
async def get_submission_endpoint(submission_id: str) -> dict:
    row = await get_submission(submission_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    return row


@router.post("/submissions/{submission_id}/ingest", response_model=IngestResponse)
async def trigger_ingestion(submission_id: str) -> dict:
    row = await get_submission(submission_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    workflow_id = f"ingest-{submission_id}"

    client = await get_temporal_client()
    handle = await client.start_workflow(
        FleetIngestionWorkflow.run,
        FleetIngestionInput(
            submission_id=submission_id,
            account_id=row["account_id"],
            samsara_api_token=row["samsara_api_token"],
            vehicle_vins=row["vehicle_vins"],
            start_date="2024-01-01",
            end_date="2024-12-31",
        ),
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
    )

    await update_submission_status(submission_id, "INGESTING")

    return {
        "submission_id": submission_id,
        "workflow_id": handle.id,
        "status": "started",
    }
