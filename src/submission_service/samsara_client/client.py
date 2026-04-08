from __future__ import annotations

from typing import Optional

import httpx

from submission_service.config import settings
from submission_service.samsara_client.rate_limiter import AsyncTokenBucket

# Module-level singleton — shared across all concurrent activity executions
# on this worker process, which is the correct scope for rate limiting.
_bucket = AsyncTokenBucket(
    capacity=settings.samsara_rate_limit_rps * 10,  # burst = 10 seconds of tokens
    rate=settings.samsara_rate_limit_rps,
)


class SamsaraClient:
    """
    Async HTTP client for the Samsara Fleet API (or mock).
    Instantiate per-activity-call; the rate-limiter bucket is shared.
    """

    def __init__(self, base_url: str, api_token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=30.0,
        )

    async def validate_token(self) -> bool:
        """Lightweight connectivity check. Returns False on any error."""
        try:
            await _bucket.acquire()
            resp = await self._client.get("/v1/fleet/vehicles", params={"limit": 1})
            return resp.status_code == 200
        except Exception:
            return False

    async def list_vehicles(self) -> list[dict]:
        """Returns list of vehicle dicts: {id, vin, name}."""
        await _bucket.acquire()
        resp = await self._client.get("/v1/fleet/vehicles")
        resp.raise_for_status()
        return resp.json()["vehicles"]

    async def get_vehicle_stats(
        self,
        vin: str,
        start_date: str,
        end_date: str,
        page_token: Optional[str] = None,
    ) -> dict:
        """
        Returns {"records": [...], "next_page_token": str | None}.
        Each record has: vin, date, speed_mph_avg, hard_brakes,
        hard_accelerations, miles_driven, idle_minutes, fuel_consumed_l,
        fault_codes.
        """
        await _bucket.acquire()
        params: dict = {"vin": vin, "start_date": start_date, "end_date": end_date}
        if page_token:
            params["page_token"] = page_token
        resp = await self._client.get("/v1/fleet/vehicles/stats", params=params)
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()
