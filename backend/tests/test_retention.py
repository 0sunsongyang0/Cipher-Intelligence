from datetime import timedelta
from app.models import DataRetentionPolicy, Conversation, User, now_utc
from app.retention import run_retention_cleanup
from app.database import SessionLocal

def test_retention_cleanup_removes_expired_chat(client):
    with SessionLocal() as db:
        user = User(username="retention-user", password_hash="x")
        db.add(user); db.flush()
        old = Conversation(owner_session_id=0, owner_user_id=user.id, title="old", updated_at=now_utc()-timedelta(days=10))
        db.add(old); p = db.get(DataRetentionPolicy, 1); p.chat_days = 1; p.upload_days=p.cape_days=p.ioc_days=p.case_days=p.audit_days=p.billing_days=0; db.commit(); old_id=old.id
        counts = run_retention_cleanup(db)
        assert counts["chat"] == 1
        assert db.get(Conversation, old_id) is None

def test_retention_policy_zero_keeps_data(client):
    with SessionLocal() as db:
        p = db.get(DataRetentionPolicy, 1); p.chat_days = 0; db.commit()
        assert run_retention_cleanup(db)["chat"] == 0

def test_retention_admin_endpoint_denies_regular_user(client, create_user):
    create_user(username="regular", password="StrongPass123!")
    client.post("/api/auth/login", json={"username":"regular","password":"StrongPass123!"})
    assert client.get("/api/admin/retention").status_code == 403

def test_account_deletion_removes_profile_and_sessions(client, create_user):
    user = create_user(username="delete-me", password="StrongPass123!")
    client.post("/api/auth/login", json={"username":"delete-me","password":"StrongPass123!"})
    assert client.delete("/api/account").status_code == 204
    assert client.get("/api/account").status_code == 401
    with SessionLocal() as db:
        assert db.get(User, user.id) is None
