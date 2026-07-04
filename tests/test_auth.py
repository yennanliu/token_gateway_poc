import httpx
import pytest
import respx

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OK = {
    "model": "gpt-5.4",
    "choices": [{"message": {"role": "assistant", "content": "x"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
}


def _body():
    return {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}


@pytest.mark.asyncio
async def test_missing_key_401(client, seed):
    r = await client.post("/v1/chat/completions", json=_body())
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_unknown_key_401(client, seed):
    r = await client.post(
        "/v1/chat/completions",
        json=_body(),
        headers={"Authorization": "Bearer atp-doesnotexist"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_revoked_key_401(client, seed):
    from datetime import datetime, timezone

    from gateway import db
    from gateway.models import ApiKey

    async with db.get_sessionmaker()() as s:
        key = await s.get(ApiKey, seed["api_key_id"])
        key.revoked_at = datetime.now(timezone.utc)
        await s.commit()

    r = await client.post(
        "/v1/chat/completions",
        json=_body(),
        headers={"Authorization": f"Bearer {seed['raw_key']}"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_valid_key_query_param(client, seed):
    with respx.mock:
        respx.post(OPENAI_URL).mock(return_value=httpx.Response(200, json=OK))
        r = await client.post(
            f"/v1/chat/completions?key={seed['raw_key']}", json=_body()
        )
    assert r.status_code == 200
