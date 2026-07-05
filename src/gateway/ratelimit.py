"""Per-key rate limiting with a pluggable backend.

- **In-memory token bucket** (default): process-local, good for a single instance.
- **Redis fixed-window** (when ``REDIS_URL`` is set): shared across instances.

Both expose the same async API ``await allow(key_id, rpm)`` (``rpm=0`` = unlimited).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


class Limiter(Protocol):
    async def allow(self, key_id: str, rpm: int) -> bool: ...
    def reset(self) -> None: ...


@dataclass
class _Bucket:
    tokens: float
    updated: float


class InMemoryRateLimiter:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    async def allow(self, key_id: str, rpm: int) -> bool:
        if rpm <= 0:
            return True
        now = self._clock()
        rate_per_sec = rpm / 60.0
        b = self._buckets.get(key_id)
        if b is None:
            self._buckets[key_id] = _Bucket(tokens=rpm - 1, updated=now)
            return True
        b.tokens = min(rpm, b.tokens + (now - b.updated) * rate_per_sec)
        b.updated = now
        if b.tokens >= 1:
            b.tokens -= 1
            return True
        return False

    def reset(self) -> None:
        self._buckets.clear()


class RedisRateLimiter:
    """Fixed 60s window counter per key: INCR then EXPIRE; deny past ``rpm``."""

    def __init__(self, client, clock=time.time) -> None:
        self._redis = client
        self._clock = clock

    async def allow(self, key_id: str, rpm: int) -> bool:
        if rpm <= 0:
            return True
        window = int(self._clock() // 60)
        redis_key = f"rl:{key_id}:{window}"
        count = await self._redis.incr(redis_key)
        if count == 1:
            await self._redis.expire(redis_key, 60)
        return count <= rpm

    def reset(self) -> None:  # best-effort; tests use fresh fakeredis
        pass


# --- module-level active limiter -------------------------------------------

_limiter: Limiter = InMemoryRateLimiter()


def set_limiter(limiter: Limiter) -> None:
    global _limiter
    _limiter = limiter


def use_in_memory() -> None:
    set_limiter(InMemoryRateLimiter())


async def allow(key_id: str, rpm: int) -> bool:
    return await _limiter.allow(key_id, rpm)


def reset() -> None:
    _limiter.reset()


def build_from_settings():
    """Pick a backend from config. Called at app startup."""
    from .config import get_settings

    url = get_settings().redis_url
    if url:
        import redis.asyncio as aioredis

        set_limiter(RedisRateLimiter(aioredis.from_url(url, decode_responses=True)))
    else:
        use_in_memory()
