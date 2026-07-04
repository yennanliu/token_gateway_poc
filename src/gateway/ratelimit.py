"""In-memory per-key rate limiting (Phase 2).

A token-bucket keyed by API key id. Simple and process-local — swap for Redis
when the gateway is horizontally scaled (that's a Phase 3 concern). ``rpm=0``
means unlimited.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key_id: str, rpm: int) -> bool:
        if rpm <= 0:
            return True
        now = self._clock()
        rate_per_sec = rpm / 60.0
        b = self._buckets.get(key_id)
        if b is None:
            self._buckets[key_id] = _Bucket(tokens=rpm - 1, updated=now)
            return True
        # refill
        b.tokens = min(rpm, b.tokens + (now - b.updated) * rate_per_sec)
        b.updated = now
        if b.tokens >= 1:
            b.tokens -= 1
            return True
        return False

    def reset(self) -> None:
        self._buckets.clear()


# Process-wide default limiter.
limiter = RateLimiter()
