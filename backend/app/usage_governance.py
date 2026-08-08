from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import math

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import ChatRequestMetric, OrganizationMember, QuotaOverride, UsageCreditGrant, UsageLedgerEntry, User
from app.observability import emit_event


@dataclass(frozen=True)
class QuotaPolicy:
    monthly_tokens: int
    monthly_cost_microusd: int
    concurrent_requests: int
    monthly_cape_submissions: int
    storage_bytes: int
    hard_limit: bool = True
    warning_percent: int = 80


PLANS = {
    "free": QuotaPolicy(200_000, 500_000, 1, 3, 250 * 1024**2),
    "standard": QuotaPolicy(2_000_000, 10_000_000, 3, 30, 5 * 1024**3),
    "pro": QuotaPolicy(20_000_000, 100_000_000, 10, 300, 50 * 1024**3),
    "enterprise": QuotaPolicy(200_000_000, 1_000_000_000, 50, 5_000, 1024**4),
}

# input/output price in micro-USD per 1M tokens. Keep pricing versioned in code;
# ledger rows retain the charged amount so later price changes never rewrite history.
MODEL_PRICES = {
    "deepseek-v4-flash": (100_000, 400_000),
    "deepseek-v4-pro": (500_000, 2_000_000),
    "chatgpt-5.5-official": (2_000_000, 8_000_000),
    "chatgpt-5.4-az": (1_500_000, 6_000_000),
    "claude-sonnet-4-6-az": (3_000_000, 15_000_000),
}
DEFAULT_PRICE = (2_000_000, 10_000_000)


def month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def daily_model_spend(db: Session, user_id: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(UsageLedgerEntry.cost_microusd), 0)).where(
        UsageLedgerEntry.user_id == user_id,
        UsageLedgerEntry.resource_type == "model",
        UsageLedgerEntry.occurred_at >= day_start(),
    )) or 0)


def organization_id_for_user(db: Session, user_id: int) -> int | None:
    return db.execute(select(OrganizationMember.organization_id).where(
        OrganizationMember.user_id == user_id
    ).order_by(OrganizationMember.id)).scalars().first()


def policy_for_user(db: Session, user_id: int) -> QuotaPolicy:
    user = db.get(User, user_id)
    policy = PLANS.get((user.subscription_tier if user else "free").lower(), PLANS["standard"])
    org_id = organization_id_for_user(db, user_id)
    overrides = []
    if org_id is not None:
        overrides.append(db.execute(select(QuotaOverride).where(
            QuotaOverride.scope_type == "organization", QuotaOverride.scope_id == org_id
        )).scalar_one_or_none())
    overrides.append(db.execute(select(QuotaOverride).where(
        QuotaOverride.scope_type == "user", QuotaOverride.scope_id == user_id
    )).scalar_one_or_none())
    for item in overrides:
        if item is None:
            continue
        policy = replace(policy, **{
            field: getattr(item, field) if getattr(item, field) is not None else getattr(policy, field)
            for field in ("monthly_tokens", "monthly_cost_microusd", "concurrent_requests", "monthly_cape_submissions", "storage_bytes")
        }, hard_limit=item.hard_limit, warning_percent=item.warning_percent)
    credits = db.execute(select(
        func.coalesce(func.sum(UsageCreditGrant.token_credit), 0),
        func.coalesce(func.sum(UsageCreditGrant.cost_credit_microusd), 0),
        func.coalesce(func.sum(UsageCreditGrant.cape_submission_credit), 0),
        func.coalesce(func.sum(UsageCreditGrant.storage_credit_bytes), 0),
    ).where(
        UsageCreditGrant.user_id == user_id,
        UsageCreditGrant.revoked_at.is_(None),
        or_(UsageCreditGrant.expires_at.is_(None), UsageCreditGrant.expires_at > datetime.now(timezone.utc)),
    )).one()
    policy = replace(policy,
        monthly_tokens=policy.monthly_tokens + int(credits[0]),
        monthly_cost_microusd=policy.monthly_cost_microusd + int(credits[1]),
        monthly_cape_submissions=policy.monthly_cape_submissions + int(credits[2]),
        storage_bytes=policy.storage_bytes + int(credits[3]))
    return policy


