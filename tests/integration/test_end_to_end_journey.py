"""End-to-end integration: control plane -> proxy call -> billing/analytics/metrics.

Exercises RBAC-driven provisioning (manage API with a user session), a real
proxied + billed chat call (upstream mocked), then the console/admin read side
(summary, usage, analytics, logs, /metrics), a top-up, and key revocation.
"""

import httpx
import pytest
import respx

ADMIN = {"X-Admin-Token": "test-admin-token"}
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
COMPLETION = {
    "model": "gpt-5.4",
    "choices": [{"message": {"role": "assistant", "content": "hello"}}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
}


@pytest.mark.asyncio
async def test_full_journey(client, engine):
    # --- provision via the control plane, acting as an org owner (RBAC) ---
    await client.post("/manage/users", json={"email": "owner@acme.com"}, headers=ADMIN)
    org = (await client.post("/manage/orgs", json={"name": "Acme", "owner_email": "owner@acme.com"}, headers=ADMIN)).json()
    token = (await client.post("/manage/sessions", json={"email": "owner@acme.com"}, headers=ADMIN)).json()["token"]
    owner = {"Authorization": f"Bearer {token}"}

    ws = (await client.post(f"/manage/orgs/{org['id']}/workspaces", json={"name": "prod", "credits": 1}, headers=owner)).json()
    proj = (await client.post(f"/manage/workspaces/{ws['id']}/projects", json={"name": "app"}, headers=owner)).json()
    await client.post(f"/manage/projects/{proj['id']}/models", json={"model_id": "gpt-5.4"}, headers=owner)
    key = (await client.post(f"/manage/projects/{proj['id']}/keys", json={"name": "prod-key"}, headers=owner)).json()
    raw = key["key"]
    assert raw.startswith("gw-")

    # --- make a real (mocked-upstream) proxied call ---
    with respx.mock:
        respx.post(OPENAI_URL).mock(return_value=httpx.Response(200, json=COMPLETION))
        r = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {raw}"},
        )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hello"

    # --- billing: balance debited by exactly the metered cost ---
    from gateway import pricing
    cost_credits = pricing.cost_micros("gpt-5.4", 100, 50) / 1_000_000
    summary = (await client.get(f"/admin/workspaces/{ws['id']}/summary", headers=ADMIN)).json()
    assert summary["credits"] == pytest.approx(1 - cost_credits)
    assert summary["keys"][0]["name"] == "prod-key"

    # --- analytics + usage + logs reflect the call ---
    analytics = (await client.get(f"/admin/projects/{proj['id']}/analytics", headers=ADMIN)).json()
    assert analytics["totals"]["requests"] == 1
    assert analytics["totals"]["input_tokens"] == 100
    usage = (await client.get(f"/admin/projects/{proj['id']}/usage", headers=ADMIN)).json()
    assert usage["events"][0]["output_tokens"] == 50
    logs = (await client.get(f"/admin/projects/{proj['id']}/logs", headers=ADMIN)).json()
    assert logs["logs"][0]["endpoint"] == "chat.completions"
    assert logs["logs"][0]["status"] == 200

    # --- metrics endpoint ---
    metrics_text = (await client.get("/metrics")).text
    assert 'gateway_requests_total{endpoint="chat.completions",model="gpt-5.4",status="200"} 1' in metrics_text

    # --- top-up increases the balance ---
    topup = (await client.post(f"/admin/workspaces/{ws['id']}/topup", json={"amount_cents": 500}, headers=ADMIN)).json()
    assert topup["balance_credits"] == pytest.approx(1 - cost_credits + 500)

    # --- activity log captured the provisioning ---
    activity = (await client.get(f"/manage/orgs/{org['id']}/activity", headers=owner)).json()
    actions = {a["action"] for a in activity["activity"]}
    assert {"org.create", "workspace.create", "project.create", "key.create"} <= actions

    # --- revoke the key -> proxy no longer authenticates ---
    await client.post(f"/manage/keys/{key['id']}/revoke", headers=owner)
    r = await client.get("/v1/models", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 401
