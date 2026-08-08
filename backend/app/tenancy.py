from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    CaseAccess, InvestigationCase, Organization, OrganizationMember, User,
    Workspace, WorkspaceMember,
)
from app.config import settings

ROLE_RANK = {"viewer": 10, "analyst": 20, "reviewer": 30, "admin": 40, "owner": 50}


def _slug(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")[:48]
    return base or f"org-{uuid4().hex[:8]}"


def ensure_personal_workspace(db: Session, user_id: int) -> tuple[Organization, Workspace]:
    membership = db.execute(
        select(OrganizationMember).where(OrganizationMember.user_id == user_id).order_by(OrganizationMember.id)
    ).scalars().first()
    if membership:
        organization = db.get(Organization, membership.organization_id)
        workspace = db.execute(
            select(Workspace).where(Workspace.organization_id == organization.id).order_by(Workspace.id)
        ).scalars().first()
        if workspace:
            if db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user_id)).scalar_one_or_none() is None:
                db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user_id, role=membership.role))
            return organization, workspace

    user = db.get(User, user_id)
    name = f"{(user.display_name or user.username) if user else '个人'}的组织"
    organization = Organization(name=name, slug=f"{_slug(name)}-{uuid4().hex[:6]}", created_by_user_id=user_id)
    db.add(organization); db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=user_id, role="owner"))
    workspace = Workspace(organization_id=organization.id, name="默认工作空间", slug="default", created_by_user_id=user_id)
    db.add(workspace); db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user_id, role="owner"))
    return organization, workspace


def _claim_strings(userinfo: dict[str, Any], name: str) -> list[str]:
    value = userinfo.get(name)
    values = value if isinstance(value, list) else value.split(",") if isinstance(value, str) else []
    result: list[str] = []
    for item in values:
        if isinstance(item, str) and item.strip(): result.append(item.strip())
        elif isinstance(item, dict):
            candidate = item.get("name") or item.get("displayName")
            if isinstance(candidate, str) and candidate.strip(): result.append(candidate.strip())
    return list(dict.fromkeys(result))


def _casdoor_organization(userinfo: dict[str, Any]) -> str:
    for key in ("organization", "organizationName", "owner"):
        value = userinfo.get(key)
        if isinstance(value, str) and value.strip(): return value.strip()
    subject = userinfo.get("sub") or userinfo.get("id")
    if isinstance(subject, str) and "/" in subject: return subject.split("/", 1)[0]
    return settings.casdoor_organization_name.strip()