def _usage_totals(db: Session, *scope_filters: object) -> dict[str, int]:
    row = db.execute(select(
        func.coalesce(func.sum(UsageLedgerEntry.input_tokens + UsageLedgerEntry.output_tokens), 0),
        func.coalesce(func.sum(UsageLedgerEntry.cost_microusd), 0),
        func.coalesce(func.sum(UsageLedgerEntry.cost_microusd).filter(UsageLedgerEntry.resource_type == "model"), 0),
        func.coalesce(func.sum(UsageLedgerEntry.cost_microusd).filter(UsageLedgerEntry.resource_type == "cape"), 0),
        func.coalesce(func.sum(UsageLedgerEntry.storage_bytes), 0),
        func.coalesce(func.sum(UsageLedgerEntry.quantity).filter(UsageLedgerEntry.resource_type == "cape"), 0),
    ).where(*scope_filters, UsageLedgerEntry.occurred_at >= month_start())).one()
    return {
        "tokens": int(row[0]),
        "costMicrousd": int(row[1]),
        "modelCostMicrousd": int(row[2]),
        "capeCostMicrousd": int(row[3]),
        "storageBytes": int(row[4]),
        "capeSubmissions": int(row[5]),
    }


def usage_totals(db: Session, user_id: int) -> dict[str, int]:
    return _usage_totals(db, UsageLedgerEntry.user_id == user_id)


def organization_usage_totals(db: Session, organization_id: int) -> dict[str, int]:
    return _usage_totals(db, UsageLedgerEntry.organization_id == organization_id)


def enforce_quota(
    db: Session,
    user_id: int,
    resource_type: str,
    *,
    storage_bytes: int = 0,
    projected_tokens: int = 0,
    projected_cost_microusd: int = 0,
) -> None:
    policy, used = policy_for_user(db, user_id), usage_totals(db, user_id)
    if not policy.hard_limit:
        return
    violations = []
    if resource_type == "model":
        # A worker or tunnel disconnect can leave a metric in ``running``
        # after the response is gone. Do not let such stale rows permanently
        # consume the user's concurrency quota.
        active_request_cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        running = db.scalar(select(func.count(ChatRequestMetric.id)).where(
            ChatRequestMetric.user_id == user_id,
            ChatRequestMetric.status == "running",
            ChatRequestMetric.started_at >= active_request_cutoff,
        )) or 0
        if used["tokens"] >= policy.monthly_tokens or used["tokens"] + projected_tokens > policy.monthly_tokens:
            violations.append("monthly token quota")
        if used["costMicrousd"] >= policy.monthly_cost_microusd or used["costMicrousd"] + projected_cost_microusd > policy.monthly_cost_microusd:
            violations.append("monthly cost budget")
        if running >= policy.concurrent_requests: violations.append("concurrent request limit")
    if resource_type == "cape" and used["capeSubmissions"] >= policy.monthly_cape_submissions:
        violations.append("monthly CAPE submission quota")
    if used["costMicrousd"] >= policy.monthly_cost_microusd or used["costMicrousd"] + projected_cost_microusd > policy.monthly_cost_microusd:
        if "monthly cost budget" not in violations:
            violations.append("monthly cost budget")
    if used["storageBytes"] + storage_bytes > policy.storage_bytes:
        violations.append("storage quota")
    if violations:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={
            "code": "QUOTA_EXCEEDED", "message": ", ".join(violations), "usage": used
        }, headers={"Retry-After": "3600"})


def estimate_tokens(text: str) -> int:
    # Conservative fallback when an upstream does not return usage. CJK chars are
    # close to one token; Latin text averages roughly four characters per token.
    cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
    return max(1, cjk + math.ceil((len(text) - cjk) / 4))


def model_cost(model: str, input_tokens: int, output_tokens: int) -> int:
    input_price, output_price = MODEL_PRICES.get(model, DEFAULT_PRICE)
    return math.ceil((input_tokens * input_price + output_tokens * output_price) / 1_000_000)


def add_ledger_entry(db: Session, *, key: str, user_id: int, resource_type: str,
                     resource_id: str | None = None, model_id: str | None = None,
                     input_tokens: int = 0, output_tokens: int = 0,
                     storage_bytes: int = 0, quantity: int = 1, cost_microusd: int = 0) -> None:
    if db.scalar(select(UsageLedgerEntry.id).where(UsageLedgerEntry.idempotency_key == key)):
        return
    organization_id = organization_id_for_user(db, user_id)
    db.add(UsageLedgerEntry(idempotency_key=key, user_id=user_id,
        organization_id=organization_id, resource_type=resource_type,
        resource_id=resource_id, model_id=model_id, input_tokens=input_tokens,
        output_tokens=output_tokens, storage_bytes=storage_bytes, quantity=quantity,
        cost_microusd=cost_microusd))
    emit_event(
        db,
        event_name="billing.ledger",
        user_id=user_id,
        organization_id=organization_id,
        model_id=model_id,
        task_id=resource_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        status_code=200,
        metadata={
            "resource_type": resource_type,
            "quantity": quantity,
            "storage_bytes": storage_bytes,
            "cost_microusd": cost_microusd,
        },
    )
