from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from temporalio import activity

from submission_service.config import settings
from submission_service.database import bulk_insert_telematics, update_submission_status
from submission_service.models import (
    FleetIngestionResult,
    VehicleIngestionInput,
    VehicleIngestionResult,
)
from submission_service.samsara_client.client import SamsaraClient


class VehicleNotFoundError(Exception):
    """Raised when a VIN does not exist in Samsara. Non-retryable."""


@activity.defn
async def validate_connector(api_token: str) -> bool:
    """Returns True if the Samsara token is valid, False otherwise. Never throws."""
    client = SamsaraClient(base_url=settings.samsara_base_url, api_token=api_token)
    try:
        return await client.validate_token()
    finally:
        await client.aclose()


@activity.defn
async def discover_fleet(api_token: str) -> list[str]:
    """Returns the list of VINs associated with the Samsara account."""
    client = SamsaraClient(base_url=settings.samsara_base_url, api_token=api_token)
    try:
        vehicles = await client.list_vehicles()
        return [v["vin"] for v in vehicles]
    finally:
        await client.aclose()


@activity.defn
async def fetch_vehicle_telematics(input: VehicleIngestionInput) -> VehicleIngestionResult:
    """
    Paginates through Samsara stats for one VIN and writes daily records to DB.
    Heartbeats after each page so Temporal detects stuck workers.
    """
    client = SamsaraClient(
        base_url=settings.samsara_base_url,
        api_token=input.samsara_api_token,
    )
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

        return VehicleIngestionResult(
            vin=input.vin,
            records_written=total_written,
            success=True,
        )

    except VehicleNotFoundError:
        raise  # non-retryable — re-raise so retry policy skips retries

    except Exception as exc:
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
    await update_submission_status(
        submission_id=result.submission_id,
        status=status,
        coverage_pct=result.coverage_pct,
    )
