import pytest

from gateway.models import role_at_least

ADMIN = {"X-Admin-Token": "test-admin-token"}


def test_role_ordering():
    assert role_at_least("owner", "admin")
    assert role_at_least("admin", "member")
    assert not role_at_least("member", "admin")
    assert not role_at_least("member", "owner")


async def _session_for(client, email, org_id=None, role=None):
    await client.post("/manage/users", json={"email": email}, headers=ADMIN)
    if org_id and role:
        await client.post(
            f"/manage/orgs/{org_id}/members", json={"email": email, "role": role}, headers=ADMIN
        )
    token = (await client.post("/manage/sessions", json={"email": email}, headers=ADMIN)).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_member_cannot_create_workspace(client, engine):
    org = (await client.post("/manage/orgs", json={"name": "Org"}, headers=ADMIN)).json()
    member = await _session_for(client, "m@x.com", org["id"], "member")
    r = await client.post(
        f"/manage/orgs/{org['id']}/workspaces", json={"name": "w"}, headers=member
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_workspace(client, engine):
    org = (await client.post("/manage/orgs", json={"name": "Org"}, headers=ADMIN)).json()
    admin_user = await _session_for(client, "a@x.com", org["id"], "admin")
    r = await client.post(
        f"/manage/orgs/{org['id']}/workspaces", json={"name": "w"}, headers=admin_user
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_no_auth_is_401(client, engine):
    r = await client.post("/manage/orgs", json={"name": "Org"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_non_member_forbidden(client, engine):
    org = (await client.post("/manage/orgs", json={"name": "Org"}, headers=ADMIN)).json()
    outsider = await _session_for(client, "out@x.com")  # no membership
    r = await client.post(
        f"/manage/orgs/{org['id']}/workspaces", json={"name": "w"}, headers=outsider
    )
    assert r.status_code == 403
