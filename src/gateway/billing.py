"""Credit ledger operations — all money changes go through here.

Every debit is one atomic transaction: insert a UsageEvent, insert a negative
LedgerEntry, and decrement the workspace balance. Top-ups are the positive dual.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import pricing
from .models import ApiKey, LedgerEntry, UsageEvent, Workspace


async def has_credit(session: AsyncSession, workspace_id: str) -> bool:
    bal = await session.scalar(
        select(Workspace.credit_micros).where(Workspace.id == workspace_id)
    )
    return bal is not None and bal > 0


async def balance(session: AsyncSession, workspace_id: str) -> int:
    return (
        await session.scalar(
            select(Workspace.credit_micros).where(Workspace.id == workspace_id)
        )
        or 0
    )


async def record_usage_and_debit(
    session: AsyncSession,
    *,
    workspace_id: str,
    api_key_id: str,
    project_id: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    status: int = 200,
) -> UsageEvent:
    """Meter a completed call and debit the workspace, atomically."""
    cost = pricing.cost_micros(model_id, input_tokens, output_tokens)

    event = UsageEvent(
        api_key_id=api_key_id,
        project_id=project_id,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_micros=cost,
        status=status,
    )
    session.add(event)
    session.add(
        LedgerEntry(
            workspace_id=workspace_id,
            delta_micros=-cost,
            reason=f"usage:{model_id}",
        )
    )
    await session.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(credit_micros=Workspace.credit_micros - cost)
    )
    await session.commit()
    await session.refresh(event)
    return event


async def top_up(
    session: AsyncSession,
    *,
    workspace_id: str,
    credits_micros: int,
    reason: str = "topup",
) -> None:
    session.add(
        LedgerEntry(
            workspace_id=workspace_id, delta_micros=credits_micros, reason=reason
        )
    )
    await session.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(credit_micros=Workspace.credit_micros + credits_micros)
    )
    await session.commit()
