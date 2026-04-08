from __future__ import annotations

import base64
from datetime import date

from fastapi import APIRouter, Header, HTTPException, Query
from typing import Optional

from submission_service.samsara_mock.data_generator import ALL_DATA, VEHICLES

router = APIRouter()

_PAGE_SIZE = 90  # days per page


def _require_auth(authorization: Optional[str]) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")


# ---------------------------------------------------------------------------
# GET /v1/fleet/vehicles
# ---------------------------------------------------------------------------

@router.get("/fleet/vehicles")
async def list_vehicles(
    limit: Optional[int] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_auth(authorization)
    return {"vehicles": VEHICLES}


# ---------------------------------------------------------------------------
# GET /v1/fleet/vehicles/stats
# ---------------------------------------------------------------------------

@router.get("/fleet/vehicles/stats")
async def get_vehicle_stats(
    vin: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    page_token: Optional[str] = Query(default=None),
    simulate_error: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_auth(authorization)

    if simulate_error == "rate_limit":
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": "5"},
        )

    if vin not in ALL_DATA:
        raise HTTPException(status_code=404, detail=f"VIN {vin!r} not found")

    # Filter records to requested date range
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    all_records = [
        r for r in ALL_DATA[vin]
        if start <= date.fromisoformat(r["date"]) <= end
    ]

    # Pagination: page_token encodes an integer offset
    offset = 0
    if page_token:
        try:
            offset = int(base64.b64decode(page_token).decode())
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid page_token")

    page = all_records[offset: offset + _PAGE_SIZE]
    next_offset = offset + _PAGE_SIZE
    next_page_token = (
        base64.b64encode(str(next_offset).encode()).decode()
        if next_offset < len(all_records)
        else None
    )

    return {"records": page, "next_page_token": next_page_token}
