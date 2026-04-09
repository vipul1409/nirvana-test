from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from temporalio import activity

from submission_service.config import settings
from submission_service.database import bulk_insert_telematics, update_submission_status
from submission_service.models import (
    ConnectorInput,
    FleetIngestionResult,
    VehicleIngestionInput,
    VehicleIngestionResult,
)
from submission_service.samsara_client.client import SamsaraClient


class InvalidTokenError(Exception):
    """Raised when the Samsara API token is rejected. Non-retryable."""


class VehicleNotFoundError(Exception):
    """Raised when a VIN does not exist in Samsara. Non-retryable."""


def _make_client(api_token: str) -> SamsaraClient:
    """Construct a Samsara client with the provided token."""
    return SamsaraClient(base_url=settings.samsara_base_url, api_token=api_token)


@activity.defn
async def validate_connector(input: ConnectorInput) -> None:
    """
    Validates the Samsara API token by making a live request.

    Raises InvalidTokenError if the token is rejected — this is non-retryable
    so the workflow fails immediately rather than burning retry attempts.
    """
    activity.logger.info(
        "Validating Samsara token for submission %s", input.submission_id
    )
    client = _make_client(input.samsara_api_token)
    try:
        ok = await client.validate_token()
    finally:
        await client.aclose()

    if not ok:
        raise InvalidTokenError(
            f"Samsara API token rejected for submission {input.submission_id}"
        )

    activity.logger.info(
        "Token validated for submission %s", input.submission_id
    )


@activity.defn
async def discover_fleet(input: ConnectorInput) -> list[str]:
    """
    Lists all VINs for the account using the stored API token.
    Token is passed explicitly via ConnectorInput on every call.
    """
    activity.logger.info(
        "Discovering fleet for submission %s", input.submission_id
    )
    client = _make_client(input.samsara_api_token)
    try:
        vehicles = await client.list_vehicles()
    finally:
        await client.aclose()

    vins = [v["vin"] for v in vehicles]
    activity.logger.info(
        "Discovered %d vehicles for submission %s", len(vins), input.submission_id
    )
    return vins


@activity.defn
async def fetch_vehicle_telematics(input: VehicleIngestionInput) -> VehicleIngestionResult:
    """
    Paginates through Samsara stats for one VIN and writes daily records to DB.
    Token is passed explicitly via VehicleIngestionInput on every request.
    Heartbeats after each page so Temporal detects stuck workers.
    """
    activity.logger.info(
        "Fetching telematics for VIN %s (submission %s)", input.vin, input.submission_id
    )
    client = _make_client(input.samsara_api_token)
    total_written = 0
    page_token = None
    page_num = 0

    try:
        while True:
            activity.heartbeat({"vin": input.vin, "page": page_num})

            try:
                response = await client.get_vehicle_stats(
                    vin=input.vin,
                    start_date=input.start_date,
                    end_date=input.end_date,
                    page_token=page_token,
                )
            except Exception as exc:
                if "404" in str(exc):
                    raise VehicleNotFoundError(
                        f"VIN {input.vin} not found in Samsara"
                    ) from exc
                raise

            records = response.get("records", [])
            if records:
                now = datetime.now(timezone.utc).isoformat()
                db_rows = [
                    {
                        "id": str(uuid.uuid4()),
                        "submission_id": input.submission_id,
                        "vin": r["vin"],
                        "metric_type": "daily_stats",
                        "value_json": json.dumps(r),
                        "recorded_at": r["date"],
                        "ingested_at": now,
                    }
                    for r in records
                ]
                written = await bulk_insert_telematics(db_rows)
                total_written += written

            page_token = response.get("next_page_token")
            if not page_token:
                break
            page_num += 1

        activity.logger.info(
            "Wrote %d records for VIN %s (submission %s)",
            total_written, input.vin, input.submission_id,
        )
        return VehicleIngestionResult(
            vin=input.vin,
            records_written=total_written,
            success=True,
        )

    except VehicleNotFoundError:
        raise  # non-retryable — propagate so retry policy skips retries

    except Exception as exc:
        activity.logger.warning(
            "Failed fetching telematics for VIN %s: %s", input.vin, exc
        )
        return VehicleIngestionResult(
            vin=input.vin,
            records_written=total_written,
            success=False,
            error_message=str(exc),
        )

    finally:
        await client.aclose()


@activity.defn
async def finalize_submission(result: FleetIngestionResult) -> None:
    """
    Writes final status to the submission row.
    READY if coverage >= threshold, PARTIAL otherwise.
    """
    status = (
        "READY"
        if result.coverage_pct >= settings.coverage_threshold
        else "PARTIAL"
    )
    activity.logger.info(
        "Finalizing submission %s: status=%s coverage=%.0f%%",
        result.submission_id, status, result.coverage_pct * 100,
    )
    await update_submission_status(
        submission_id=result.submission_id,
        status=status,
        coverage_pct=result.coverage_pct,
    )


@activity.defn
async def mark_submission_failed(submission_id: str) -> None:
    """
    Marks the submission FAILED. Called when the FleetIngestionWorkflow
    fails before it can call finalize_submission (e.g. invalid token).
    """
    activity.logger.info("Marking submission %s as FAILED", submission_id)
    await update_submission_status(submission_id=submission_id, status="FAILED")
