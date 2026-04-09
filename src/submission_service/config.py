from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Temporal
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "ingestion"

    # Database
    db_path: str = "submission_service.db"

    # Samsara (points to mock server by default)
    samsara_base_url: str = "http://localhost:8001"

    # Valid API keys accepted by the mock Samsara server.
    # Comma-separated when set via env var: SAMSARA_MOCK_API_KEYS=key1,key2
    samsara_mock_api_keys: list[str] = ["demo-token-abc123"]

    # Rate limiter: Samsara publishes 600 req/min; prototype uses 80%
    samsara_rate_limit_rps: float = 8.0  # 480 req/min

    # Server ports
    api_port: int = 8000
    mock_samsara_port: int = 8001

    # Coverage threshold: >= this → READY, else PARTIAL
    coverage_threshold: float = 0.80


settings = Settings()
