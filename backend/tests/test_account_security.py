import base64
import hmac
import hashlib
import struct
import time

from sqlalchemy import select

from app.account_security import reveal_secret
from app.database import SessionLocal
from app.models import AccountRecoveryCode, Session, User


def login(client, username="alice", password="StrongPass123!"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_password_change_requires_reauthentication_and_revokes_other_sessions(client, create_user):
    create_user(username="alice", password="StrongPass123!")
    assert login(client).status_code == 200
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "alice"))
        db.add(Session(user_id=user.id, token_hash="0" * 64, expires_at=user.created_at.replace(year=user.created_at.year + 1)))
        db.commit()

    denied = client.put("/api/account/security/password", json={"password": "wrong", "newPassword": "NewStrong456!"})
    changed = client.put("/api/account/security/password", json={"password": "StrongPass123!", "newPassword": "NewStrong456!"})

    assert denied.status_code == 401
    assert changed.status_code == 200
    assert login(client, password="StrongPass123!").status_code == 401
    assert login(client, password="NewStrong456!").status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.username == "alice")).password_hash != "NewStrong456!"


def test_recovery_codes_are_returned_once_and_only_hashes_are_stored(client, create_user):
    create_user(username="alice", password="StrongPass123!")
    assert login(client).status_code == 200
    generated = client.post("/api/account/security/recovery-codes", json={"password": "StrongPass123!"})
    assert generated.status_code == 200
    codes = generated.json()["codes"]
    assert len(codes) == 10
    overview = client.get("/api/account/security").json()
    assert "codes" not in overview
    with SessionLocal() as db:
        hashes = db.scalars(select(AccountRecoveryCode.code_hash)).all()
        assert len(hashes) == 10
        assert not any(code in hashes for code in codes)


def test_totp_confirmation_encrypts_secret_and_rotates_recovery_codes(client, create_user):
    create_user(username="alice", password="StrongPass123!")
    assert login(client).status_code == 200
    setup = client.post("/api/account/security/totp/setup", json={"password": "StrongPass123!"})
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int(time.time()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    code = f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff) % 1_000_000:06d}"
    confirmed = client.post("/api/account/security/totp/confirm", json={"password": "StrongPass123!", "secret": secret, "confirmationCode": code})
    assert confirmed.status_code == 200
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "alice"))
        assert user.totp_secret != secret
        assert reveal_secret(user.totp_secret) == secret
    client.post("/api/auth/logout")
    assert login(client).status_code == 401
    assert client.post("/api/auth/login", json={"username": "alice", "password": "StrongPass123!", "passcode": code}).status_code == 200


def test_recovery_code_can_be_consumed_only_once(client, create_user):
    create_user(username="alice", password="StrongPass123!")
    assert login(client).status_code == 200
    setup = client.post("/api/account/security/totp/setup", json={"password": "StrongPass123!"}).json()
    secret = setup["secret"]
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    code = f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff) % 1_000_000:06d}"
    recovery = client.post("/api/account/security/totp/confirm", json={"password": "StrongPass123!", "secret": secret, "confirmationCode": code}).json()["codes"][0]
    client.post("/api/auth/logout")
    payload = {"username": "alice", "password": "StrongPass123!", "recoveryCode": recovery}
    assert client.post("/api/auth/login", json=payload).status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json=payload).status_code == 401


def test_sessions_history_and_force_logout_do_not_expose_tokens(client, create_user):
    create_user(username="alice", password="StrongPass123!")
    assert login(client).status_code == 200
    sessions = client.get("/api/account/security/sessions")
    history = client.get("/api/account/security/login-history")
    assert sessions.status_code == history.status_code == 200
    assert "token" not in sessions.text.lower()
    assert history.json()[0]["method"] == "local_password"
    assert client.post("/api/account/security/sessions/revoke-all", json={"password": "StrongPass123!"}).status_code == 200
