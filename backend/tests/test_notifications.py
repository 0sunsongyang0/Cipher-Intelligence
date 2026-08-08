from app.database import SessionLocal
from app.models import Notification, OrganizationMember
from app.notifications import NotificationEvent, notify


def login(client, username: str, password: str = "StrongPass123!") -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def create_organization(client, name: str, slug: str) -> int:
    response = client.post("/api/organizations", json={"name": name, "slug": slug})
    assert response.status_code == 201
    return response.json()["id"]


def test_notification_center_lifecycle_filter_and_preferences(client, create_user) -> None:
    user = create_user(username="notify-user", password="StrongPass123!")
    login(client, user.username)
    organization_id = create_organization(client, "Notify Org", "notify-org")
    with SessionLocal() as db:
        event = NotificationEvent(
            organization_id=organization_id, user_id=user.id, notification_type="mention",
            title="你在 Case 中被提及", idempotency_key="mention:case-7:comment-4",
            case_id=7, resource_type="case", resource_id="7", resource_url="/cases?case=7",
        )
        assert notify(db, event) is True
        assert notify(db, event) is True
        db.commit()
        assert db.query(Notification).filter_by(idempotency_key=event.idempotency_key).count() == 1

    listed = client.get("/api/notifications?type=mention")
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert listed.json()["unreadCount"] == 1
    assert item["organizationId"] == organization_id
    assert item["resourceUrl"] == "/cases?case=7"

    preferences = client.get(f"/api/notifications/preferences?organization_id={organization_id}")
    assert preferences.status_code == 200
    assert any(value["type"] == "quota_low" and value["inApp"] for value in preferences.json()["items"])
    updated = client.put(
        f"/api/notifications/preferences/quota_low?organization_id={organization_id}",
        json={"inApp": False, "email": True, "webPush": True},
    )
    assert updated.json() == {"type": "quota_low", "inApp": False, "email": True, "webPush": True}

    assert client.put("/api/notifications/read-all").json() == {"updated": 1}
    assert client.get("/api/notifications").json()["unreadCount"] == 0
    assert client.delete(f"/api/notifications/{item['id']}").status_code == 204
    assert client.get("/api/notifications").json()["items"] == []


def test_notifications_never_cross_organization_membership(client, create_user) -> None:
    owner = create_user(username="notify-owner", password="StrongPass123!")
    outsider = create_user(username="notify-outsider", password="StrongPass123!")
    login(client, owner.username)
    organization_id = create_organization(client, "Secret Org", "secret-notify-org")
    with SessionLocal() as db:
        assert notify(db, NotificationEvent(
            organization_id=organization_id, user_id=outsider.id, notification_type="threat_intel_updated",
            title="外部情报已更新", idempotency_key="intel:feed:42",
        )) is False
        db.commit()
        assert db.query(Notification).filter_by(user_id=outsider.id, organization_id=organization_id).count() == 0

    client.post("/api/auth/logout")
    login(client, outsider.username)
    assert client.get(f"/api/notifications?organization_id={organization_id}").status_code == 403

    with SessionLocal() as db:
        assert db.query(OrganizationMember).filter_by(organization_id=organization_id, user_id=outsider.id).count() == 0
