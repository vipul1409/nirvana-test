"""
Seed the demo database and vehicle fixtures.

Always drops and recreates the database. Writes demo_vehicles.json for
the mock Samsara server to load at startup.

Usage:
    uv run seed                          # 10 vehicles, 2 with missing data
    uv run seed --vehicles 5             # 5 vehicles, 2 with missing data
    uv run seed --vehicles 20 --missing 4
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from submission_service.config import settings
from submission_service.database import create_submission, init_db
from submission_service.samsara_mock.data_generator import (
    VEHICLES_FILE,
    generate_vehicles,
    save_vehicles,
)

DEMO_SUBMISSION_ID = "demo-submission-001"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the submission-service demo database")
    parser.add_argument(
        "--vehicles",
        type=int,
        default=10,
        help="Total number of demo vehicles (default: 10)",
    )
    parser.add_argument(
        "--missing",
        type=int,
        default=2,
        help="Number of vehicles with missing telematics data (default: 2)",
    )
    return parser.parse_args()


async def seed(vehicles: list[dict]) -> None:
    # Always drop and recreate the database
    if os.path.exists(settings.db_path):
        os.remove(settings.db_path)
        print(f"Dropped existing database: {settings.db_path}")

    await init_db()
    print(f"Recreated database: {settings.db_path}")

    vins = [v["vin"] for v in vehicles]
    await create_submission(
        agent_id="agent-001",
        account_id="acme-fleet-corp",
        product_line="commercial_auto",
        vehicle_vins=vins,
        samsara_api_token="demo-token-abc123",
        submission_id=DEMO_SUBMISSION_ID,
    )

    missing = [v for v in vehicles if v.get("has_missing_data")]
    print(f"Created submission: {DEMO_SUBMISSION_ID}")
    print(f"  Total vehicles : {len(vehicles)}")
    print(f"  Missing data   : {len(missing)} vehicle(s) — "
          + ", ".join(v['vin'] for v in missing) if missing else "  Missing data   : 0 vehicles")
    print(f"Vehicles file written: {VEHICLES_FILE}")
    print("Restart mock-samsara to pick up the new vehicle list.")


def main() -> None:
    args = parse_args()

    if args.missing > args.vehicles:
        print(f"Error: --missing ({args.missing}) cannot exceed --vehicles ({args.vehicles})")
        sys.exit(1)

    vehicles = generate_vehicles(n=args.vehicles, missing_count=args.missing)
    save_vehicles(vehicles)
    asyncio.run(seed(vehicles))


if __name__ == "__main__":
    main()
