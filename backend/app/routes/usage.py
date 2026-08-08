from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_user_session
from app.config import settings
from app.database import get_db
from app.models import Session as SessionModel, UsageLedgerEntry
from app.usage_governance import policy_for_user, usage_totals

router = APIRouter(prefix="/api/usage", tags=["usage"])


class UsageSummary(BaseModel):
    plan: str
    period: str
    usage: dict[str, int | float]
    limits: dict[str, int | bool]
    warnings: list[str]
    billingCnyPerUsd: float


@router.get("/summary", response_model=UsageSummary)
def summary(db: Session = Depends(get_db), session: SessionModel = Depends(require_user_session)):
    policy, used = policy_for_user(db, session.user_id), usage_totals(db, session.user_id)
    limits = {"tokens": policy.monthly_tokens, "costMicrousd": policy.monthly_cost_microusd,
              "concurrentRequests": policy.concurrent_requests, "capeSubmissions": policy.monthly_cape_submissions,
              "storageBytes": policy.storage_bytes, "hardLimit": policy.hard_limit, "warningPercent": policy.warning_percent}
    warnings = [name for name, limit_key in (("tokens", "tokens"), ("cost", "costMicrousd"),
        ("CAPE submissions", "capeSubmissions"), ("storage", "storageBytes"))
        if limits[limit_key] and used[limit_key] * 100 >= int(limits[limit_key]) * policy.warning_percent]
    from app.models import User
    user = db.get(User, session.user_id)
    return UsageSummary(
        plan=user.subscription_tier,
        period=datetime.utcnow().strftime("%Y-%m"),
        usage={
            **used,
            "capeCostCny": round(
                used["capeCostMicrousd"] * float(settings.billing_cny_per_usd) / 1_000_000,
                6,
            ),
        },
        limits=limits,
        warnings=warnings,
        billingCnyPerUsd=float(settings.billing_cny_per_usd),
    )


@router.get("/ledger")
def ledger(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db),
           session: SessionModel = Depends(require_user_session)):
    rows = db.execute(select(UsageLedgerEntry).where(UsageLedgerEntry.user_id == session.user_id)
        .order_by(UsageLedgerEntry.occurred_at.desc()).limit(limit)).scalars().all()
    return {"items": [{"id": r.id, "resourceType": r.resource_type, "resourceId": r.resource_id,
        "model": r.model_id, "inputTokens": r.input_tokens, "outputTokens": r.output_tokens,
        "storageBytes": r.storage_bytes, "quantity": r.quantity, "costMicrousd": r.cost_microusd,
        "occurredAt": r.occurred_at} for r in rows]}
