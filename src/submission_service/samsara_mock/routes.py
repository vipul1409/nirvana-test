from __future__ import annotations

import base64
from datetime import date
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from submission_service.config import settings

router = APIRouter()

_PAGE_SIZE = 90  # days per page


def _require_auth(authorization: Optional[str]) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token not in settings.samsara_mock_api_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# GET /v1/fleet/vehicles
# ---------------------------------------------------------------------------

@router.get("/fleet/vehicles")
async def list_vehicles(
    request: Request,
    limit: Optional[int] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_auth(authorization)
    return {"vehicles": request.app.state.vehicles}


# ---------------------------------------------------------------------------
# GET /v1/fleet/vehicles/stats
# ---------------------------------------------------------------------------

@router.get("/fleet/vehicles/stats")
async def get_vehicle_stats(
    request: Request,
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

    all_data: dict = request.app.state.all_data
    if vin not in all_data:
        raise HTTPException(status_code=404, detail=f"VIN {vin!r} not found")

    # Filter records to requested date range
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    all_records = [
        r for r in all_data[vin]
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
