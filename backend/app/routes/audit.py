from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import verify_audit_chain
from app.auth import require_admin_user_session
from app.database import get_db
from app.models import AuditLog, Session as SessionModel

router = APIRouter(prefix="/api/admin/audit-logs", tags=["audit"])


def _query(*, event_type: str, actor: str, resource_type: str, outcome: str,
           date_from: datetime | None, date_to: datetime | None):
    query = select(AuditLog)
    if event_type: query = query.where(AuditLog.event_type == event_type)
    if actor: query = query.where(AuditLog.actor_username.ilike(f"%{actor}%"))
    if resource_type: query = query.where(AuditLog.resource_type == resource_type)
    if outcome: query = query.where(AuditLog.outcome == outcome)
    if date_from: query = query.where(AuditLog.created_at >= date_from)
    if date_to: query = query.where(AuditLog.created_at <= date_to)
    return query


def _serialize(item: AuditLog) -> dict:
    return {
        "id": item.id, "eventType": item.event_type, "action": item.action,
        "outcome": item.outcome, "actorUserId": item.actor_user_id,
        "actorUsername": item.actor_username, "actorIp": item.actor_ip,
        "organizationId": item.organization_id, "workspaceId": item.workspace_id,
        "resourceType": item.resource_type, "resourceId": item.resource_id,
        "detail": json.loads(item.detail_json or "{}"), "previousHash": item.previous_hash,
        "entryHash": item.entry_hash, "createdAt": item.created_at,
    }


@router.get("")
def list_audit_logs(
    event_type: str = Query(default="", alias="eventType"), actor: str = Query(default=""),
    resource_type: str = Query(default="", alias="resourceType"), outcome: str = Query(default=""),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200, alias="pageSize"),
    db: Session = Depends(get_db), _session: SessionModel = Depends(require_admin_user_session),
) -> dict:
    base = _query(event_type=event_type, actor=actor, resource_type=resource_type,
                  outcome=outcome, date_from=date_from, date_to=date_to)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(base.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_serialize(item) for item in items], "total": total, "page": page, "pageSize": page_size}


@router.get("/verify")
def verify_logs(db: Session = Depends(get_db), _session: SessionModel = Depends(require_admin_user_session)) -> dict:
    items = list(db.scalars(select(AuditLog).order_by(AuditLog.id)).all())
    valid, broken_at = verify_audit_chain(items)
    return {"valid": valid, "entries": len(items), "brokenAtId": broken_at}


@router.get("/export")
def export_audit_logs(
    event_type: str = Query(default="", alias="eventType"), actor: str = Query(default=""),
    resource_type: str = Query(default="", alias="resourceType"), outcome: str = Query(default=""),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db), _session: SessionModel = Depends(require_admin_user_session),
) -> Response:
    items = db.scalars(_query(event_type=event_type, actor=actor, resource_type=resource_type,
        outcome=outcome, date_from=date_from, date_to=date_to).order_by(AuditLog.id)).all()
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["id", "created_at", "event_type", "action", "outcome", "actor_user_id",
                     "actor_username", "actor_ip", "resource_type", "resource_id", "detail", "entry_hash"])
    for item in items:
        writer.writerow([item.id, item.created_at.isoformat(), item.event_type, item.action, item.outcome,
                         item.actor_user_id, item.actor_username, item.actor_ip, item.resource_type,
                         item.resource_id, item.detail_json, item.entry_hash])
    return Response(content=output.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="cipher-audit-logs.csv"'})
