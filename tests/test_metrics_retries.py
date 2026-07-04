import os

import httpx
import pytest
import respx

from gateway.config import get_settings

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OK = {
    "model": "gpt-5.4",
    "choices": [{"message": {"role": "assistant", "content": "x"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


@pytest.mark.asyncio
async def test_metrics_increment(client, seed):
    with respx.mock:
        respx.post(OPENAI_URL).mock(return_value=httpx.Response(200, json=OK))
        await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {seed['raw_key']}"},
        )
    m = await client.get("/metrics")
    assert m.status_code == 200
    text = m.text
    assert 'gateway_requests_total{endpoint="chat.completions",model="gpt-5.4",status="200"} 1' in text
    assert 'gateway_input_tokens_total{model="gpt-5.4"} 10' in text
    assert 'gateway_output_tokens_total{model="gpt-5.4"} 5' in text


@pytest.mark.asyncio
async def test_upstream_retries_then_succeeds(client, seed):
    os.environ["RETRY_BACKOFF_SECONDS"] = "0"
    get_settings.cache_clear()
    try:
        with respx.mock:
            route = respx.post(OPENAI_URL).mock(
                side_effect=[
                    httpx.Response(503, json={"error": {"message": "busy"}}),
                    httpx.Response(200, json=OK),
                ]
            )
            r = await client.post(
                "/v1/chat/completions",
                json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": f"Bearer {seed['raw_key']}"},
            )
        assert r.status_code == 200
        assert route.call_count == 2
    finally:
        os.environ.pop("RETRY_BACKOFF_SECONDS", None)
        get_settings.cache_clear()
