"""Payments / credit top-ups (Phase 2).

Two modes, chosen by config:
- **mock** (no Stripe key): a top-up is recorded and credits applied immediately.
- **stripe** (STRIPE_SECRET_KEY set): a Checkout session is created and credits
  are applied when the webhook confirms payment.

The Stripe path is written against the HTTP API via httpx so it needs no extra
dependency; without a key it is never exercised.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from . import billing
from .config import get_settings
from .models import Payment


def credits_for_cents(cents: int) -> int:
    """Return micro-credits purchased for a USD-cent amount (1 credit = 1 cent)."""
    s = get_settings()
    credits = cents // s.cents_per_credit
    return credits * s.micros_per_credit


def is_stripe_enabled() -> bool:
    return bool(get_settings().stripe_secret_key)


async def create_topup(
    session: AsyncSession, *, workspace_id: str, amount_cents: int
) -> Payment:
    """Create a payment record. In mock mode it settles immediately."""
    micros = credits_for_cents(amount_cents)
    payment = Payment(
        workspace_id=workspace_id,
        amount_cents=amount_cents,
        credits_micros=micros,
        provider="stripe" if is_stripe_enabled() else "mock",
        status="pending",
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)

    if not is_stripe_enabled():
        await settle_payment(session, payment)

    return payment


async def settle_payment(session: AsyncSession, payment: Payment) -> None:
    """Mark a payment paid and apply its credits (idempotent)."""
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
