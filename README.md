# Submission & Ingestion Service

Prototype of the fleet telematics ingestion pipeline described in `ARCHITECTURE.md`. Uses Temporal for durable workflow orchestration and a mock Samsara API for demo data.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker Desktop

## Setup

```bash
uv sync
```

## Running the Demo

Open **4 terminals** in this directory.

### Terminal 1 — Start Temporal

```bash
./docker/start.sh
```

Wait ~15 seconds for Temporal to initialize. UI available at <http://localhost:8080>.

### Terminal 2 — Mock Samsara API

```bash
uv run mock-samsara
```

Serves 3 demo vehicles with 366 days of telematics data on <http://localhost:8001>.

### Terminal 3 — Temporal Worker

```bash
uv run worker
```

Registers `FleetIngestionWorkflow` and `VehicleIngestionWorkflow` on the `ingestion` task queue.

### Terminal 4 — Ingestion API

```bash
uv run api
```

REST API on <http://localhost:8000>.

---

## Triggering Ingestion

**Seed the demo submission** (creates `demo-submission-001` with 3 vehicles):

```bash
uv run seed
```

**Start ingestion:**

```bash
curl -X POST http://localhost:8000/api/v1/submissions/demo-submission-001/ingest \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Poll status:**

```bash
curl http://localhost:8000/api/v1/submissions/demo-submission-001
```

Expected final state (~15 seconds):

```json
{
  "status": "READY",
  "coverage_pct": 1.0,
  "vehicle_vins": ["1HGBH41JXMN109186", "3VWFE21C04M000001", "5YJSA1DG9DFP14105"]
}
```

**Watch the workflow tree in Temporal UI:** <http://localhost:8080>
- `FleetIngestionWorkflow` (parent) fans out to 3 `VehicleIngestionWorkflow` children, one per VIN.

---

## Creating a Fresh Submission

```bash
curl -X POST http://localhost:8000/api/v1/submissions \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent-001",
    "account_id": "acme-fleet-corp",
    "vehicle_vins": ["1HGBH41JXMN109186", "3VWFE21C04M000001", "5YJSA1DG9DFP14105"]
  }'
# Returns {"id": "<submission-id>", "status": "PENDING", ...}

curl -X POST http://localhost:8000/api/v1/submissions/<submission-id>/ingest \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

## Demo Vehicles

| VIN | Vehicle | Behavior |
|-----|---------|----------|
| `1HGBH41JXMN109186` | Honda Civic | Low risk — avg 42 mph, ~2 hard brakes/month |
| `3VWFE21C04M000001` | Freightliner Cascadia | Truck — avg 58 mph, ~8 hard brakes/month, high idle |
| `5YJSA1DG9DFP14105` | Tesla Model 3 | EV — avg 51 mph, fuel = 0 |

All vehicles have 366 daily records covering 2024-01-01 through 2024-12-31.

---

## Teardown

```bash
./docker/stop.sh
```
