from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_user_session
from app.database import get_db
from app.models import Organization, OrganizationMember, Session as SessionModel, UsageLedgerEntry, User, Workspace, WorkspaceMember
from app.schemas import MemberUpsert, OrganizationCreate, WorkspaceCreate
from app.tenancy import ensure_personal_workspace, organization_role, require_organization_role
from app.tenancy import sync_casdoor_tenancy
from app.casdoor_auth import CasdoorAuthError, fetch_casdoor_user
from app.usage_governance import organization_usage_totals

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


def _ledger_item(row: UsageLedgerEntry) -> dict:
    return {
        "id": row.id,
        "userId": row.user_id,
        "resourceType": row.resource_type,
        "resourceId": row.resource_id,
        "model": row.model_id,
        "inputTokens": row.input_tokens,
        "outputTokens": row.output_tokens,
        "storageBytes": row.storage_bytes,
        "quantity": row.quantity,
        "costMicrousd": row.cost_microusd,
        "occurredAt": row.occurred_at,
    }


def _member(db: Session, item: OrganizationMember) -> dict:
    user = db.get(User, item.user_id)
    return {"userId": item.user_id, "username": user.username, "displayName": user.display_name, "role": item.role}


@router.get("")
def list_organizations(session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    ensure_personal_workspace(db, session.user_id); db.commit()
    rows = db.execute(select(Organization, OrganizationMember.role).join(OrganizationMember).where(OrganizationMember.user_id == session.user_id).order_by(Organization.name)).all()
    return {"items": [{"id": org.id, "name": org.name, "slug": org.slug, "role": role} for org, role in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_organization(payload: OrganizationCreate, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    slug = payload.slug or f"org-{uuid4().hex[:10]}"
    if db.execute(select(Organization.id).where(Organization.slug == slug)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Organization slug already exists")
    org = Organization(name=payload.name.strip(), slug=slug, created_by_user_id=session.user_id)
    db.add(org); db.flush(); db.add(OrganizationMember(organization_id=org.id, user_id=session.user_id, role="owner"))
    workspace = Workspace(organization_id=org.id, name="默认工作空间", slug="default", created_by_user_id=session.user_id)
    db.add(workspace); db.flush(); db.add(WorkspaceMember(workspace_id=workspace.id, user_id=session.user_id, role="owner")); db.commit()
    return {"id": org.id, "name": org.name, "slug": org.slug, "role": "owner", "defaultWorkspaceId": workspace.id}


@router.get("/{organization_id}")
def get_organization(organization_id: int, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    role = require_organization_role(db, organization_id, session.user_id)
    org = db.get(Organization, organization_id)
    members = db.execute(select(OrganizationMember).where(OrganizationMember.organization_id == organization_id)).scalars().all()
    workspaces = db.execute(select(Workspace).where(Workspace.organization_id == organization_id)).scalars().all()
    return {"id": org.id, "name": org.name, "slug": org.slug, "role": role, "members": [_member(db, m) for m in members], "workspaces": [{"id": w.id, "name": w.name, "slug": w.slug} for w in workspaces]}


@router.get("/{organization_id}/usage/summary")
def get_organization_usage_summary(organization_id: int, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    require_organization_role(db, organization_id, session.user_id, "admin")
    return {
        "organizationId": organization_id,
        "period": datetime.now(timezone.utc).strftime("%Y-%m"),
        "usage": organization_usage_totals(db, organization_id),
    }


@router.get("/{organization_id}/usage/ledger")
def get_organization_usage_ledger(organization_id: int, limit: int = Query(100, ge=1, le=500), session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    require_organization_role(db, organization_id, session.user_id, "admin")
    rows = db.execute(select(UsageLedgerEntry).where(
        UsageLedgerEntry.organization_id == organization_id
    ).order_by(UsageLedgerEntry.occurred_at.desc()).limit(limit)).scalars().all()
    return {"organizationId": organization_id, "items": [_ledger_item(row) for row in rows]}


@router.put("/{organization_id}/members")
def upsert_member(organization_id: int, payload: MemberUpsert, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    actor_role = require_organization_role(db, organization_id, session.user_id, "admin")
    if payload.role == "owner" and actor_role != "owner":
        raise HTTPException(status_code=403, detail="Only owners can grant owner role")
    user = db.execute(select(User).where(func.lower(User.username) == payload.username.strip().lower())).scalar_one_or_none()
    if user is None: raise HTTPException(status_code=404, detail="User not found")
    item = db.execute(select(OrganizationMember).where(OrganizationMember.organization_id == organization_id, OrganizationMember.user_id == user.id)).scalar_one_or_none()
    if item is None: item = OrganizationMember(organization_id=organization_id, user_id=user.id); db.add(item)
    item.role = payload.role
    for workspace in db.execute(select(Workspace).where(Workspace.organization_id == organization_id)).scalars():
        wm = db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id)).scalar_one_or_none()
        if wm is None: db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=payload.role))
        else: wm.role = payload.role
    db.commit(); return _member(db, item)


@router.post("/{organization_id}/workspaces", status_code=201)
def create_workspace(organization_id: int, payload: WorkspaceCreate, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    require_organization_role(db, organization_id, session.user_id, "admin")
    slug = payload.slug or f"workspace-{uuid4().hex[:8]}"
    if db.execute(select(Workspace.id).where(Workspace.organization_id == organization_id, Workspace.slug == slug)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Workspace slug already exists")
    workspace = Workspace(organization_id=organization_id, name=payload.name.strip(), slug=slug, created_by_user_id=session.user_id)
    db.add(workspace); db.flush()
    members = db.execute(select(OrganizationMember).where(OrganizationMember.organization_id == organization_id)).scalars().all()
    db.add_all([WorkspaceMember(workspace_id=workspace.id, user_id=m.user_id, role=m.role) for m in members]); db.commit()
    return {"id": workspace.id, "organizationId": organization_id, "name": workspace.name, "slug": workspace.slug}


@router.post("/{organization_id}/casdoor/sync")
async def sync_organization_from_casdoor(organization_id: int, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    require_organization_role(db, organization_id, session.user_id, "admin")
    organization = db.get(Organization, organization_id)
    if organization is None or organization.identity_source != "casdoor":
        raise HTTPException(status_code=409, detail="Organization is not managed by Casdoor")
    memberships = db.execute(select(OrganizationMember).where(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.identity_source == "casdoor",
    )).scalars().all()
    synced = 0; failed: list[str] = []
    for membership in memberships:
        user = db.get(User, membership.user_id)
        if user is None or not user.casdoor_subject: continue
        try:
            userinfo = await fetch_casdoor_user(user.casdoor_subject)
            next_org, _workspace, _role = sync_casdoor_tenancy(db, user, userinfo)
            if next_org.id != organization_id: failed.append(user.username)
            else: synced += 1
        except CasdoorAuthError:
            failed.append(user.username)
    db.commit()
    return {"organizationId": organization_id, "synced": synced, "failed": failed}
