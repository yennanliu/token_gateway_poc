import httpx
import pytest
import respx

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

COMPLETION = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "model": "gpt-5.4",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
}


@pytest.mark.asyncio
async def test_chat_completion_forwarded(client, seed):
    with respx.mock:
        route = respx.post(OPENAI_URL).mock(
            return_value=httpx.Response(200, json=COMPLETION)
        )
        body = {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
        r = await client.post(
            "/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {seed['raw_key']}"},
        )

    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hi"

    # Upstream received our REAL key, not the client's atp- key.
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer real-openai-key"
    assert b"gpt-5.4" in sent.content


@pytest.mark.asyncio
async def test_missing_model_is_400(client, seed):
    r = await client.post(
        "/v1/chat/completions",
        json={"messages": []},
        headers={"Authorization": f"Bearer {seed['raw_key']}"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_request_error"
