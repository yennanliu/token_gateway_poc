"""Role-based access control for the management API (Phase 3).

A *principal* is resolved from either:
- the superuser **admin token** (``X-Admin-Token``), which bypasses role checks; or
- a **user session token** (``Authorization: Bearer sess-…``).

``require_role`` enforces ``owner > admin > member`` within an organization.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session
from .models import Membership, Session, User, role_at_least

SESSION_PREFIX = "sess-"


def new_session_token() -> str:
    return f"{SESSION_PREFIX}{secrets.token_urlsafe(32)}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class Principal:
    is_superuser: bool
    user: User | None = None

    @property
    def actor(self) -> str:
        if self.is_superuser:
            return "admin"
        return self.user.email if self.user else "unknown"


async def get_principal(
    request: Request,
    x_admin_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    if x_admin_token and x_admin_token == get_settings().admin_token:
        return Principal(is_superuser=True)

    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token.startswith(SESSION_PREFIX):
            row = await session.execute(
                select(User)
                .join(Session, Session.user_id == User.id)
                .where(Session.token_hash == hash_token(token))
            )
            user = row.scalar_one_or_none()
            if user is not None:
                return Principal(is_superuser=False, user=user)

    raise HTTPException(status_code=401, detail="Authentication required")


async def require_role(
    session: AsyncSession, principal: Principal, org_id: str, minimum: str
) -> None:
    if principal.is_superuser:
        return
    if principal.user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    role = await session.scalar(
        select(Membership.role).where(
            Membership.user_id == principal.user.id, Membership.org_id == org_id
        )
    )
    if role is None or not role_at_least(role, minimum):
        raise HTTPException(
            status_code=403, detail=f"Requires role '{minimum}' in this organization"
        )
