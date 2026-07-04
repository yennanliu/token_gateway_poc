"""Activity/audit log recording (Phase 3)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .models import ActivityLog


async def record(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    org_id: str | None = None,
    target: str | None = None,
) -> None:
    session.add(
        ActivityLog(actor=actor, action=action, org_id=org_id, target=target)
    )
    await session.commit()
