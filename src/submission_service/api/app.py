from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from submission_service.config import settings
from submission_service.database import init_db
from submission_service.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Submission & Ingestion Service",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def main() -> None:
    uvicorn.run(
        "submission_service.api.app:app",
        host="0.0.0.0",
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
