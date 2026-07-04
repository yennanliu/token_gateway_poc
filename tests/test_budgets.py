import httpx
import pytest
import respx

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ADMIN = {"X-Admin-Token": "test-admin-token"}


def _resp(pt, ct):
    return {
        "model": "gpt-5.4",
        "choices": [{"message": {"role": "assistant", "content": "x"}}],
        "usage": {"prompt_tokens": pt, "completion_tokens": ct},
    }


@pytest.mark.asyncio
async def test_monthly_budget_blocks_after_cap(client, seed):
    # Tiny budget: first call fits (spend starts at 0), second is over.
    r = await client.put(
        f"/manage/workspaces/{seed['workspace_id']}/budget",
        json={"monthly_budget_credits": 0.0005},  # 500 micros
        headers=ADMIN,
    )
    assert r.status_code == 200

    body = {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    headers = {"Authorization": f"Bearer {seed['raw_key']}"}
    with respx.mock:
        respx.post(OPENAI_URL).mock(return_value=httpx.Response(200, json=_resp(100, 50)))
        first = await client.post("/v1/chat/completions", json=body, headers=headers)
        second = await client.post("/v1/chat/completions", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 402
    assert second.json()["error"]["type"] == "budget_exceeded"
