from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin_user_session, require_user_session
from app.casdoor_auth import CasdoorAuthError
from app.casdoor_commerce import sync_user_commerce
from app.config import settings
from app.database import get_db
from app.models import CommerceSubscription, Session as SessionModel, UsageCreditGrant, User


router = APIRouter(prefix="/api/commerce", tags=["commerce"])
admin_router = APIRouter(prefix="/api/admin/commerce", tags=["admin-commerce"])


class CommerceSubscriptionItem(BaseModel):
    id: str
    plan: str
    planDisplayName: str | None
    tier: str
    state: str
    period: str | None
    startsAt: datetime | None
    endsAt: datetime | None
    lastSyncedAt: datetime


class CommerceCreditGrantItem(BaseModel):
    id: str
    product: str
    tokens: int
    costMicrousd: int
    capeSubmissions: int
    storageBytes: int
    expiresAt: datetime | None
    revokedAt: datetime | None


class CommerceOverview(BaseModel):
    enabled: bool
    tier: str
    subscriptions: list[CommerceSubscriptionItem]
    creditGrants: list[CommerceCreditGrantItem]


class AdminCommerceSyncResponse(BaseModel):
    userId: int
    tier: str
    activeSubscriptions: int
    totalSubscriptions: int
    syncedAt: datetime


def _subscription_payload(db: Session, user: User) -> CommerceOverview:
    rows = db.execute(select(CommerceSubscription).where(
        CommerceSubscription.user_id == user.id
    ).order_by(CommerceSubscription.created_at.desc())).scalars().all()
    grants = db.execute(select(UsageCreditGrant).where(
        UsageCreditGrant.user_id == user.id
    ).order_by(UsageCreditGrant.created_at.desc())).scalars().all()
    return CommerceOverview.model_validate({
        "enabled": settings.casdoor_commerce_enabled,
        "tier": user.subscription_tier,
        "subscriptions": [{
            "id": row.external_id,
            "plan": row.plan_name,
            "planDisplayName": row.plan_display_name,
            "tier": row.tier,
            "state": row.state,
            "period": row.period,
            "startsAt": row.starts_at,
            "endsAt": row.ends_at,
            "lastSyncedAt": row.last_synced_at,
        } for row in rows],
        "creditGrants": [{
            "id": grant.external_key,
            "product": grant.product_name,
            "tokens": grant.token_credit,
            "costMicrousd": grant.cost_credit_microusd,
            "capeSubmissions": grant.cape_submission_credit,
            "storageBytes": grant.storage_credit_bytes,
            "expiresAt": grant.expires_at,
            "revokedAt": grant.revoked_at,
        } for grant in grants],
    })


@router.get("/subscription", response_model=CommerceOverview)
def get_subscription(db: Session = Depends(get_db), session: SessionModel = Depends(require_user_session)):
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return _subscription_payload(db, user)


@router.post("/subscription/sync", response_model=CommerceOverview)
async def sync_subscription(db: Session = Depends(get_db), session: SessionModel = Depends(require_user_session)):
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.casdoor_subject is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account is not managed by Casdoor")
    try:
        await sync_user_commerce(db, user)
        db.commit()
    except CasdoorAuthError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Casdoor commerce sync is temporarily unavailable") from error
    return _subscription_payload(db, user)


@admin_router.post("/users/{user_id}/sync", response_model=AdminCommerceSyncResponse)
async def admin_sync_subscription(user_id: int, db: Session = Depends(get_db),
                                  _session: SessionModel = Depends(require_admin_user_session)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        result = await sync_user_commerce(db, user)
        db.commit()
    except CasdoorAuthError as error:
        db.rollback()
        raise HTTPException(status_code=503, detail="Casdoor commerce sync is temporarily unavailable") from error
    return {"userId": user.id, "tier": result.tier,
        "activeSubscriptions": result.active_subscription_count,
        "totalSubscriptions": result.total_subscription_count,
        "syncedAt": result.synced_at}
