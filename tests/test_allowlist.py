import httpx
import pytest
import respx

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OK = {
    "model": "gpt-5.4",
    "choices": [{"message": {"role": "assistant", "content": "x"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
}


@pytest.mark.asyncio
async def test_enabled_model_forwards(client, seed):
    with respx.mock:
        route = respx.post(OPENAI_URL).mock(return_value=httpx.Response(200, json=OK))
        r = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {seed['raw_key']}"},
        )
    assert r.status_code == 200
    assert route.called


@pytest.mark.asyncio
async def test_disabled_model_403_no_upstream(client, seed):
    with respx.mock:
        route = respx.post(OPENAI_URL).mock(return_value=httpx.Response(200, json=OK))
        r = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {seed['raw_key']}"},
        )
    assert r.status_code == 403
    assert not route.called
