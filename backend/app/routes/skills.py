from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import require_admin_user_session, require_user_session
from app.audit import record_audit_event
from app.database import get_db
from app.models import Conversation, Message, OrganizationMember, Session as SessionModel, SkillInstallation, SkillPackage, SkillRun, User, now_utc
from app.skill_engine import execute_skill, serialize_run
from app.skill_scanner import scan_skill_directory
from app.skill_security import (assert_data_scope, execution_policy, flattened_permissions, normalize_permissions,
                                package_digest, require_permission_approval, sign_digest, verify_signature)

router = APIRouter(prefix="/api/skills", tags=["skills"])
SKILLS_DIR = Path(__file__).resolve().parents[1].parent / "skills"

class SkillMutation(BaseModel):
    enabled: bool

class SkillRunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    approvedPermissions: list[str] = Field(default_factory=list, max_length=100)
    conversationId: int | None = None
    prompt: str | None = Field(default=None, max_length=8000)

class SkillEntitlementMutation(BaseModel):
    tier: str = Field(pattern="^(standard|professional|enterprise)$")

class SkillReviewMutation(BaseModel):
    status: str = Field(pattern="^(verified|blocked|needs_review)$")

class SkillInstallationMutation(BaseModel):
    enabled: bool

def user_tier(user: User | None) -> str:
    if user is None:
        return "standard"
    return "enterprise" if user.is_admin else user.subscription_tier

def pricing_allowed(pricing: str, tier: str) -> bool:
    if pricing in {"included", "free"}:
        return True
    if pricing == "professional":
        return tier in {"professional", "enterprise"}
    if pricing == "enterprise":
        return tier == "enterprise"
    return False

def serialize(item: SkillPackage, *, installed: bool = False, install_count: int = 0,
              run_count: int = 0, tier: str = "standard", installation_enabled: bool = False) -> dict:
    manifest = json.loads(item.manifest_json or "{}")
    marketplace = manifest.get("marketplace", {}) if isinstance(manifest.get("marketplace"), dict) else {}
    upstream = manifest.get("upstream", {}) if isinstance(manifest.get("upstream"), dict) else {}
    return {"id": item.id, "key": item.skill_key, "name": item.name, "version": item.version,
            "description": item.description, "author": item.author, "source": item.source,
            "sourceUrl": item.source_url, "permissions": json.loads(item.permissions_json or "[]"),
            "permissionDetails": normalize_permissions(manifest), "executionPolicy": execution_policy(manifest),
            "reviewStatus": item.review_status, "enabled": item.enabled,
            "releaseStatus": item.release_status, "changelog": manifest.get("changelog", []),
            "compatibility": manifest.get("compatibility", {"cipher": ">=1.0", "platforms": ["linux"]}),
            "signature": {"status": item.signature_status, "digest": item.package_hash},
            "scanStatus": manifest.get("_scan", {}).get("status", "unknown"),
            "category": str(marketplace.get("category", "security-operations")),
            "license": str(manifest.get("license", "")),
            "upstreamVersion": str(upstream.get("release") or upstream.get("commit") or ""),
            "tags": [str(value) for value in marketplace.get("tags", [])],
            "pricing": str(marketplace.get("pricing", "included")),
            "entitlement": {"tier": tier, "allowed": pricing_allowed(str(marketplace.get("pricing", "included")), tier)},
            "featured": bool(marketplace.get("featured", False)),
            "installed": installed, "installationEnabled": installation_enabled,
            "installCount": install_count, "runCount": run_count,
            "inputs": manifest.get("inputs", {})}


def serialize_many(db: Session, items: list[SkillPackage], user_id: int | None) -> list[dict]:
    skill_ids = [item.id for item in items]
    if not skill_ids:
        return []
    installations = {}
    if user_id is not None:
        installations = {value.skill_id: value for value in db.scalars(select(SkillInstallation).where(
            SkillInstallation.user_id == user_id, SkillInstallation.skill_id.in_(skill_ids)
        )).all()}
    install_counts = dict(db.execute(select(SkillInstallation.skill_id, func.count()).where(
        SkillInstallation.skill_id.in_(skill_ids)
    ).group_by(SkillInstallation.skill_id)).all())
    run_counts = dict(db.execute(select(SkillRun.skill_id, func.count()).where(
        SkillRun.skill_id.in_(skill_ids)
    ).group_by(SkillRun.skill_id)).all())
    tier = user_tier(db.get(User, user_id)) if user_id is not None else "standard"
    return [serialize(item, installed=item.id in installations,
        installation_enabled=bool(installations.get(item.id) and installations[item.id].enabled),
        install_count=int(install_counts.get(item.id, 0)), run_count=int(run_counts.get(item.id, 0)),
        tier=tier) for item in items]

