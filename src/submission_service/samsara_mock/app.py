import uvicorn
from fastapi import FastAPI

from submission_service.config import settings
from submission_service.samsara_mock.routes import router

app = FastAPI(title="Mock Samsara API", version="1.0.0")
app.include_router(router, prefix="/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def main() -> None:
    uvicorn.run(
        "submission_service.samsara_mock.app:app",
        host="0.0.0.0",
        port=settings.mock_samsara_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
