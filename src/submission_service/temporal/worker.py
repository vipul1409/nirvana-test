from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from submission_service.config import settings
from submission_service.database import init_db
from submission_service.temporal.activities import (
    discover_fleet,
    fetch_vehicle_telematics,
    finalize_submission,
    validate_connector,
)
from submission_service.temporal.workflows import (
    FleetIngestionWorkflow,
    VehicleIngestionWorkflow,
)


async def run_worker() -> None:
    await init_db()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[FleetIngestionWorkflow, VehicleIngestionWorkflow],
        activities=[
            validate_connector,
            discover_fleet,
            fetch_vehicle_telematics,
            finalize_submission,
        ],
    )
    print(f"Worker started on task queue '{settings.temporal_task_queue}'")
    await worker.run()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
