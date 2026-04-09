from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from submission_service.config import settings
from submission_service.samsara_mock.data_generator import build_dataset, load_vehicles
from submission_service.samsara_mock.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load vehicles fresh from demo_vehicles.json (or defaults) at startup
    # so the mock server always reflects the latest seed.
    vehicles = load_vehicles()
    app.state.vehicles = vehicles
    app.state.all_data = build_dataset(vehicles)
    missing = [v["vin"] for v in vehicles if v.get("has_missing_data")]
    print(f"Mock Samsara: loaded {len(vehicles)} vehicles ({len(missing)} with missing data)")
    yield


app = FastAPI(title="Mock Samsara API", version="1.0.0", lifespan=lifespan)
app.include_router(router, prefix="/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "vehicles": len(app.state.vehicles)}


def main() -> None:
    uvicorn.run(
        "submission_service.samsara_mock.app:app",
        host="0.0.0.0",
        port=settings.mock_samsara_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
