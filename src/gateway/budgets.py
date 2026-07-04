"""Monthly spend budgets (Phase 4).

A workspace may set ``monthly_budget_micros`` (0 = unlimited). We sum the current
calendar month's usage cost and block new calls once the cap is reached — this is
distinct from running out of prepaid credits.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Project, UsageEvent


def _month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def month_to_date_spend(session: AsyncSession, workspace_id: str) -> int:
    return int(
        await session.scalar(
            select(func.coalesce(func.sum(UsageEvent.cost_micros), 0))
            .join(Project, UsageEvent.project_id == Project.id)
            .where(
                Project.workspace_id == workspace_id,
                UsageEvent.created_at >= _month_start(),
            )
        )
        or 0
    )


async def within_budget(session: AsyncSession, workspace) -> bool:
    """True if the workspace has room under its monthly budget (or none set)."""
    if workspace.monthly_budget_micros <= 0:
        return True
    spent = await month_to_date_spend(session, workspace.id)
    return spent < workspace.monthly_budget_micros
