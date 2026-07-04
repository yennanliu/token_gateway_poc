import pytest

ADMIN = {"X-Admin-Token": "test-admin-token"}


async def _bootstrap_owner_session(client):
    await client.post("/manage/users", json={"email": "owner@x.com"}, headers=ADMIN)
    org = (
        await client.post(
            "/manage/orgs", json={"name": "Org", "owner_email": "owner@x.com"}, headers=ADMIN
        )
    ).json()
    token = (
        await client.post("/manage/sessions", json={"email": "owner@x.com"}, headers=ADMIN)
    ).json()["token"]
    return org["id"], {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_full_control_plane_flow(client, engine):
    org_id, owner = await _bootstrap_owner_session(client)

    ws = (
        await client.post(
            f"/manage/orgs/{org_id}/workspaces",
            json={"name": "prod-ws", "credits": 10},
            headers=owner,
        )
    ).json()
    proj = (
        await client.post(
            f"/manage/workspaces/{ws['id']}/projects", json={"name": "prod"}, headers=owner
        )
    ).json()
    await client.post(
        f"/manage/projects/{proj['id']}/models", json={"model_id": "gpt-5.4"}, headers=owner
    )
    key = (
        await client.post(
            f"/manage/projects/{proj['id']}/keys", json={"name": "k1"}, headers=owner
        )
    ).json()
    assert key["key"].startswith("atp-")

    # The freshly minted key works against the proxy surface.
    r = await client.get(
        "/v1/models", headers={"Authorization": f"Bearer {key['key']}"}
    )
    assert r.status_code == 200
    assert {m["id"] for m in r.json()["data"]} == {"gpt-5.4"}

    # Revoke -> key no longer authenticates.
    await client.post(f"/manage/keys/{key['id']}/revoke", headers=owner)
    r = await client.get("/v1/models", headers={"Authorization": f"Bearer {key['key']}"})
    assert r.status_code == 401

    # Activity log captured the mutations.
    acts = (await client.get(f"/manage/orgs/{org_id}/activity", headers=owner)).json()
    actions = {a["action"] for a in acts["activity"]}
    assert {"org.create", "workspace.create", "project.create", "key.create", "key.revoke"} <= actions


@pytest.mark.asyncio
async def test_disable_model(client, engine):
    org_id, owner = await _bootstrap_owner_session(client)
    ws = (await client.post(f"/manage/orgs/{org_id}/workspaces", json={"name": "w"}, headers=owner)).json()
    proj = (await client.post(f"/manage/workspaces/{ws['id']}/projects", json={"name": "p"}, headers=owner)).json()
    await client.post(f"/manage/projects/{proj['id']}/models", json={"model_id": "gpt-5.4"}, headers=owner)
    await client.delete(f"/manage/projects/{proj['id']}/models/gpt-5.4", headers=owner)
    key = (await client.post(f"/manage/projects/{proj['id']}/keys", json={}, headers=owner)).json()
    r = await client.get("/v1/models", headers={"Authorization": f"Bearer {key['key']}"})
    assert r.json()["data"] == []
