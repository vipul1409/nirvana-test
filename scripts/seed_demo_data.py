"""
Creates the demo submission with all 3 vehicles in PENDING state.
Run: uv run seed
"""
from __future__ import annotations

import asyncio
import sys
import os

# Allow running directly: python scripts/seed_demo_data.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from submission_service.database import create_submission, get_submission, init_db
from submission_service.samsara_mock.data_generator import VEHICLES

DEMO_SUBMISSION_ID = "demo-submission-001"
DEMO_VINS = [v["vin"] for v in VEHICLES]


async def seed() -> None:
    await init_db()

    existing = await get_submission(DEMO_SUBMISSION_ID)
    if existing:
        print(f"Demo submission already exists: {DEMO_SUBMISSION_ID} (status={existing['status']})")
        return

    await create_submission(
        agent_id="agent-001",
        account_id="acme-fleet-corp",
        product_line="commercial_auto",
        vehicle_vins=DEMO_VINS,
        samsara_api_token="demo-token-abc123",
        submission_id=DEMO_SUBMISSION_ID,
    )
    print(f"Created demo submission: {DEMO_SUBMISSION_ID}")
    print(f"VINs: {DEMO_VINS}")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
