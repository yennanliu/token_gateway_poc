"""Authentication + request guarding.

Extracts the ``atp-…`` key from any accepted location, resolves it to a
project/workspace, and (via ``guard``) enforces credit balance, the model
allowlist, and rate limits before a request is forwarded upstream.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import billing, budgets, errors
from .config import get_settings
from .keys import hash_key
from .models import ApiKey, Project, ProjectModel, Workspace
from .ratelimit import limiter


@dataclass
class AuthContext:
    api_key: ApiKey
    project: Project
    workspace: Workspace


def extract_key(request: Request) -> str | None:
    """Read the key from Authorization / x-api-key / x-goog-api-key / ?key=."""
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    for header in ("x-api-key", "x-goog-api-key"):
        val = request.headers.get(header)
        if val:
            return val.strip()
    q = request.query_params.get("key")
    if q:
        return q.strip()
    return None


async def resolve_key(session: AsyncSession, raw_key: str) -> AuthContext | None:
    row = await session.execute(
        select(ApiKey, Project, Workspace)
        .join(Project, ApiKey.project_id == Project.id)
        .join(Workspace, Project.workspace_id == Workspace.id)
        .where(ApiKey.key_hash == hash_key(raw_key))
    )
    result = row.first()
    if result is None:
        return None
    api_key, project, workspace = result
    if api_key.revoked_at is not None:
        return None
    return AuthContext(api_key=api_key, project=project, workspace=workspace)


async def authenticate(
    request: Request, session: AsyncSession, style: errors.Style
) -> AuthContext:
    raw = extract_key(request)
    if not raw:
        raise errors.unauthorized(style)
    ctx = await resolve_key(session, raw)
    if ctx is None:
        raise errors.unauthorized(style)
    return ctx


async def model_enabled(session: AsyncSession, project_id: str, model_id: str) -> bool:
    hit = await session.scalar(
        select(ProjectModel.model_id).where(
            ProjectModel.project_id == project_id,
            ProjectModel.model_id == model_id,
        )
    )
    return hit is not None


async def guard(
    request: Request,
    session: AsyncSession,
    *,
    model: str,
    style: errors.Style,
) -> AuthContext:
    """Full pre-flight: auth -> rate limit -> credit -> allowlist."""
    ctx = await authenticate(request, session, style)

    rpm = ctx.api_key.rpm_limit
    if rpm is None:
        rpm = get_settings().default_rpm_limit
    if not limiter.allow(ctx.api_key.id, rpm):
        raise errors.rate_limited(style)

    if not await billing.has_credit(session, ctx.workspace.id):
        raise errors.payment_required(style)

    if not await budgets.within_budget(session, ctx.workspace):
        raise errors.GatewayError(
            402, "budget_exceeded", "Monthly spend budget exceeded.", style
        )

    if not await model_enabled(session, ctx.project.id, model):
        raise errors.forbidden_model(model, style)

    return ctx
