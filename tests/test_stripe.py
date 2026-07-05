import json
import os
import time

import httpx
import pytest
import respx

from gateway import db, payments
from gateway.config import get_settings
from gateway.models import Payment, Workspace

ADMIN = {"X-Admin-Token": "test-admin-token"}
STRIPE_SESSIONS = "https://api.stripe.com/v1/checkout/sessions"


def test_signature_roundtrip():
    payload = b'{"hello":"world"}'
    secret = "whsec_test"
    header = payments.sign_stripe_payload(payload, secret, ts=1000)
    assert payments.verify_stripe_signature(payload, header, secret, now=1000)
    # wrong secret
    assert not payments.verify_stripe_signature(payload, header, "nope", now=1000)
    # stale timestamp (beyond tolerance)
    assert not payments.verify_stripe_signature(payload, header, secret, now=999999)


@pytest.fixture
def stripe_env():
    os.environ["STRIPE_SECRET_KEY"] = "sk_test_x"
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    get_settings.cache_clear()
    yield
    os.environ.pop("STRIPE_SECRET_KEY", None)
    os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_checkout_creates_pending_payment(client, seed, stripe_env):
    with respx.mock:
        respx.post(STRIPE_SESSIONS).mock(
            return_value=httpx.Response(
                200, json={"id": "cs_test_123", "url": "https://checkout.stripe.com/pay/cs_test_123"}
            )
        )
        r = await client.post(
            f"/admin/workspaces/{seed['workspace_id']}/checkout",
            json={"amount_cents": 500},
            headers=ADMIN,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["checkout_url"].startswith("https://checkout.stripe.com/")
    assert body["status"] == "pending"

    async with db.get_sessionmaker()() as s:
        p = await s.get(Payment, body["payment_id"])
        assert p.provider == "stripe"
        assert p.provider_ref == "cs_test_123"
        assert p.status == "pending"
        # No credits applied yet.
        ws = await s.get(Workspace, seed["workspace_id"])
        assert ws.credit_micros == 100_000_000


@pytest.mark.asyncio
async def test_webhook_settles_and_applies_credits(client, seed, stripe_env):
    # First create a pending checkout payment.
    with respx.mock:
        respx.post(STRIPE_SESSIONS).mock(
            return_value=httpx.Response(200, json={"id": "cs_1", "url": "https://x/y"})
        )
        r = await client.post(
            f"/admin/workspaces/{seed['workspace_id']}/checkout",
            json={"amount_cents": 500},
            headers=ADMIN,
        )
    payment_id = r.json()["payment_id"]

    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_1", "metadata": {"payment_id": payment_id}}},
    }
    payload = json.dumps(event).encode()
    # The endpoint verifies against real time; sign with a current timestamp.
    ts = int(time.time())
    header = payments.sign_stripe_payload(payload, "whsec_test", ts=ts)

    w = await client.post(
        "/admin/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": header, "Content-Type": "application/json"},
    )
    assert w.status_code == 200
    assert w.json()["result"] == "settled"

    async with db.get_sessionmaker()() as s:
        p = await s.get(Payment, payment_id)
        assert p.status == "paid"
        ws = await s.get(Workspace, seed["workspace_id"])
        assert ws.credit_micros == 100_000_000 + 500 * 1_000_000


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature(client, seed, stripe_env):
    payload = json.dumps({"type": "checkout.session.completed", "data": {"object": {}}}).encode()
    w = await client.post(
        "/admin/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": "t=1,v1=bad", "Content-Type": "application/json"},
    )
    assert w.status_code == 400
