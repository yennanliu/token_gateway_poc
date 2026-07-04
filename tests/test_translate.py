import os

import httpx
import pytest
import respx

from gateway import translate
from gateway.config import get_settings

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def test_openai_to_anthropic_extracts_system_and_max_tokens():
    body = {
        "model": "claude-sonnet-4-6",
        "messages": [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
        ],
    }
    out = translate.openai_to_anthropic(body)
    assert out["system"] == "be brief"
    assert out["messages"] == [{"role": "user", "content": "hi"}]
    assert out["max_tokens"] == 1024


def test_anthropic_to_openai_shape():
    resp = {
        "id": "msg_1",
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }
    out = translate.anthropic_to_openai(resp, "claude-sonnet-4-6")
    assert out["object"] == "chat.completion"
    assert out["choices"][0]["message"]["content"] == "hello"
    assert out["usage"]["prompt_tokens"] == 5


@pytest.mark.asyncio
async def test_openai_endpoint_translates_to_anthropic(client, seed):
    os.environ["ENABLE_TRANSLATION"] = "true"
    get_settings.cache_clear()
    try:
        anthropic_resp = {
            "id": "msg_1",
            "content": [{"type": "text", "text": "hi there"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 6, "output_tokens": 4},
        }
        with respx.mock:
            route = respx.post(ANTHROPIC_URL).mock(
                return_value=httpx.Response(200, json=anthropic_resp)
            )
            r = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "claude-sonnet-4-6",
                    "messages": [{"role": "user", "content": "hi"}],
                },
                headers={"Authorization": f"Bearer {seed['raw_key']}"},
            )
        assert r.status_code == 200
        data = r.json()
        # Response is OpenAI-shaped even though upstream was Anthropic.
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["content"] == "hi there"
        # Upstream got the real Anthropic key + translated body.
        sent = route.calls.last.request
        assert sent.headers["x-api-key"] == "real-anthropic-key"
        assert b"max_tokens" in sent.content
    finally:
        os.environ["ENABLE_TRANSLATION"] = "false"
        get_settings.cache_clear()
