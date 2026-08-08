from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.auth import require_user_session
from app.database import get_db
from app.models import Notification, NotificationPreference, OrganizationMember, Session as SessionModel, now_utc
from app.notifications import NOTIFICATION_TYPES

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class PreferenceUpdate(BaseModel):
    inApp: bool
    email: bool = False
    webPush: bool = False


def _organization_ids(db: Session, user_id: int) -> list[int]:
    return list(db.execute(select(OrganizationMember.organization_id).where(
        OrganizationMember.user_id == user_id
    )).scalars().all())


def _base_query(db: Session, session: SessionModel, organization_id: int | None):
    allowed = _organization_ids(db, session.user_id)
    if organization_id is not None and organization_id not in allowed:
        raise HTTPException(status_code=403, detail="Organization access denied")
    scope = [organization_id] if organization_id is not None else allowed
    return select(Notification).where(Notification.user_id == session.user_id, Notification.organization_id.in_(scope))


def _serialize(item: Notification) -> dict:
    return {"id": item.id, "organizationId": item.organization_id, "type": item.notification_type,
            "title": item.title, "body": item.body, "caseId": item.case_id,
            "resourceType": item.resource_type, "resourceId": item.resource_id,
            "resourceUrl": item.resource_url, "readAt": item.read_at, "createdAt": item.created_at}


@router.get("")
def list_notifications(unread_only: bool = False, notification_type: str | None = Query(None, alias="type"),
                       organization_id: int | None = None, limit: int = Query(50, ge=1, le=100),
                       session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    query = _base_query(db, session, organization_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if notification_type:
        if notification_type not in NOTIFICATION_TYPES:
            raise HTTPException(status_code=422, detail="Unsupported notification type")
        query = query.where(Notification.notification_type == notification_type)
    items = db.execute(query.order_by(Notification.created_at.desc()).limit(limit)).scalars().all()
    unread_count = db.execute(select(func.count(Notification.id)).where(
        Notification.user_id == session.user_id,
        Notification.organization_id.in_(_organization_ids(db, session.user_id)),
        Notification.read_at.is_(None),
    )).scalar_one()
    return {"items": [_serialize(item) for item in items], "unreadCount": unread_count}


@router.put("/read-all")
def mark_all_read(organization_id: int | None = None, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    query = _base_query(db, session, organization_id).where(Notification.read_at.is_(None))
    ids = list(db.execute(query.with_only_columns(Notification.id)).scalars().all())
    if ids:
        db.execute(update(Notification).where(Notification.id.in_(ids)).values(read_at=now_utc()))
        db.commit()
    return {"updated": len(ids)}


@router.put("/{notification_id}/read")
def mark_notification_read(notification_id: int, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    item = db.execute(_base_query(db, session, None).where(Notification.id == notification_id)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    item.read_at = now_utc(); db.commit()
    return {"id": item.id, "readAt": item.read_at}


@router.delete("/{notification_id}", status_code=204)
def delete_notification(notification_id: int, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> Response:
    item = db.execute(_base_query(db, session, None).where(Notification.id == notification_id)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.delete(item); db.commit()
    return Response(status_code=204)


@router.get("/preferences")
def get_preferences(organization_id: int, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    _base_query(db, session, organization_id)
    rows = db.execute(select(NotificationPreference).where(
        NotificationPreference.organization_id == organization_id,
        NotificationPreference.user_id == session.user_id,
    )).scalars().all()
    by_type = {item.notification_type: item for item in rows}
    return {"organizationId": organization_id, "items": [{"type": kind,
        "inApp": by_type[kind].in_app_enabled if kind in by_type else True,
        "email": by_type[kind].email_enabled if kind in by_type else False,
        "webPush": by_type[kind].web_push_enabled if kind in by_type else False} for kind in NOTIFICATION_TYPES]}


@router.put("/preferences/{notification_type}")
def update_preference(notification_type: str, organization_id: int, payload: PreferenceUpdate,
                      session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)) -> dict:
    if notification_type not in NOTIFICATION_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported notification type")
    _base_query(db, session, organization_id)
    item = db.execute(select(NotificationPreference).where(
        NotificationPreference.organization_id == organization_id,
        NotificationPreference.user_id == session.user_id,
        NotificationPreference.notification_type == notification_type,
    )).scalar_one_or_none()
    if item is None:
        item = NotificationPreference(organization_id=organization_id, user_id=session.user_id, notification_type=notification_type)
        db.add(item)
    item.in_app_enabled, item.email_enabled, item.web_push_enabled = payload.inApp, payload.email, payload.webPush
    db.commit()
    return {"type": notification_type, "inApp": item.in_app_enabled, "email": item.email_enabled, "webPush": item.web_push_enabled}
