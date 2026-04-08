from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# API request / response models (Pydantic)
# ---------------------------------------------------------------------------

class SubmissionCreate(BaseModel):
    agent_id: str
    account_id: str
    product_line: str = "commercial_auto"
    vehicle_vins: list[str]


class SubmissionResponse(BaseModel):
    id: str
    agent_id: str
    account_id: str
    product_line: str
    status: str
    coverage_pct: Optional[float]
    vehicle_vins: list[str]
    created_at: str
    sla_deadline_at: str


class IngestRequest(BaseModel):
    samsara_api_token: str = "demo-token-abc123"


class IngestResponse(BaseModel):
    submission_id: str
    workflow_id: str
    status: str


# ---------------------------------------------------------------------------
# Temporal workflow I/O (dataclasses — serialised natively by the SDK)
# ---------------------------------------------------------------------------

@dataclass
class FleetIngestionInput:
    submission_id: str
    account_id: str
    samsara_api_token: str
    vehicle_vins: list[str]
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD


@dataclass
class VehicleIngestionInput:
    submission_id: str
    vin: str
    samsara_api_token: str
    start_date: str
    end_date: str


@dataclass
class VehicleIngestionResult:
    vin: str
    records_written: int
    success: bool
    error_message: Optional[str] = None


@dataclass
class FleetIngestionResult:
    submission_id: str
    total_vehicles: int
    successful_vehicles: int
    failed_vehicles: int
    coverage_pct: float


# ---------------------------------------------------------------------------
# DDL (used by database.py)
# ---------------------------------------------------------------------------

SUBMISSION_DDL = """
CREATE TABLE IF NOT EXISTS submission (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    account_id      TEXT NOT NULL,
    product_line    TEXT NOT NULL DEFAULT 'commercial_auto',
    status          TEXT NOT NULL DEFAULT 'PENDING',
    coverage_pct    REAL,
    vehicle_vins    TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    sla_deadline_at TEXT NOT NULL
);
"""

TELEMATICS_RECORD_DDL = """
CREATE TABLE IF NOT EXISTS telematics_record (
    id            TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    vin           TEXT NOT NULL,
    metric_type   TEXT NOT NULL,
    value_json    TEXT NOT NULL,
    recorded_at   TEXT NOT NULL,
    ingested_at   TEXT NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES submission(id)
);

CREATE INDEX IF NOT EXISTS idx_telematics_vin_date
    ON telematics_record (vin, recorded_at);
"""