def assert_entitled(db: Session, item: SkillPackage, user_id: int | None) -> None:
    manifest = json.loads(item.manifest_json or "{}")
    marketplace = manifest.get("marketplace", {}) if isinstance(manifest.get("marketplace"), dict) else {}
    tier = user_tier(db.get(User, user_id)) if user_id is not None else "standard"
    if not pricing_allowed(str(marketplace.get("pricing", "included")), tier):
        raise HTTPException(status_code=403, detail="当前套餐不包含此 Skill，请升级套餐后使用")

def admin(request: Request, db: Session = Depends(get_db)) -> SessionModel:
    return require_admin_user_session(request, db)

@router.get("")
def list_skills(request: Request, q: str = Query(default=""), category: str = Query(default=""),
                source: str = Query(default=""),
                installed: bool | None = Query(default=None), db: Session = Depends(get_db),
                session: SessionModel = Depends(require_user_session)) -> dict:
    query = select(SkillPackage).order_by(SkillPackage.name, SkillPackage.version.desc())
    if q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(or_(SkillPackage.name.ilike(needle), SkillPackage.skill_key.ilike(needle), SkillPackage.description.ilike(needle)))
    items = list(db.scalars(query).all())
    serialized = serialize_many(db, items, session.user_id)
    if category.strip(): serialized = [item for item in serialized if item["category"] == category.strip()]
    if source.strip(): serialized = [item for item in serialized if item["source"] == source.strip()]
    if installed is not None: serialized = [item for item in serialized if item["installed"] is installed]
    return {"items": serialized}

@router.post("/sync", status_code=200)
def sync_builtin_skills(db: Session = Depends(get_db), _session: SessionModel = Depends(admin)) -> dict:
    if not SKILLS_DIR.is_dir():
        return {"added": 0, "items": []}
    added = 0
    for manifest_path in SKILLS_DIR.glob("*/skill.yaml"):
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        key, version = str(payload.get("id", "")), str(payload.get("version", "1.0.0"))
        if not key:
            continue
        payload.setdefault("releaseStatus", "published")
        payload.setdefault("compatibility", {"cipher": ">=1.0", "platforms": ["linux"]})
        payload.setdefault("changelog", [{"version": version, "changes": ["首次纳入 Cipher Skill 市场"]}])
        scan = scan_skill_directory(manifest_path.parent, payload)
        payload["_scan"] = scan
        digest = package_digest(manifest_path.parent, payload)
        supplied_signature = str(payload.get("signature") or sign_digest(digest))
        item = db.scalar(select(SkillPackage).where(
            SkillPackage.skill_key == key, SkillPackage.version == version))
        if item is None:
            item = SkillPackage(skill_key=key, version=version)
            db.add(item); added += 1
        item.name = str(payload.get("name", key))
        item.description = str(payload.get("description", ""))
        item.author = str(payload.get("author", "Cipher"))
        item.source = str(payload.get("source", "builtin"))
        item.source_url = str(payload["sourceUrl"]) if payload.get("sourceUrl") else None
        item.permissions_json = json.dumps(flattened_permissions(payload), ensure_ascii=False)
        item.package_hash, item.signature = digest, supplied_signature
        item.signature_status = "verified" if verify_signature(digest, supplied_signature) else "invalid"
        item.release_status = str(payload.get("releaseStatus", "published"))
        item.review_status = "blocked" if scan["status"] == "critical" else "needs_review" if scan["findings"] else "verified"
        if item.signature_status != "verified": item.review_status = "blocked"
        item.manifest_json = json.dumps(payload, ensure_ascii=False)
        if item.review_status != "verified": item.enabled = False
    db.commit()
    items = list(db.scalars(select(SkillPackage)).all())
    return {"added": added, "items": serialize_many(db, items, _session.user_id)}

@router.get("/history")
def list_skill_runs(db: Session = Depends(get_db), session: SessionModel = Depends(require_user_session)) -> dict:
    runs = list(db.scalars(select(SkillRun).where(SkillRun.user_id == session.user_id)
        .order_by(SkillRun.created_at.desc()).limit(30)).all())
    return {"items": [serialize_run(run) for run in runs]}

