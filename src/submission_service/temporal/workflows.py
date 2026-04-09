from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ChildWorkflowError

from submission_service.models import (
    ConnectorInput,
    FleetIngestionInput,
    FleetIngestionResult,
    VehicleIngestionInput,
    VehicleIngestionResult,
)

# Import activity functions using imports_passed_through so the sandbox
# doesn't try to re-import their transitive dependencies (aiosqlite, httpx,
# etc.) under restriction.  Must be at module level so the functions are
# available as references for execute_activity / execute_child_workflow.
with workflow.unsafe.imports_passed_through():
    from submission_service.temporal.activities import (
        fetch_vehicle_telematics,
        finalize_submission,
        validate_connector,
    )


@workflow.defn
class VehicleIngestionWorkflow:
    @workflow.run
    async def run(self, input: VehicleIngestionInput) -> VehicleIngestionResult:
        result: VehicleIngestionResult = await workflow.execute_activity(
            fetch_vehicle_telematics,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=5),
                backoff_coefficient=2.0,
                non_retryable_error_types=["VehicleNotFoundError"],
            ),
        )
        return result


@workflow.defn
class FleetIngestionWorkflow:
    @workflow.run
    async def run(self, input: FleetIngestionInput) -> FleetIngestionResult:
        # Step 1 — validate the Samsara API token before any other work.
        # InvalidTokenError is non-retryable: a bad token won't fix itself.
        await workflow.execute_activity(
            validate_connector,
            ConnectorInput(
                submission_id=input.submission_id,
                samsara_api_token=input.samsara_api_token,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                maximum_attempts=2,
                non_retryable_error_types=["InvalidTokenError"],
            ),
        )

        # Step 2 — fan out one child workflow per VIN.
        # Start all children before awaiting any, to maximise parallelism.
        child_handles = []
        for vin in input.vehicle_vins:
            child_input = VehicleIngestionInput(
                submission_id=input.submission_id,
                vin=vin,
                samsara_api_token=input.samsara_api_token,
                start_date=input.start_date,
                end_date=input.end_date,
            )
            handle = await workflow.start_child_workflow(
                VehicleIngestionWorkflow,
                child_input,
                id=f"vehicle-ingest-{input.submission_id}-{vin}",
                task_queue=workflow.info().task_queue,
            )
            child_handles.append((vin, handle))

        # Step 3 — await all children; tolerate individual failures.
        results: list[VehicleIngestionResult] = []
        for vin, handle in child_handles:
            try:
                r: VehicleIngestionResult = await handle
                results.append(r)
            except ChildWorkflowError as exc:
                results.append(
                    VehicleIngestionResult(
                        vin=vin,
                        records_written=0,
                        success=False,
                        error_message=str(exc.cause),
                    )
                )

        # Step 4 — compute coverage and finalise.
        successful = [r for r in results if r.success]
        coverage = len(successful) / len(results) if results else 0.0

        fleet_result = FleetIngestionResult(
            submission_id=input.submission_id,
            total_vehicles=len(results),
            successful_vehicles=len(successful),
            failed_vehicles=len(results) - len(successful),
            coverage_pct=coverage,
        )

        await workflow.execute_activity(
            finalize_submission,
            fleet_result,
            start_to_close_timeout=timedelta(seconds=30),
        )

        return fleet_result
