import pytest

from gateway import db, payments
from gateway.models import Payment, Workspace

ADMIN_TOKEN = "test-admin-token"
AUTH = {"X-Admin-Token": ADMIN_TOKEN}


def test_credits_for_cents():
    # $5.00 => 500 cents => 500 credits => 500 * 1_000_000 micros
    assert payments.credits_for_cents(500) == 500 * 1_000_000
    assert payments.credits_for_cents(100_000) == 100_000 * 1_000_000


@pytest.mark.asyncio
async def test_topup_applies_credits_in_mock_mode(client, seed):
    r = await client.post(
        f"/admin/workspaces/{seed['workspace_id']}/topup",
        json={"amount_cents": 500},
        headers=AUTH,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "mock"
    assert body["status"] == "paid"
    assert body["credits_added"] == 500.0
    # started at 100 credits (100_000_000 micros) + 500 = 600
    assert body["balance_credits"] == 600.0

    async with db.get_sessionmaker()() as s:
        ws = await s.get(Workspace, seed["workspace_id"])
        assert ws.credit_micros == 100_000_000 + 500 * 1_000_000
        p = await s.get(Payment, body["payment_id"])
        assert p.status == "paid"


@pytest.mark.asyncio
async def test_topup_rejects_nonpositive(client, seed):
    r = await client.post(
        f"/admin/workspaces/{seed['workspace_id']}/topup",
        json={"amount_cents": 0},
        headers=AUTH,
    )
    assert r.status_code == 400
