# Submission & Ingestion Service

## What This Is

Fleet telematics ingestion pipeline for an Underwriting Decision Engine. Agents submit insurance applications; this service pulls historical telematics data from Samsara for every vehicle in the fleet, then advances the submission to risk scoring.

The core problem is **durable fan-out**: 1,000 vehicles × 24 months of daily data, pulled from a rate-limited API, with resumability and partial completion tracking. Temporal is the backbone.

## Running Locally

```bash
uv sync                  # install dependencies
./docker/start.sh        # start Temporal + PostgreSQL (wait ~15s)
uv run mock-samsara      # fake Samsara API on :8001
uv run worker            # Temporal worker
uv run api               # ingestion API on :8000
uv run seed              # create demo submission
```

Trigger ingestion:
```bash
curl -X POST http://localhost:8000/api/v1/submissions/demo-submission-001/ingest \
  -H "Content-Type: application/json" -d '{}'

curl http://localhost:8000/api/v1/submissions/demo-submission-001
```

Temporal UI: http://localhost:8080

Teardown: `./docker/stop.sh`

## Architecture

### Workflow Structure

```
FleetIngestionWorkflow (one per submission)
├── Activity: validate_connector   — verify Samsara token, fail fast
├── Fan-out: VehicleIngestionWorkflow × N   (one child per VIN)
│     └── Activity: fetch_vehicle_telematics
│           Paginate Samsara stats API, heartbeat each page,
│           write daily records to telematics_record table
└── Activity: finalize_submission  — compute coverage %, set status
```

**Why child workflows instead of parallel activities?** Temporal caps workflow history at ~50K events. At 1,000 vehicles as activities, the parent would generate ~3K events; at 2,000 it exceeds the limit. Each child workflow has its own isolated history. The parent only records "child started / child completed."

**Partial completion semantics**: a failed child does not fail the parent. The parent collects all results with error handling, computes `coverage_pct = succeeded / total`, and sets status to `READY` (≥ 80% coverage) or `PARTIAL` (< 80%). Submissions with 94% coverage still advance to scoring.

### Rate Limiting

All Samsara API calls go through a shared `AsyncTokenBucket` — a module-level singleton in `samsara_client/client.py`, shared across all concurrent activities on the worker. Rate is set at 80% of Samsara's limit (8 req/s). This is enforced in the client, not in workflow logic, so it's impossible to bypass accidentally.

### Database

SQLite via `aiosqlite`. Two tables:

- `submission` — tracks status (`PENDING → INGESTING → READY / PARTIAL`)
- `telematics_record` — one row per vehicle per day; `value_json` holds the full daily stats blob; indexed on `(vin, recorded_at)`

No `ingestion_job` or `ingestion_task` tables — Temporal owns that state.

Data is stored in `submission_service.db` in the working directory.

## Key Files

| File | Purpose |
|------|---------|
| `src/submission_service/temporal/workflows.py` | `FleetIngestionWorkflow` + `VehicleIngestionWorkflow` |
| `src/submission_service/temporal/activities.py` | All 4 activities: validate, discover, fetch, finalize |
| `src/submission_service/samsara_mock/data_generator.py` | Demo data — single source of truth for all 3 vehicles |
| `src/submission_service/samsara_client/client.py` | Samsara HTTP client + module-level rate limiter |
| `src/submission_service/api/routes.py` | `POST /submissions`, `POST /submissions/{id}/ingest` |
| `src/submission_service/database.py` | aiosqlite CRUD helpers |
| `docker/docker-compose.yml` | Temporal + Temporal UI + PostgreSQL |

## Demo Vehicles

| VIN | Vehicle | Profile |
|-----|---------|---------|
| `1HGBH41JXMN109186` | Honda Civic | Low risk — avg 42 mph, ~2 hard brakes/month |
| `3VWFE21C04M000001` | Freightliner Cascadia | Truck — avg 58 mph, ~8 hard brakes/month, high idle |
| `5YJSA1DG9DFP14105` | Tesla Model 3 | EV — avg 51 mph, fuel = 0 |

366 daily records per VIN (2024-01-01 → 2024-12-31). Data is deterministic — seeded with `random.Random(vin)`.

## Temporal SDK Gotchas

- **`imports_passed_through()`** — activity functions must be imported in `workflows.py` inside `with workflow.unsafe.imports_passed_through():`. Using `sandbox_unrestricted()` or top-level imports causes `RuntimeError: Failed validating workflow` because the sandbox intercepts transitive imports (`aiosqlite`, `httpx`, etc.).
- **No I/O in workflow code** — all DB and HTTP calls are in activities only. Workflows must be deterministic.
- **`DB_PORT` must be set** — `temporalio/auto-setup` uses `nc -z $POSTGRES_SEEDS $DB_PORT` to wait for Postgres; without `DB_PORT=5432` it loops forever.
- **Activity connections** — each activity call opens its own `aiosqlite.connect()`. Connections are not shared across activity executions (not thread-safe).

## Config

All settings in `src/submission_service/config.py` via `pydantic-settings` — every value is overridable by environment variable.

| Env var | Default | Notes |
|---------|---------|-------|
| `TEMPORAL_ADDRESS` | `localhost:7233` | |
| `SAMSARA_BASE_URL` | `http://localhost:8001` | points to mock by default |
| `SAMSARA_RATE_LIMIT_RPS` | `8.0` | 80% of 600 req/min |
| `DB_PATH` | `submission_service.db` | SQLite file location |
| `COVERAGE_THRESHOLD` | `0.80` | below this → PARTIAL status |
