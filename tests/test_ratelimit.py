import httpx
import pytest
import respx

from gateway import db
from gateway.models import ApiKey

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OK = {
    "model": "gpt-5.4",
    "choices": [{"message": {"role": "assistant", "content": "x"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
}


@pytest.mark.asyncio
async def test_per_key_rpm_limit(client, seed):
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
