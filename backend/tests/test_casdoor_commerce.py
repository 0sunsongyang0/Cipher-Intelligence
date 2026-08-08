from datetime import datetime, timedelta, timezone

import pytest

from app.auth import hash_password
from app.casdoor_commerce import CommerceSyncResult, resolve_plan_tier, sync_user_commerce
from app.config import settings
from app.database import SessionLocal
from app.models import CommerceSubscription, UsageCreditGrant, User, now_utc
from app.usage_governance import PLANS, policy_for_user


def iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def login(client, username: str, password: str = "Password123"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_commerce_overview_route_returns_subscription_history(client, monkeypatch):
    monkeypatch.setattr(settings, "casdoor_commerce_enabled", True)
    with SessionLocal() as db:
        user = User(
            username="route-buyer",
            casdoor_subject="cipher/route-buyer",
            casdoor_name="route-buyer",
            password_hash=hash_password("Password123"),
            subscription_tier="pro",
        )
        db.add(user)
        db.flush()
        db.add(CommerceSubscription(
            user_id=user.id,
            provider="casdoor",
            external_id="cipher/sub_route",
            plan_name="cipher-pro-monthly",
            plan_display_name="Cipher Pro",
            tier="pro",
            state="Active",
            period="Monthly",
        ))
        db.add(UsageCreditGrant(
            user_id=user.id,
            provider="casdoor",
            external_key="cipher/pay_route:cape-pack:0",
            product_name="cape-pack",
            cape_submission_credit=10,
        ))
        db.commit()

    assert login(client, "route-buyer").status_code == 200
    response = client.get("/api/commerce/subscription")

    assert response.status_code == 200
    assert response.json()["tier"] == "pro"
    assert response.json()["subscriptions"][0]["plan"] == "cipher-pro-monthly"
    assert response.json()["creditGrants"][0]["capeSubmissions"] == 10


def test_user_commerce_sync_route_commits_result(client, monkeypatch):
    monkeypatch.setattr(settings, "casdoor_commerce_enabled", True)
    with SessionLocal() as db:
        user = User(
            username="sync-route-buyer",
            casdoor_subject="cipher/sync-route-buyer",
            casdoor_name="sync-route-buyer",
            password_hash=hash_password("Password123"),
            subscription_tier="free",
        )
        db.add(user)
        db.commit()

    async def fake_sync(_db, user):
        user.subscription_tier = "enterprise"
        return CommerceSyncResult("enterprise", 1, 1, now_utc())

    monkeypatch.setattr("app.routes.commerce.sync_user_commerce", fake_sync)
    assert login(client, "sync-route-buyer").status_code == 200
    response = client.post("/api/commerce/subscription/sync")

    assert response.status_code == 200
    assert response.json()["tier"] == "enterprise"
    with SessionLocal() as db:
        assert db.query(User).filter_by(username="sync-route-buyer").one().subscription_tier == "enterprise"


def test_resolve_plan_tier_supports_billing_period_suffix(monkeypatch):
    monkeypatch.setattr(settings, "casdoor_plan_tier_mapping", "")
    assert resolve_plan_tier("cipher-pro-monthly") == "pro"
    assert resolve_plan_tier("cipher-enterprise-yearly") == "enterprise"
    assert resolve_plan_tier("unmapped") is None


@pytest.mark.anyio
async def test_sync_user_commerce_uses_highest_active_subscription(client, monkeypatch):
    del client
    monkeypatch.setattr(settings, "casdoor_commerce_enabled", True)
    monkeypatch.setattr(settings, "casdoor_plan_tier_mapping", "")

    async def fake_rows(_username):
        return ([
            {"owner": "cipher", "name": "sub_standard", "user": "buyer",
             "plan": "cipher-standard-monthly", "state": "Active",
             "startTime": iso(timedelta(days=-1)), "endTime": iso(timedelta(days=29)), "period": "Monthly"},
            {"owner": "cipher", "name": "sub_pro", "user": "buyer",
             "plan": "cipher-pro-yearly", "state": "Active",
             "startTime": iso(timedelta(days=-1)), "endTime": iso(timedelta(days=364)), "period": "Yearly"},
            {"owner": "cipher", "name": "sub_old", "user": "buyer",
             "plan": "cipher-enterprise", "state": "Expired",
             "startTime": iso(timedelta(days=-40)), "endTime": iso(timedelta(days=-10))},
        ], [
            {"name": "cipher-standard-monthly", "displayName": "Standard Monthly"},
            {"name": "cipher-pro-yearly", "displayName": "Pro Yearly"},
            {"name": "cipher-enterprise", "displayName": "Enterprise"},
        ])

    monkeypatch.setattr("app.casdoor_commerce._fetch_commerce_rows", fake_rows)
    async def no_addons(_username): return [], []
    monkeypatch.setattr("app.casdoor_commerce._fetch_addon_rows", no_addons)
    with SessionLocal() as db:
        user = User(username="commerce-buyer", casdoor_subject="subject", casdoor_name="buyer",
                    password_hash=hash_password("Password123"), subscription_tier="free")
        db.add(user); db.commit(); db.refresh(user)
        result = await sync_user_commerce(db, user)
        db.commit()
        assert result.tier == "pro"
        assert result.active_subscription_count == 2
        assert user.subscription_tier == "pro"
        assert db.query(CommerceSubscription).filter_by(user_id=user.id).count() == 3


@pytest.mark.anyio
async def test_sync_marks_removed_subscription_inactive(client, monkeypatch):
    del client
    monkeypatch.setattr(settings, "casdoor_commerce_enabled", True)

    async def no_rows(_username):
        return [], []

    monkeypatch.setattr("app.casdoor_commerce._fetch_commerce_rows", no_rows)
    monkeypatch.setattr("app.casdoor_commerce._fetch_addon_rows", no_rows)
    with SessionLocal() as db:
        user = User(username="former-buyer", casdoor_subject="subject-2", casdoor_name="former",
                    password_hash=hash_password("Password123"), subscription_tier="pro")
        db.add(user); db.flush()
        db.add(CommerceSubscription(user_id=user.id, provider="casdoor", external_id="cipher/sub_old",
            plan_name="cipher-pro", tier="pro", state="Active"))
        db.commit()
        result = await sync_user_commerce(db, user)
        db.commit()
        assert result.tier == "free"
        assert user.subscription_tier == "free"
        assert db.query(CommerceSubscription).filter_by(user_id=user.id).one().state == "Removed"


@pytest.mark.anyio
async def test_paid_product_properties_grant_addon_quota(client, monkeypatch):
    del client
    monkeypatch.setattr(settings, "casdoor_commerce_enabled", True)
    async def no_subscriptions(_username): return [], []
    async def addon_rows(_username):
        return ([{"owner": "cipher", "name": "pay_1", "user": "addon-buyer", "state": "Paid",
                  "createdTime": iso(timedelta()), "orderObj": {"productInfos": [
                      {"name": "cape-pack", "quantity": 2}]}}],
                [{"name": "cape-pack", "properties": {
                    "cipher.tokens": "1000", "cipher.capeSubmissions": "5",
                    "cipher.storageBytes": "2048", "cipher.expiresDays": "30"}}])
    monkeypatch.setattr("app.casdoor_commerce._fetch_commerce_rows", no_subscriptions)
    monkeypatch.setattr("app.casdoor_commerce._fetch_addon_rows", addon_rows)
    with SessionLocal() as db:
        user = User(username="addon-buyer", casdoor_subject="subject-3", casdoor_name="addon-buyer",
                    password_hash=hash_password("Password123"), subscription_tier="free")
        db.add(user); db.commit(); db.refresh(user)
        await sync_user_commerce(db, user); db.commit()
        grant = db.query(UsageCreditGrant).filter_by(user_id=user.id).one()
        assert grant.token_credit == 2_000
        assert grant.cape_submission_credit == 10
        policy = policy_for_user(db, user.id)
        assert policy.monthly_tokens == PLANS["free"].monthly_tokens + 2_000
        assert policy.monthly_cape_submissions == PLANS["free"].monthly_cape_submissions + 10
