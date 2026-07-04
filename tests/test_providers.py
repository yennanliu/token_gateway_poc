import httpx
import pytest
import respx
from sqlalchemy import select

from gateway import db
from gateway.models import UsageEvent

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"


@pytest.mark.asyncio
async def test_anthropic_messages(client, seed):
    resp = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "content": [{"type": "text", "text": "hi"}],
        "usage": {"input_tokens": 7, "output_tokens": 3},
    }
    with respx.mock:
        route = respx.post(ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=resp))
        r = await client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"Authorization": f"Bearer {seed['raw_key']}"},
        )
    assert r.status_code == 200
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "real-anthropic-key"
    async with db.get_sessionmaker()() as s:
        e = await s.scalar(select(UsageEvent))
        assert (e.input_tokens, e.output_tokens) == (7, 3)


@pytest.mark.asyncio
async def test_gemini_generate_content(client, seed):
    resp = {
        "candidates": [{"content": {"parts": [{"text": "hi"}]}}],
        "usageMetadata": {
            "promptTokenCount": 5,
            "candidatesTokenCount": 4,
            "totalTokenCount": 9,
        },
    }
    with respx.mock:
        route = respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=resp))
        r = await client.post(
            "/v1/models/gemini-2.5-pro:generateContent",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
            headers={"x-goog-api-key": seed["raw_key"]},
        )
    assert r.status_code == 200
    sent = route.calls.last.request
    assert sent.headers["x-goog-api-key"] == "real-gemini-key"
    async with db.get_sessionmaker()() as s:
        e = await s.scalar(select(UsageEvent))
        assert (e.input_tokens, e.output_tokens) == (5, 4)


@pytest.mark.asyncio
async def test_list_models_returns_project_allowlist(client, seed):
    r = await client.get(
        "/v1/models", headers={"Authorization": f"Bearer {seed['raw_key']}"}
    )
    assert r.status_code == 200
    body = r.json()
    ids = {m["id"] for m in body["data"]}
    assert ids == {"gpt-5.4", "claude-sonnet-4-6", "gemini-2.5-pro"}
    assert body["object"] == "list"


@pytest.mark.asyncio
async def test_list_models_requires_auth(client, seed):
    r = await client.get("/v1/models")
    assert r.status_code == 401
