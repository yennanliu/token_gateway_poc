"""GET /v1/models — OpenAI-shaped list of the project's enabled models."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth
from ..db import get_session
from ..models import ProjectModel

router = APIRouter()
STYLE = "openai"

# Fixed created timestamp (kept stable; not a real creation time).
_CREATED = 1700000000


@router.get("/v1/models")
async def list_models(request: Request, session: AsyncSession = Depends(get_session)):
    ctx = await auth.authenticate(request, session, STYLE)
    rows = await session.scalars(
        select(ProjectModel.model_id)
        .where(ProjectModel.project_id == ctx.project.id)
        .order_by(ProjectModel.model_id)
    )
    data = [
        {"id": m, "object": "model", "created": _CREATED, "owned_by": "llm-gateway"}
        for m in rows.all()
    ]
    return {"object": "list", "data": data}
