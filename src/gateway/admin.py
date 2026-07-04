"""Admin/console API (Phase 2).

Read-only summaries + top-ups, protected by a static admin token
(``X-Admin-Token`` header). The Vue console calls these. In a real deployment
this would sit behind proper user auth + RBAC (see memberships/roles).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import payments
from .config import get_settings
from .db import get_session
from .models import ApiKey, Project, RequestLog, UsageEvent, Workspace

router = APIRouter(prefix="/admin")


async def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not x_admin_token or x_admin_token != get_settings().admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


def _credits(micros: int) -> float:
    return micros / get_settings().micros_per_credit


@router.get("/workspaces", dependencies=[Depends(require_admin)])
async def list_workspaces(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(Workspace).order_by(Workspace.name))
    return {
        "workspaces": [
            {
                "id": w.id,
                "name": w.name,
                "credit_micros": w.credit_micros,
                "credits": _credits(w.credit_micros),
            }
            for w in rows.all()
        ]
    }


@router.get("/workspaces/{workspace_id}/summary", dependencies=[Depends(require_admin)])
async def workspace_summary(
    workspace_id: str, session: AsyncSession = Depends(get_session)
):
    ws = await session.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    keys = (
        await session.scalars(
            select(ApiKey)
            .join(Project, ApiKey.project_id == Project.id)
            .where(Project.workspace_id == workspace_id)
            .order_by(desc(ApiKey.created_at))
        )
    ).all()

    return {
        "id": ws.id,
        "name": ws.name,
        "credit_micros": ws.credit_micros,
        "credits": _credits(ws.credit_micros),
        "keys": [
            {
                "id": k.id,
                "name": k.name,
                "prefix": k.key_prefix,
                "revoked": k.revoked_at is not None,
                "created_at": k.created_at.isoformat() if k.created_at else None,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in keys
        ],
    }


@router.get("/projects/{project_id}/usage", dependencies=[Depends(require_admin)])
async def project_usage(
    project_id: str, limit: int = 50, session: AsyncSession = Depends(get_session)
):
    rows = (
        await session.scalars(
            select(UsageEvent)
            .where(UsageEvent.project_id == project_id)
            .order_by(desc(UsageEvent.created_at))
            .limit(min(limit, 500))
        )
    ).all()
    return {
        "events": [
            {
                "id": e.id,
                "model": e.model_id,
                "input_tokens": e.input_tokens,
                "output_tokens": e.output_tokens,
                "cost_micros": e.cost_micros,
                "cost_credits": _credits(e.cost_micros),
                "status": e.status,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ]
    }


@router.get("/projects/{project_id}/logs", dependencies=[Depends(require_admin)])
async def project_logs(
    project_id: str, limit: int = 100, session: AsyncSession = Depends(get_session)
):
    rows = (
        await session.scalars(
            select(RequestLog)
            .where(RequestLog.project_id == project_id)
            .order_by(desc(RequestLog.created_at))
            .limit(min(limit, 1000))
        )
    ).all()
    return {
        "logs": [
            {
                "id": r.id,
                "endpoint": r.endpoint,
                "model": r.model_id,
                "status": r.status,
                "latency_ms": r.latency_ms,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/projects/{project_id}/analytics", dependencies=[Depends(require_admin)])
async def project_analytics(
    project_id: str, session: AsyncSession = Depends(get_session)
):
    rows = (
        await session.execute(
            select(
                UsageEvent.model_id,
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0),
                func.coalesce(func.sum(UsageEvent.cost_micros), 0),
            )
            .where(UsageEvent.project_id == project_id)
            .group_by(UsageEvent.model_id)
        )
    ).all()
    by_model = [
        {
            "model": model,
            "requests": int(count),
            "input_tokens": int(in_tok),
            "output_tokens": int(out_tok),
            "cost_micros": int(cost),
            "cost_credits": _credits(int(cost)),
        }
        for (model, count, in_tok, out_tok, cost) in rows
    ]
    return {
        "by_model": by_model,
        "totals": {
            "requests": sum(m["requests"] for m in by_model),
            "input_tokens": sum(m["input_tokens"] for m in by_model),
            "output_tokens": sum(m["output_tokens"] for m in by_model),
            "cost_credits": sum(m["cost_credits"] for m in by_model),
        },
    }


class TopUpRequest(BaseModel):
    amount_cents: int


@router.post("/workspaces/{workspace_id}/topup", dependencies=[Depends(require_admin)])
async def topup(
    workspace_id: str,
    body: TopUpRequest,
    session: AsyncSession = Depends(get_session),
):
    ws = await session.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if body.amount_cents <= 0:
        raise HTTPException(status_code=400, detail="amount_cents must be positive")

    payment = await payments.create_topup(
        session, workspace_id=workspace_id, amount_cents=body.amount_cents
    )
    await session.refresh(ws)
    return {
        "payment_id": payment.id,
        "status": payment.status,
        "provider": payment.provider,
        "credits_added": _credits(payment.credits_micros),
        "balance_credits": _credits(ws.credit_micros),
    }
