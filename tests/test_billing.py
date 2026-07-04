import httpx
import pytest
import respx
from sqlalchemy import func, select

from gateway import db, pricing
from gateway.models import LedgerEntry, UsageEvent, Workspace

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def _resp(pt, ct):
    return {
        "model": "gpt-5.4",
        "choices": [{"message": {"role": "assistant", "content": "x"}}],
        "usage": {"prompt_tokens": pt, "completion_tokens": ct},
    }


@pytest.mark.asyncio
async def test_debit_matches_pricing(client, seed):
    with respx.mock:
        respx.post(OPENAI_URL).mock(return_value=httpx.Response(200, json=_resp(100, 50)))
        r = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {seed['raw_key']}"},
        )
    assert r.status_code == 200

    expected = pricing.cost_micros("gpt-5.4", 100, 50)
    async with db.get_sessionmaker()() as s:
        ws = await s.get(Workspace, seed["workspace_id"])
        assert ws.credit_micros == 100_000_000 - expected

        event = await s.scalar(select(UsageEvent))
        assert event.input_tokens == 100
        assert event.output_tokens == 50
        assert event.cost_micros == expected

        ledger_sum = await s.scalar(select(func.sum(LedgerEntry.delta_micros)))
        assert ledger_sum == -expected


@pytest.mark.asyncio
async def test_zero_balance_returns_402_and_does_not_forward(client, seed):
    async with db.get_sessionmaker()() as s:
        ws = await s.get(Workspace, seed["workspace_id"])
        ws.credit_micros = 0
        await s.commit()

    with respx.mock:
        route = respx.post(OPENAI_URL).mock(return_value=httpx.Response(200, json=_resp(1, 1)))
        r = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {seed['raw_key']}"},
        )
    assert r.status_code == 402
    assert not route.called
