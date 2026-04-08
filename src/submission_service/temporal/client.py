from __future__ import annotations

from temporalio.client import Client

from submission_service.config import settings

_client: Client | None = None


async def get_temporal_client() -> Client:
    """Returns a cached Temporal client. Safe to call multiple times."""
    global _client
    if _client is None:
        _client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
        )
    return _client
