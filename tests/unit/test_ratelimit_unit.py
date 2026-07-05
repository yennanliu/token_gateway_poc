"""Unit tests for the in-memory token-bucket limiter (deterministic fake clock)."""

import pytest

from gateway.ratelimit import InMemoryRateLimiter


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs


@pytest.mark.asyncio
async def test_burst_up_to_rpm_then_denied():
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)
    assert await limiter.allow("k", 3) is True
    assert await limiter.allow("k", 3) is True
    assert await limiter.allow("k", 3) is True
    assert await limiter.allow("k", 3) is False  # bucket empty


@pytest.mark.asyncio
async def test_refills_over_time():
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)
    for _ in range(3):
        await limiter.allow("k", 3)
    assert await limiter.allow("k", 3) is False
    clock.advance(60)  # full refill after a minute
    assert await limiter.allow("k", 3) is True


@pytest.mark.asyncio
async def test_zero_rpm_is_unlimited():
    limiter = InMemoryRateLimiter(clock=FakeClock())
    for _ in range(50):
        assert await limiter.allow("k", 0) is True


@pytest.mark.asyncio
async def test_keys_are_independent():
    limiter = InMemoryRateLimiter(clock=FakeClock())
    assert await limiter.allow("a", 1) is True
    assert await limiter.allow("a", 1) is False
    assert await limiter.allow("b", 1) is True  # different key, fresh bucket
