from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.casdoor_auth import CasdoorAuthError, _casdoor_api_access_token
from app.config import settings
from app.models import CommerceSubscription, UsageCreditGrant, User, now_utc
from app.usage_governance import organization_id_for_user


TIER_PRIORITY = {"free": 0, "standard": 1, "pro": 2, "enterprise": 3}
ACTIVE_STATES = {"active"}


@dataclass(frozen=True)
class CommerceSyncResult:
    tier: str
    active_subscription_count: int
    total_subscription_count: int
    synced_at: datetime


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _api_list(response: httpx.Response, resource: str) -> list[dict[str, Any]]:
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise CasdoorAuthError(f"Casdoor {resource} request failed") from error
    data = payload.get("data") if isinstance(payload, dict) and payload.get("status") == "ok" else None
    if not isinstance(data, list):
        raise CasdoorAuthError(f"Casdoor returned invalid {resource} data")
    return [item for item in data if isinstance(item, dict)]


async def _fetch_commerce_rows(username: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not settings.casdoor_auth_enabled:
        raise CasdoorAuthError("Casdoor commerce sync is not enabled")
    owner = settings.casdoor_organization_name.strip()
    endpoint = (settings.casdoor_internal_endpoint.strip() or settings.casdoor_endpoint).rstrip("/")
    async with httpx.AsyncClient(timeout=settings.casdoor_timeout_seconds) as client:
        token = await _casdoor_api_access_token(client)
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        subscriptions_response, plans_response = await asyncio.gather(
            client.get(f"{endpoint}/api/get-subscriptions", params={"owner": owner, "field": "user", "value": username}, headers=headers),
            client.get(f"{endpoint}/api/get-plans", params={"owner": owner}, headers=headers),
        )
    return _api_list(subscriptions_response, "subscription"), _api_list(plans_response, "plan")


async def _fetch_addon_rows(username: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    owner = settings.casdoor_organization_name.strip()
    endpoint = (settings.casdoor_internal_endpoint.strip() or settings.casdoor_endpoint).rstrip("/")
    async with httpx.AsyncClient(timeout=settings.casdoor_timeout_seconds) as client:
        token = await _casdoor_api_access_token(client)
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        payments_response, products_response = await asyncio.gather(
            client.get(f"{endpoint}/api/get-payments", params={"owner": owner, "field": "user", "value": username}, headers=headers),
            client.get(f"{endpoint}/api/get-products", params={"owner": owner}, headers=headers),
        )
    return _api_list(payments_response, "payment"), _api_list(products_response, "product")


def resolve_plan_tier(plan_name: str, plan: dict[str, Any] | None = None) -> str | None:
    mapping = settings.casdoor_subscription_tier_mapping
    candidates = [plan_name]
    if plan:
        candidates.extend(str(plan.get(key) or "") for key in ("displayName", "product", "role"))
    expanded: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip().casefold()
        if not normalized:
            continue
        expanded.append(normalized)
        for suffix in ("-monthly", "-yearly", "_monthly", "_yearly"):
            if normalized.endswith(suffix):
                expanded.append(normalized[: -len(suffix)])
    for candidate in expanded:
        if candidate in mapping:
            return mapping[candidate]
    return None


def _is_active(row: dict[str, Any], now: datetime) -> bool:
    if str(row.get("state") or "").strip().casefold() not in ACTIVE_STATES:
        return False
    starts_at, ends_at = _parse_datetime(row.get("startTime")), _parse_datetime(row.get("endTime"))
    return (starts_at is None or starts_at <= now) and (ends_at is None or ends_at > now)


async def sync_user_commerce(db: Session, user: User) -> CommerceSyncResult:
    """Synchronize Casdoor subscription truth without deleting billing history."""
    if not settings.casdoor_commerce_enabled or not user.casdoor_name:
        return CommerceSyncResult(user.subscription_tier, 0, 0, now_utc())

    subscriptions, plans = await _fetch_commerce_rows(user.casdoor_name)
    payments, products = await _fetch_addon_rows(user.casdoor_name)
    plans_by_name = {str(item.get("name") or ""): item for item in plans}
    synced_at = now_utc()
    seen: set[str] = set()
    active_tiers: list[str] = []

    for row in subscriptions:
        owner = str(row.get("owner") or settings.casdoor_organization_name)
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        external_id = f"{owner}/{name}"
        seen.add(external_id)
        plan_name = str(row.get("plan") or "").strip()
        plan = plans_by_name.get(plan_name)
        tier = resolve_plan_tier(plan_name, plan) or "free"
        if _is_active(row, synced_at):
            active_tiers.append(tier)

        snapshot = db.execute(select(CommerceSubscription).where(
            CommerceSubscription.provider == "casdoor", CommerceSubscription.external_id == external_id
        )).scalar_one_or_none()
        if snapshot is None:
            snapshot = CommerceSubscription(user_id=user.id, provider="casdoor", external_id=external_id,
                plan_name=plan_name or "unknown", tier=tier, state=str(row.get("state") or "Unknown"))
            db.add(snapshot)
        snapshot.user_id = user.id
        snapshot.organization_id = organization_id_for_user(db, user.id)
        snapshot.plan_name = plan_name or "unknown"
        snapshot.plan_display_name = str((plan or {}).get("displayName") or "")[:160] or None
        snapshot.tier = tier
        snapshot.pricing_name = str(row.get("pricing") or "")[:120] or None
        snapshot.payment_name = str(row.get("payment") or "")[:120] or None
        snapshot.period = str(row.get("period") or "")[:32] or None
        snapshot.state = str(row.get("state") or "Unknown")[:32]
        snapshot.starts_at = _parse_datetime(row.get("startTime"))
        snapshot.ends_at = _parse_datetime(row.get("endTime"))
        snapshot.raw_json = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        snapshot.last_synced_at = synced_at

    existing = db.execute(select(CommerceSubscription).where(
        CommerceSubscription.user_id == user.id, CommerceSubscription.provider == "casdoor"
    )).scalars().all()
    for snapshot in existing:
        if snapshot.external_id not in seen and snapshot.state.casefold() in ACTIVE_STATES:
            snapshot.state = "Removed"
            snapshot.last_synced_at = synced_at

    _sync_credit_grants(db, user, payments, products, synced_at)

    effective_tier = max(active_tiers, key=lambda item: TIER_PRIORITY.get(item, -1), default="free")
    user.subscription_tier = effective_tier
    db.add(user)
    db.flush()
    return CommerceSyncResult(effective_tier, len(active_tiers), len(subscriptions), synced_at)


def _property_int(properties: dict[str, Any], name: str) -> int:
    value = properties.get(name)
    try:
        return max(0, int(str(value).strip())) if value not in (None, "") else 0
    except ValueError:
        return 0


def _sync_credit_grants(db: Session, user: User, payments: list[dict[str, Any]],
                        products: list[dict[str, Any]], synced_at: datetime) -> None:
    products_by_name = {str(item.get("name") or ""): item for item in products}
    seen_paid: set[str] = set()
    organization_id = organization_id_for_user(db, user.id)
    for payment in payments:
        if str(payment.get("state") or "").strip().casefold() != "paid":
            continue
        payment_name = str(payment.get("name") or "").strip()
        owner = str(payment.get("owner") or settings.casdoor_organization_name)
        order = payment.get("orderObj")
        product_infos = order.get("productInfos") if isinstance(order, dict) else None
        if not isinstance(product_infos, list):
            product_infos = [{"name": name, "quantity": 1} for name in payment.get("products", []) if isinstance(name, str)]
        for index, info in enumerate(product_infos):
            if not isinstance(info, dict):
                continue
            product_name = str(info.get("name") or "").strip()
            product = products_by_name.get(product_name)
            properties = product.get("properties") if isinstance(product, dict) else None
            if not product_name or not isinstance(properties, dict):
                continue
            quantity = max(1, _property_int(info, "quantity"))
            token_credit = _property_int(properties, "cipher.tokens") * quantity
            cost_credit = _property_int(properties, "cipher.costMicrousd") * quantity
            cape_credit = _property_int(properties, "cipher.capeSubmissions") * quantity
            storage_credit = _property_int(properties, "cipher.storageBytes") * quantity
            if not any((token_credit, cost_credit, cape_credit, storage_credit)):
                continue
            external_key = f"{owner}/{payment_name}:{product_name}:{index}"
            seen_paid.add(external_key)
            grant = db.execute(select(UsageCreditGrant).where(
                UsageCreditGrant.provider == "casdoor", UsageCreditGrant.external_key == external_key
            )).scalar_one_or_none()
            if grant is None:
                grant = UsageCreditGrant(user_id=user.id, provider="casdoor", external_key=external_key,
                    product_name=product_name)
                db.add(grant)
            grant.user_id = user.id
            grant.organization_id = organization_id
            grant.token_credit = token_credit
            grant.cost_credit_microusd = cost_credit
            grant.cape_submission_credit = cape_credit
            grant.storage_credit_bytes = storage_credit
            expires_days = _property_int(properties, "cipher.expiresDays")
            created_at = _parse_datetime(payment.get("createdTime")) or synced_at
            grant.expires_at = created_at + timedelta(days=expires_days) if expires_days else None
            grant.revoked_at = None
            grant.metadata_json = json.dumps({"payment": payment_name, "quantity": quantity}, separators=(",", ":"))

    existing_grants = db.execute(select(UsageCreditGrant).where(
        UsageCreditGrant.user_id == user.id, UsageCreditGrant.provider == "casdoor"
    )).scalars().all()
    for grant in existing_grants:
        if grant.external_key not in seen_paid and grant.revoked_at is None:
            grant.revoked_at = synced_at
