"""Management API (Phase 3): self-serve control plane with RBAC.

All routes require a principal (superuser admin token or a user session token).
Mutations are role-checked per organization and recorded to the activity log.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import activity
from .db import get_session
from .keys import display_prefix, generate_key, hash_key
from .models import (
    ActivityLog,
    ApiKey,
    Membership,
    Organization,
    Project,
    ProjectModel,
    Session,
    User,
    Workspace,
)
from .rbac import Principal, get_principal, hash_token, new_session_token, require_role

router = APIRouter(prefix="/manage")


# --- helpers ----------------------------------------------------------------


async def _org_of_workspace(session: AsyncSession, ws_id: str) -> tuple[Workspace, str | None]:
    ws = await session.get(Workspace, ws_id)
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    return ws, ws.org_id


async def _org_of_project(session: AsyncSession, proj_id: str) -> tuple[Project, str | None]:
    proj = await session.get(Project, proj_id)
    if proj is None:
        raise HTTPException(404, "Project not found")
    ws = await session.get(Workspace, proj.workspace_id)
    return proj, (ws.org_id if ws else None)


def _require_superuser(principal: Principal) -> None:
    if not principal.is_superuser:
        raise HTTPException(403, "Requires the admin token")


# --- users & sessions -------------------------------------------------------


class UserIn(BaseModel):
    email: str


@router.post("/users")
async def create_user(
    body: UserIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    _require_superuser(principal)
    user = User(email=body.email)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return {"id": user.id, "email": user.email}


@router.post("/sessions")
async def create_session(
    body: UserIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    _require_superuser(principal)
    user = await session.scalar(select(User).where(User.email == body.email))
    if user is None:
        raise HTTPException(404, "User not found")
    token = new_session_token()
    session.add(Session(user_id=user.id, token_hash=hash_token(token)))
    await session.commit()
    return {"token": token, "user_id": user.id}


# --- organizations & members ------------------------------------------------


class OrgIn(BaseModel):
    name: str
    owner_email: str | None = None


@router.post("/orgs")
async def create_org(
    body: OrgIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    org = Organization(name=body.name)
    session.add(org)
    await session.flush()

    # Determine the owner: the creating user, or owner_email (superuser).
    owner: User | None = principal.user
    if body.owner_email:
        owner = await session.scalar(select(User).where(User.email == body.owner_email))
        if owner is None:
            raise HTTPException(404, "owner_email user not found")
    if owner is not None:
        session.add(Membership(user_id=owner.id, org_id=org.id, role="owner"))
    await session.commit()
    await activity.record(
        session, actor=principal.actor, action="org.create", org_id=org.id, target=org.name
    )
    return {"id": org.id, "name": org.name}


@router.get("/orgs")
async def list_orgs(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    if principal.is_superuser:
        rows = (await session.scalars(select(Organization))).all()
    else:
        rows = (
            await session.scalars(
                select(Organization)
                .join(Membership, Membership.org_id == Organization.id)
                .where(Membership.user_id == principal.user.id)
            )
        ).all()
    return {"orgs": [{"id": o.id, "name": o.name} for o in rows]}


class MemberIn(BaseModel):
    email: str
    role: str = "member"


@router.post("/orgs/{org_id}/members")
async def add_member(
    org_id: str,
    body: MemberIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    await require_role(session, principal, org_id, "admin")
    if body.role not in ("owner", "admin", "member"):
        raise HTTPException(400, "Invalid role")
    user = await session.scalar(select(User).where(User.email == body.email))
    if user is None:
        raise HTTPException(404, "User not found")
    session.add(Membership(user_id=user.id, org_id=org_id, role=body.role))
    await session.commit()
    await activity.record(
        session, actor=principal.actor, action="member.add", org_id=org_id, target=body.email
    )
    return {"org_id": org_id, "email": body.email, "role": body.role}


@router.get("/orgs/{org_id}/activity")
async def list_activity(
    org_id: str,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    await require_role(session, principal, org_id, "member")
    rows = (
        await session.scalars(
            select(ActivityLog)
            .where(ActivityLog.org_id == org_id)
            .order_by(desc(ActivityLog.created_at))
            .limit(200)
        )
    ).all()
    return {
        "activity": [
            {
                "actor": a.actor,
                "action": a.action,
                "target": a.target,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]
    }


# --- workspaces -------------------------------------------------------------


class WorkspaceIn(BaseModel):
    name: str
    credits: float = 0.0


@router.post("/orgs/{org_id}/workspaces")
async def create_workspace(
    org_id: str,
    body: WorkspaceIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    await require_role(session, principal, org_id, "admin")
    ws = Workspace(
        org_id=org_id, name=body.name, credit_micros=int(body.credits * 1_000_000)
    )
    session.add(ws)
    await session.commit()
    await activity.record(
        session, actor=principal.actor, action="workspace.create", org_id=org_id, target=ws.id
    )
    return {"id": ws.id, "name": ws.name, "org_id": org_id}


class BudgetIn(BaseModel):
    monthly_budget_credits: float


@router.put("/workspaces/{ws_id}/budget")
async def set_budget(
    ws_id: str,
    body: BudgetIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    ws, org_id = await _org_of_workspace(session, ws_id)
    await require_role(session, principal, org_id, "admin")
    ws.monthly_budget_micros = int(body.monthly_budget_credits * 1_000_000)
    session.add(ws)
    await session.commit()
    await activity.record(
        session, actor=principal.actor, action="budget.set", org_id=org_id, target=ws_id
    )
    return {"id": ws.id, "monthly_budget_micros": ws.monthly_budget_micros}


# --- projects ---------------------------------------------------------------


class ProjectIn(BaseModel):
    name: str


@router.post("/workspaces/{ws_id}/projects")
async def create_project(
    ws_id: str,
    body: ProjectIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    ws, org_id = await _org_of_workspace(session, ws_id)
    await require_role(session, principal, org_id, "admin")
    proj = Project(workspace_id=ws_id, name=body.name)
    session.add(proj)
    await session.commit()
    await activity.record(
        session, actor=principal.actor, action="project.create", org_id=org_id, target=proj.id
    )
    return {"id": proj.id, "name": proj.name, "workspace_id": ws_id}


# --- model allowlist --------------------------------------------------------


class ModelIn(BaseModel):
    model_id: str


@router.post("/projects/{proj_id}/models")
async def enable_model(
    proj_id: str,
    body: ModelIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    proj, org_id = await _org_of_project(session, proj_id)
    await require_role(session, principal, org_id, "admin")
    exists = await session.get(ProjectModel, (proj_id, body.model_id))
    if exists is None:
        session.add(ProjectModel(project_id=proj_id, model_id=body.model_id))
        await session.commit()
    return {"project_id": proj_id, "model_id": body.model_id, "enabled": True}


@router.delete("/projects/{proj_id}/models/{model_id}")
async def disable_model(
    proj_id: str,
    model_id: str,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    proj, org_id = await _org_of_project(session, proj_id)
    await require_role(session, principal, org_id, "admin")
    await session.execute(
        delete(ProjectModel).where(
            ProjectModel.project_id == proj_id, ProjectModel.model_id == model_id
        )
    )
    await session.commit()
    return {"project_id": proj_id, "model_id": model_id, "enabled": False}


# --- API keys ---------------------------------------------------------------


class KeyIn(BaseModel):
    name: str = "default"
    rpm_limit: int | None = None


@router.post("/projects/{proj_id}/keys")
async def create_key(
    proj_id: str,
    body: KeyIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    proj, org_id = await _org_of_project(session, proj_id)
    await require_role(session, principal, org_id, "admin")
    raw = generate_key()
    key = ApiKey(
        project_id=proj_id,
        name=body.name,
        key_prefix=display_prefix(raw),
        key_hash=hash_key(raw),
        rpm_limit=body.rpm_limit,
    )
    session.add(key)
    await session.commit()
    await activity.record(
        session, actor=principal.actor, action="key.create", org_id=org_id, target=key.id
    )
    # Raw key returned exactly once.
    return {"id": key.id, "name": key.name, "key": raw}


@router.post("/keys/{key_id}/revoke")
async def revoke_key(
    key_id: str,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    from datetime import datetime, timezone

    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, "Key not found")
    _, org_id = await _org_of_project(session, key.project_id)
    await require_role(session, principal, org_id, "admin")
    key.revoked_at = datetime.now(timezone.utc)
    session.add(key)
    await session.commit()
    await activity.record(
        session, actor=principal.actor, action="key.revoke", org_id=org_id, target=key_id
    )
    return {"id": key_id, "revoked": True}
