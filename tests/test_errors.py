import httpx
import pytest
import respx

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


@pytest.mark.asyncio
async def test_anthropic_error_shape_on_401(client, seed):
    r = await client.post(
        "/v1/messages",
        json={"model": "claude-sonnet-4-6", "max_tokens": 8, "messages": []},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_upstream_5xx_passed_through(client, seed):
    with respx.mock:
        respx.post(OPENAI_URL).mock(
            return_value=httpx.Response(503, json={"error": {"message": "down"}})
        )
        r = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {seed['raw_key']}"},
        )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_upstream_connection_error_502(client, seed):
    with respx.mock:
        respx.post(OPENAI_URL).mock(side_effect=httpx.ConnectError("boom"))
        r = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {seed['raw_key']}"},
        )
    assert r.status_code == 502
