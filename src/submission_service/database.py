from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiosqlite

from submission_service.config import settings
from submission_service.models import SUBMISSION_DDL, TELEMATICS_RECORD_DDL


async def init_db() -> None:
    """Create tables if they don't exist. Idempotent."""
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript(SUBMISSION_DDL + TELEMATICS_RECORD_DDL)
        await db.commit()


async def create_submission(
    agent_id: str,
    account_id: str,
    product_line: str,
    vehicle_vins: list[str],
    submission_id: Optional[str] = None,
) -> dict:
    now = datetime.now(timezone.utc)
    sid = submission_id or str(uuid.uuid4())
    row = {
        "id": sid,
        "agent_id": agent_id,
        "account_id": account_id,
        "product_line": product_line,
        "status": "PENDING",
        "coverage_pct": None,
        "vehicle_vins": json.dumps(vehicle_vins),
        "created_at": now.isoformat(),
        "sla_deadline_at": (now + timedelta(minutes=30)).isoformat(),
    }
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """INSERT OR IGNORE INTO submission
               (id, agent_id, account_id, product_line, status, vehicle_vins,
                created_at, sla_deadline_at)
               VALUES (:id, :agent_id, :account_id, :product_line, :status,
                       :vehicle_vins, :created_at, :sla_deadline_at)""",
            row,
        )
        await db.commit()
    # Return with vehicle_vins as list (mirrors get_submission)
    row["vehicle_vins"] = vehicle_vins
    return row


async def get_submission(submission_id: str) -> Optional[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM submission WHERE id = ?", (submission_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            d = dict(row)
            d["vehicle_vins"] = json.loads(d["vehicle_vins"])
            return d


async def update_submission_status(
    submission_id: str,
    status: str,
    coverage_pct: Optional[float] = None,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """UPDATE submission
               SET status = ?, coverage_pct = ?
               WHERE id = ?""",
            (status, coverage_pct, submission_id),
        )
        await db.commit()


async def bulk_insert_telematics(records: list[dict]) -> int:
    """Insert telematics records. Uses INSERT OR IGNORE for idempotency."""
    if not records:
        return 0
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executemany(
            """INSERT OR IGNORE INTO telematics_record
               (id, submission_id, vin, metric_type, value_json, recorded_at, ingested_at)
               VALUES (:id, :submission_id, :vin, :metric_type, :value_json,
                       :recorded_at, :ingested_at)""",
            records,
        )
        await db.commit()
    return len(records)
