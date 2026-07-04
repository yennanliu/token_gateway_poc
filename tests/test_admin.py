import httpx
import pytest
import respx

ADMIN_TOKEN = "test-admin-token"

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
AUTH = {"X-Admin-Token": ADMIN_TOKEN}


async def _make_billed_call(client, seed):
    resp = {
        "model": "gpt-5.4",
        "choices": [{"message": {"role": "assistant", "content": "x"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    with respx.mock:
        respx.post(OPENAI_URL).mock(return_value=httpx.Response(200, json=resp))
        await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {seed['raw_key']}"},
        )


@pytest.mark.asyncio
async def test_summary_requires_admin_token(client, seed):
    r = await client.get(f"/admin/workspaces/{seed['workspace_id']}/summary")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_workspace_summary_shape(client, seed):
    r = await client.get(
        f"/admin/workspaces/{seed['workspace_id']}/summary", headers=AUTH
    )
    assert r.status_code == 200
    body = r.json()
    assert body["credits"] == 100.0
    assert len(body["keys"]) == 1
    assert body["keys"][0]["prefix"].startswith("atp-")
    assert body["keys"][0]["revoked"] is False


@pytest.mark.asyncio
async def test_usage_and_analytics(client, seed):
    await _make_billed_call(client, seed)

    usage = await client.get(
        f"/admin/projects/{seed['project_id']}/usage", headers=AUTH
    )
    assert usage.status_code == 200
    events = usage.json()["events"]
    assert len(events) == 1
    assert events[0]["input_tokens"] == 100

    analytics = await client.get(
        f"/admin/projects/{seed['project_id']}/analytics", headers=AUTH
    )
    assert analytics.status_code == 200
    a = analytics.json()
    assert a["totals"]["requests"] == 1
    assert a["totals"]["input_tokens"] == 100
    assert a["by_model"][0]["model"] == "gpt-5.4"


@pytest.mark.asyncio
async def test_request_logs(client, seed):
    await _make_billed_call(client, seed)
    logs = await client.get(f"/admin/projects/{seed['project_id']}/logs", headers=AUTH)
    assert logs.status_code == 200
    entries = logs.json()["logs"]
    assert len(entries) == 1
    assert entries[0]["endpoint"] == "chat.completions"
    assert entries[0]["status"] == 200
