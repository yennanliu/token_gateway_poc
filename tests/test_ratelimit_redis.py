import fakeredis.aioredis
import httpx
import pytest
import respx

from gateway import ratelimit
from gateway.ratelimit import RedisRateLimiter

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OK = {
    "model": "gpt-5.4",
    "choices": [{"message": {"role": "assistant", "content": "x"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
}


@pytest.mark.asyncio
async def test_redis_fixed_window_allows_then_denies():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    limiter = RedisRateLimiter(client, clock=lambda: 60.0)  # fixed window
    assert await limiter.allow("k", 2) is True
    assert await limiter.allow("k", 2) is True
    assert await limiter.allow("k", 2) is False  # third in window


@pytest.mark.asyncio
async def test_redis_unlimited_when_rpm_zero():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    limiter = RedisRateLimiter(client)
    for _ in range(100):
        assert await limiter.allow("k", 0) is True


@pytest.mark.asyncio
async def test_redis_backend_enforced_through_gateway(client, seed):
    # Swap the active limiter to a Redis-backed one for this test.
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    ratelimit.set_limiter(RedisRateLimiter(fake, clock=lambda: 0.0))

    from gateway import db
    from gateway.models import ApiKey

    async with db.get_sessionmaker()() as s:
        key = await s.get(ApiKey, seed["api_key_id"])
        key.rpm_limit = 1
        await s.commit()

    body = {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    headers = {"Authorization": f"Bearer {seed['raw_key']}"}
    with respx.mock:
        respx.post(OPENAI_URL).mock(return_value=httpx.Response(200, json=OK))
        first = await client.post("/v1/chat/completions", json=body, headers=headers)
        second = await client.post("/v1/chat/completions", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429
