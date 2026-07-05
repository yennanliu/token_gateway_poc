"""Payments / credit top-ups (Phase 2 + completion).

Two modes, chosen by config:
- **mock** (no ``STRIPE_SECRET_KEY``): a top-up settles immediately.
- **stripe** (key set): create a real Checkout Session; credits are applied when
  the ``checkout.session.completed`` webhook is verified and processed.

The Stripe REST API is called via httpx (no extra SDK dependency).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import billing
from .config import get_settings
from .models import Payment


def credits_for_cents(cents: int) -> int:
    """Micro-credits purchased for a USD-cent amount (1 credit = 1 cent)."""
    s = get_settings()
    credits = cents // s.cents_per_credit
    return credits * s.micros_per_credit


def is_stripe_enabled() -> bool:
    return bool(get_settings().stripe_secret_key)


async def create_topup(
    session: AsyncSession, *, workspace_id: str, amount_cents: int
) -> Payment:
    """Mock-mode top-up: record + settle immediately (used by /admin/.../topup)."""
    payment = Payment(
        workspace_id=workspace_id,
        amount_cents=amount_cents,
        credits_micros=credits_for_cents(amount_cents),
        provider="stripe" if is_stripe_enabled() else "mock",
        status="pending",
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    if not is_stripe_enabled():
        await settle_payment(session, payment)
    return payment


async def create_checkout_session(
    session: AsyncSession, *, workspace_id: str, amount_cents: int
) -> tuple[Payment, str]:
    """Create a Stripe Checkout Session; returns (payment, checkout_url)."""
    s = get_settings()
    payment = Payment(
        workspace_id=workspace_id,
        amount_cents=amount_cents,
        credits_micros=credits_for_cents(amount_cents),
        provider="stripe",
        status="pending",
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)

    form = {
        "mode": "payment",
        "success_url": s.stripe_success_url,
        "cancel_url": s.stripe_cancel_url,
        "client_reference_id": payment.id,
        "metadata[payment_id]": payment.id,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(amount_cents),
        "line_items[0][price_data][product_data][name]": "Gateway credits top-up",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{s.stripe_api_base}/v1/checkout/sessions",
            data=form,
            headers={"Authorization": f"Bearer {s.stripe_secret_key}"},
        )
    resp.raise_for_status()
    obj = resp.json()
    payment.provider_ref = obj.get("id")
    session.add(payment)
    await session.commit()
    return payment, obj.get("url", "")


async def settle_payment(session: AsyncSession, payment: Payment) -> None:
    """Mark paid + apply credits (idempotent)."""
    if payment.status == "paid":
        return
    await billing.top_up(
        session,
        workspace_id=payment.workspace_id,
        credits_micros=payment.credits_micros,
        reason=f"topup:{payment.provider}:{payment.id}",
    )
    payment.status = "paid"
    session.add(payment)
    await session.commit()


# --- Stripe webhook signature verification ---------------------------------


def verify_stripe_signature(
    payload: bytes, sig_header: str, secret: str, *, tolerance: int = 300, now: int | None = None
) -> bool:
    """Verify Stripe's ``Stripe-Signature`` header (t=…,v1=…) via HMAC-SHA256."""
    if not sig_header or not secret:
        return False
    parts = dict(
        p.split("=", 1) for p in sig_header.split(",") if "=" in p
    )
    ts = parts.get("t")
    v1 = parts.get("v1")
    if not ts or not v1:
        return False
    now = int(time.time()) if now is None else now
    if abs(now - int(ts)) > tolerance:
        return False
    signed = f"{ts}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


def sign_stripe_payload(payload: bytes, secret: str, ts: int) -> str:
    """Build a valid Stripe-Signature header (used by tests / local tooling)."""
    signed = f"{ts}.".encode() + payload
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


async def handle_webhook_event(session: AsyncSession, payload: bytes) -> str:
    """Process a verified Stripe event. Returns a short status string."""
    event = json.loads(payload)
    if event.get("type") != "checkout.session.completed":
        return "ignored"
    obj = event.get("data", {}).get("object", {})
    payment_id = (obj.get("metadata") or {}).get("payment_id") or obj.get(
        "client_reference_id"
    )
    if not payment_id:
        # fall back to provider_ref (session id)
        session_id = obj.get("id")
        payment = await session.scalar(
            select(Payment).where(Payment.provider_ref == session_id)
        )
    else:
        payment = await session.get(Payment, payment_id)
    if payment is None:
        return "not_found"
    await settle_payment(session, payment)
    return "settled"