def sync_casdoor_tenancy(db: Session, user: User, userinfo: dict[str, Any]) -> tuple[Organization, Workspace, str]:
    external_org = _casdoor_organization(userinfo)
    if not external_org:
        raise HTTPException(status_code=400, detail="Casdoor identity has no organization")
    organization = db.execute(select(Organization).where(
        Organization.identity_source == "casdoor", Organization.external_id == external_org
    )).scalar_one_or_none()
    if organization is None:
        organization = Organization(
            name=external_org, slug=f"casdoor-{_slug(external_org)}-{uuid4().hex[:6]}",
            created_by_user_id=user.id, identity_source="casdoor", external_id=external_org,
        )
        db.add(organization); db.flush()

    mapped = settings.casdoor_cipher_role_mapping
    roles = [mapped[item.casefold()] for item in _claim_strings(userinfo, "roles") if item.casefold() in mapped]
    role = max(roles, key=lambda item: ROLE_RANK[item]) if roles else "viewer"
    membership = db.execute(select(OrganizationMember).where(
        OrganizationMember.organization_id == organization.id, OrganizationMember.user_id == user.id
    )).scalar_one_or_none()
    if membership is None:
        membership = OrganizationMember(organization_id=organization.id, user_id=user.id)
        db.add(membership)
    membership.role = role; membership.identity_source = "casdoor"

    stale_org_memberships = db.execute(select(OrganizationMember).where(
        OrganizationMember.user_id == user.id,
        OrganizationMember.identity_source == "casdoor",
        OrganizationMember.organization_id != organization.id,
    )).scalars().all()
    for item in stale_org_memberships: db.delete(item)

    default_workspace = db.execute(select(Workspace).where(
        Workspace.organization_id == organization.id, Workspace.slug == "default"
    )).scalar_one_or_none()
    if default_workspace is None:
        default_workspace = Workspace(organization_id=organization.id, name="默认工作空间", slug="default", created_by_user_id=user.id, identity_source="casdoor", external_id=f"{external_org}:default")
        db.add(default_workspace); db.flush()

    desired_workspaces = {default_workspace.id: default_workspace}
    if settings.casdoor_sync_groups_as_workspaces:
        for group in _claim_strings(userinfo, "groups"):
            external_id = f"{external_org}:{group}"
            workspace = db.execute(select(Workspace).where(Workspace.organization_id == organization.id, Workspace.identity_source == "casdoor", Workspace.external_id == external_id)).scalar_one_or_none()
            if workspace is None:
                workspace = Workspace(organization_id=organization.id, name=group[:120], slug=f"group-{_slug(group)}-{uuid4().hex[:5]}", created_by_user_id=user.id, identity_source="casdoor", external_id=external_id)
                db.add(workspace); db.flush()
            desired_workspaces[workspace.id] = workspace

    existing = db.execute(select(WorkspaceMember).join(Workspace).where(
        Workspace.organization_id == organization.id, WorkspaceMember.user_id == user.id,
        WorkspaceMember.identity_source == "casdoor",
    )).scalars().all()
    existing_by_workspace = {item.workspace_id: item for item in existing}
    for workspace_id in desired_workspaces:
        item = existing_by_workspace.pop(workspace_id, None)
        if item is None: db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=role, identity_source="casdoor"))
        else: item.role = role
    for item in existing_by_workspace.values(): db.delete(item)
    db.flush()
    return organization, default_workspace, role


def organization_role(db: Session, organization_id: int, user_id: int) -> str | None:
    member = db.execute(select(OrganizationMember).where(
        OrganizationMember.organization_id == organization_id, OrganizationMember.user_id == user_id
    )).scalar_one_or_none()
    return member.role if member else None


def require_organization_role(db: Session, organization_id: int, user_id: int, minimum: str = "viewer") -> str:
    role = organization_role(db, organization_id, user_id)
    if role is None or ROLE_RANK.get(role, 0) < ROLE_RANK[minimum]:
        raise HTTPException(status_code=403, detail="Insufficient organization permission")
    return role


def accessible_case_query(user_id: int):
    return select(InvestigationCase).outerjoin(
        OrganizationMember,
        (OrganizationMember.organization_id == InvestigationCase.organization_id)
        & (OrganizationMember.user_id == user_id),
    ).outerjoin(
        CaseAccess,
        (CaseAccess.case_id == InvestigationCase.id) & (CaseAccess.user_id == user_id),
    ).where(or_(
        InvestigationCase.owner_user_id == user_id,
        OrganizationMember.id.is_not(None),
        CaseAccess.id.is_not(None),
    )).distinct()


def require_case_access(db: Session, case_id: int, user_id: int, *, write: bool = False, manage: bool = False) -> InvestigationCase:
    case = db.execute(accessible_case_query(user_id).where(InvestigationCase.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.owner_user_id == user_id:
        return case
    direct = db.execute(select(CaseAccess).where(CaseAccess.case_id == case.id, CaseAccess.user_id == user_id)).scalar_one_or_none()
    role = organization_role(db, case.organization_id, user_id) if case.organization_id else None
    if manage and ROLE_RANK.get(role or "", 0) < ROLE_RANK["admin"]:
        raise HTTPException(status_code=403, detail="Case management permission required")
    if write and direct is not None and direct.permission == "viewer":
        raise HTTPException(status_code=403, detail="Case is read-only")
    if write and direct is None and ROLE_RANK.get(role or "", 0) < ROLE_RANK["analyst"]:
        raise HTTPException(status_code=403, detail="Case write permission required")
    return case