@router.post("/{skill_id}/install", status_code=201)
def install_skill(skill_id: int, db: Session = Depends(get_db), session: SessionModel = Depends(require_user_session)) -> dict:
    item = db.get(SkillPackage, skill_id)
    if item is None: raise HTTPException(status_code=404, detail="Skill not found")
    if not item.enabled or item.review_status != "verified" or item.release_status != "published" or item.signature_status != "verified":
        raise HTTPException(status_code=409, detail="Skill 尚未上架或未通过安全审核")
    assert_entitled(db, item, session.user_id)
    installation = db.scalar(select(SkillInstallation).where(
        SkillInstallation.skill_id == skill_id, SkillInstallation.user_id == session.user_id))
    if installation is None:
        permissions = json.loads(item.permissions_json or "[]")
        db.add(SkillInstallation(skill_id=skill_id, user_id=session.user_id or 0,
                                 approved_permissions_json=json.dumps(permissions, ensure_ascii=False))); db.commit()
    return serialize_many(db, [item], session.user_id)[0]

@router.delete("/{skill_id}/install", status_code=200)
def uninstall_skill(skill_id: int, db: Session = Depends(get_db), session: SessionModel = Depends(require_user_session)) -> dict:
    item = db.get(SkillPackage, skill_id)
    if item is None: raise HTTPException(status_code=404, detail="Skill not found")
    installation = db.scalar(select(SkillInstallation).where(
        SkillInstallation.skill_id == skill_id, SkillInstallation.user_id == session.user_id))
    if installation is not None: db.delete(installation); db.commit()
    return serialize_many(db, [item], session.user_id)[0]

@router.patch("/{skill_id}/install")
def set_installation(skill_id: int, payload: SkillInstallationMutation, db: Session = Depends(get_db),
                     session: SessionModel = Depends(require_user_session)) -> dict:
    item = db.get(SkillPackage, skill_id)
    installation = db.scalar(select(SkillInstallation).where(
        SkillInstallation.skill_id == skill_id, SkillInstallation.user_id == session.user_id))
    if item is None or installation is None: raise HTTPException(status_code=404, detail="Skill installation not found")
    installation.enabled = payload.enabled; db.commit()
    return serialize_many(db, [item], session.user_id)[0]

@router.get("/{skill_id}/scan")
def scan_installed_skill(skill_id: int, db: Session = Depends(get_db), _session: SessionModel = Depends(admin)) -> dict:
    item = db.get(SkillPackage, skill_id)
    if item is None: raise HTTPException(status_code=404, detail="Skill not found")
    manifest = json.loads(item.manifest_json or "{}")
    directory = SKILLS_DIR / item.skill_key
    result = scan_skill_directory(directory, manifest)
    manifest["_scan"] = result
    item.manifest_json = json.dumps(manifest, ensure_ascii=False)
    item.review_status = "blocked" if result["status"] == "critical" else "needs_review" if result["findings"] else "verified"
    if item.review_status != "verified": item.enabled = False
    db.commit()
    return result

@router.patch("/{skill_id}")
def set_skill(skill_id: int, payload: SkillMutation, request: Request, db: Session = Depends(get_db), session: SessionModel = Depends(admin)) -> dict:
    item = db.get(SkillPackage, skill_id)
    if item is None: raise HTTPException(status_code=404, detail="Skill not found")
    if payload.enabled and item.review_status != "verified":
        raise HTTPException(status_code=409, detail="Skill 尚未通过安全审核，不能启用")
    item.enabled = payload.enabled
    record_audit_event(db, event_type="admin.skill", action="skill.enable" if payload.enabled else "skill.disable",
                       request=request, actor_user_id=session.user_id, resource_type="skill",
                       resource_id=item.id, detail={"key": item.skill_key, "version": item.version})
    db.commit(); db.refresh(item)
    return serialize(item)

@router.post("/{skill_id}/review")
def review_skill(skill_id: int, payload: SkillReviewMutation, request: Request, db: Session = Depends(get_db),
                 session: SessionModel = Depends(admin)) -> dict:
    item = db.get(SkillPackage, skill_id)
    if item is None: raise HTTPException(status_code=404, detail="Skill not found")
    if payload.status == "verified" and item.signature_status != "verified":
        raise HTTPException(status_code=409, detail="签名无效，不能通过审核")
    item.review_status = payload.status
    if payload.status != "verified": item.enabled = False
    record_audit_event(db, event_type="admin.skill", action="skill.review", request=request,
                       actor_user_id=session.user_id, resource_type="skill", resource_id=item.id,
                       detail={"status": payload.status, "signatureStatus": item.signature_status})
    db.commit(); return serialize(item)

