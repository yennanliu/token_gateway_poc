import httpx
import pytest
import respx
from sqlalchemy import select

from gateway import db, pricing
from gateway.models import UsageEvent, Workspace

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

SSE = (
    b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
    b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":8}}\n\n'
    b"data: [DONE]\n\n"
)


@pytest.mark.asyncio
async def test_stream_passthrough_and_billed(client, seed):
    with respx.mock:
        respx.post(OPENAI_URL).mock(
            return_value=httpx.Response(200, content=SSE, headers={"content-type": "text/event-stream"})
        )
        r = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-5.4",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"Authorization": f"Bearer {seed['raw_key']}"},
        )
        assert r.status_code == 200
        assert b"hello" in r.content.replace(b'"', b"").replace(b" ", b"") or b"hel" in r.content
        assert b"[DONE]" in r.content

    expected = pricing.cost_micros("gpt-5.4", 12, 8)
    async with db.get_sessionmaker()() as s:
        event = await s.scalar(select(UsageEvent))
        assert event is not None
        assert (event.input_tokens, event.output_tokens) == (12, 8)
        ws = await s.get(Workspace, seed["workspace_id"])
        assert ws.credit_micros == 100_000_000 - expected
