from __future__ import annotations

import asyncio
import time


class AsyncTokenBucket:
    """
    Async token bucket rate limiter.

    capacity: max burst size in tokens
    rate:     refill rate in tokens/second
    """

    def __init__(self, capacity: float, rate: float) -> None:
        self._capacity = capacity
        self._rate = rate
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Block until `tokens` tokens are available."""
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return
            wait = (tokens - self._tokens) / self._rate

        await asyncio.sleep(wait)

        async with self._lock:
            self._refill()
            self._tokens -= tokens

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now