@router.post("/{skill_id}/rollback")
def rollback_skill(skill_id: int, request: Request, db: Session = Depends(get_db), session: SessionModel = Depends(admin)) -> dict:
    current = db.get(SkillPackage, skill_id)
    if current is None: raise HTTPException(status_code=404, detail="Skill not found")
    versions = list(db.scalars(select(SkillPackage).where(SkillPackage.skill_key == current.skill_key,
        SkillPackage.id != current.id, SkillPackage.review_status == "verified",
        SkillPackage.signature_status == "verified").order_by(SkillPackage.created_at.desc())).all())
    if not versions: raise HTTPException(status_code=409, detail="没有可回滚的已验证版本")
    target = versions[0]; current.release_status, current.enabled = "rolled_back", False
    target.release_status, target.enabled = "published", True
    record_audit_event(db, event_type="admin.skill", action="skill.rollback", request=request,
                       actor_user_id=session.user_id, resource_type="skill", resource_id=target.id,
                       detail={"fromVersion": current.version, "toVersion": target.version})
    db.commit(); return serialize_many(db, [target], session.user_id)[0]

@router.post("/{skill_id}/runs", status_code=201)
def run_skill(skill_id: int, payload: SkillRunRequest, request: Request, db: Session = Depends(get_db), session: SessionModel = Depends(require_user_session)) -> dict:
    skill = db.get(SkillPackage, skill_id)
    if skill is None: raise HTTPException(status_code=404, detail="Skill not found")
    if not skill.enabled or skill.review_status != "verified" or skill.signature_status != "verified":
        raise HTTPException(status_code=409, detail="Skill 尚未启用或未通过安全审核")
    assert_entitled(db, skill, session.user_id)
    installation = db.scalar(select(SkillInstallation).where(
        SkillInstallation.skill_id == skill_id, SkillInstallation.user_id == session.user_id))
    if installation is None:
        raise HTTPException(status_code=409, detail="请先安装 Skill 再运行")
    if not installation.enabled: raise HTTPException(status_code=409, detail="Skill 已被用户禁用")
    permissions = json.loads(skill.permissions_json or "[]")
    approved = payload.approvedPermissions or json.loads(installation.approved_permissions_json or "[]")
    require_permission_approval(permissions, approved)
    organization_ids = set(db.scalars(select(OrganizationMember.organization_id).where(
        OrganizationMember.user_id == session.user_id)).all())
    assert_data_scope(payload.input, session.user_id or 0, organization_ids)
    conversation = None
    if payload.conversationId is not None:
        conversation = db.scalar(select(Conversation).where(
            Conversation.id == payload.conversationId,
            Conversation.owner_user_id == session.user_id,
        ))
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    run = execute_skill(db, skill, session.user_id or 0, payload.input, execution_policy(json.loads(skill.manifest_json or "{}")))
    record_audit_event(db, event_type="skill.execute", action="skill.run", request=request,
                       actor_user_id=session.user_id, resource_type="skill_run", resource_id=run.id,
                       detail={"skillId": skill.id, "skillKey": skill.skill_key,
                               "caseId": run.case_id, "status": run.status})
    db.commit()
    response = serialize_run(run)
    if conversation is not None:
        user_content = (payload.prompt or f"/{skill.skill_key}").strip()
        output = response["output"]
        summary = str(output.get("summary") or f"{skill.name} 已完成")
        detail = json.dumps(output, ensure_ascii=False, indent=2)
        assistant_content = f"## {skill.name}\n\n{summary}\n\n```json\n{detail}\n```\n\n> Skill `{skill.skill_key}` · v{skill.version} · Run #{run.id}"
        user_message = Message(conversation_id=conversation.id, role="user", content=user_content)
        assistant_message = Message(conversation_id=conversation.id, role="assistant", content=assistant_content)
        db.add_all([user_message, assistant_message])
        conversation.updated_at = now_utc()
        db.commit(); db.refresh(user_message); db.refresh(assistant_message)
        response["conversationMessages"] = [
            {"id": user_message.id, "role": user_message.role, "content": user_message.content, "createdAt": user_message.created_at},
            {"id": assistant_message.id, "role": assistant_message.role, "content": assistant_message.content, "createdAt": assistant_message.created_at},
        ]
    return response

@router.patch("/entitlements/users/{user_id}")
def set_user_entitlement(user_id: int, payload: SkillEntitlementMutation,
                         db: Session = Depends(get_db), _session: SessionModel = Depends(admin)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.subscription_tier = payload.tier
    db.commit()
    return {"userId": user.id, "tier": user_tier(user)}

@router.get("/runs/{run_id}")
def get_skill_run(run_id: int, db: Session = Depends(get_db), session: SessionModel = Depends(require_user_session)) -> dict:
    run = db.get(SkillRun, run_id)
    if run is None or run.user_id != session.user_id: raise HTTPException(status_code=404, detail="Skill run not found")
    return serialize_run(run)
