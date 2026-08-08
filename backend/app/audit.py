from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, User, now_utc


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def _hash_payload(*, previous_hash: str | None, created_at: datetime, payload: dict[str, Any]) -> str:
    # SQLite drops timezone information when round-tripping datetimes. Hash a
    # normalized representation so verification is stable across databases.
    normalized_created_at = created_at.replace(tzinfo=None).isoformat()
    material = f"{previous_hash or ''}\n{normalized_created_at}\n{_canonical(payload)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def record_audit_event(
    db: Session,
    *,
    event_type: str,
    action: str,
    request: Request | None = None,
    actor_user_id: int | None = None,
    actor_username: str | None = None,
    outcome: str = "success",
    organization_id: int | None = None,
    workspace_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    if actor_username is None and actor_user_id is not None:
        user = db.get(User, actor_user_id)
        actor_username = user.username if user is not None else None
    previous_hash = db.scalar(select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1))
    created_at = now_utc()
    safe_detail = detail or {}
    payload = {
        "eventType": event_type,
        "action": action,
        "outcome": outcome,
        "actorUserId": actor_user_id,
        "actorUsername": actor_username,
        "actorIp": request.client.host if request is not None and request.client else None,
        "userAgent": request.headers.get("user-agent", "")[:512] if request is not None else None,
        "organizationId": organization_id,
        "workspaceId": workspace_id,
        "resourceType": resource_type,
        "resourceId": str(resource_id) if resource_id is not None else None,
        "detail": safe_detail,
    }
    item = AuditLog(
        event_type=event_type,
        action=action,
        outcome=outcome,
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        actor_ip=payload["actorIp"],
        user_agent=payload["userAgent"],
        organization_id=organization_id,
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=payload["resourceId"],
        detail_json=_canonical(safe_detail),
        previous_hash=previous_hash,
        entry_hash=_hash_payload(previous_hash=previous_hash, created_at=created_at, payload=payload),
        created_at=created_at,
    )
    db.add(item)
    db.flush()
    return item


def verify_audit_chain(items: list[AuditLog]) -> tuple[bool, int | None]:
    previous_hash: str | None = None
    for item in items:
        payload = {
            "eventType": item.event_type, "action": item.action, "outcome": item.outcome,
            "actorUserId": item.actor_user_id, "actorUsername": item.actor_username,
            "actorIp": item.actor_ip, "userAgent": item.user_agent,
            "organizationId": item.organization_id, "workspaceId": item.workspace_id,
            "resourceType": item.resource_type, "resourceId": item.resource_id,
            "detail": json.loads(item.detail_json or "{}"),
        }
        expected = _hash_payload(previous_hash=previous_hash, created_at=item.created_at, payload=payload)
        if item.previous_hash != previous_hash or item.entry_hash != expected:
            return False, item.id
        previous_hash = item.entry_hash
    return True, None
