import sqlite3
from datetime import timedelta
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.database as database_module
import app.config as config_module
from app.auth import COOKIE_NAME, hash_token
from app.database import SessionLocal
from app.models import InviteCode, Session as SessionModel, now_utc


def login(
    client,
    *,
    username: str = "alice",
    password: str = "StrongPass123!",
    headers: dict[str, str] | None = None,
):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers=headers or {},
    )


def test_register_creates_user_consumes_invite_and_returns_authenticated_session(
    client, create_invite_code
) -> None:
    create_invite_code(code="SMBU@2014520uu-", max_uses=3)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "password": "StrongPass123!",
            "inviteCode": "SMBU@2014520uu-",
        },
    )

    assert response.status_code == 201
    assert response.json()["authenticated"] is True
    assert response.json()["user"]["username"] == "alice"
    assert "campus_session" in response.cookies

    with SessionLocal() as db:
        invite_code = db.execute(
            select(InviteCode).where(InviteCode.code == "SMBU@2014520uu-")
        ).scalar_one()
        assert invite_code.used_count == 1


def test_login_rejects_invalid_invite_or_credentials_paths(client, create_user) -> None:
    invalid_invite = client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "StrongPass123!", "inviteCode": "bad"},
    )
    assert invalid_invite.status_code == 400
    assert invalid_invite.json() == {"detail": "Invite code is invalid"}

    create_user(username="alice", password="StrongPass123!")
    bad_login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "wrong-password"},
    )
    assert bad_login.status_code == 401
    assert bad_login.json() == {"detail": "Invalid username or password"}


def test_login_sets_campus_session_cookie(client, create_user) -> None:
    create_user(username="alice", password="StrongPass123!")

    response = login(client)

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert "campus_session" in response.cookies


def test_database_bootstrap_adds_user_and_invite_schema(monkeypatch) -> None:
    base_dir = Path("backend/.pytest-tmp")
    base_dir.mkdir(exist_ok=True)
    temp_dir = Path(mkdtemp(dir=base_dir))
    legacy_db_path = temp_dir / "legacy-account.db"
    migration_engine = None

    try:
        with sqlite3.connect(legacy_db_path) as connection:
            connection.execute(
                """
                CREATE TABLE sessions (
                    id INTEGER PRIMARY KEY,
                    token_hash VARCHAR(64) NOT NULL,
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE conversations (
                    id INTEGER PRIMARY KEY,
                    owner_session_id INTEGER NOT NULL DEFAULT 0,
                    title VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
            connection.commit()

        migration_engine = create_engine(
            f"sqlite:///{legacy_db_path}",
            connect_args={"check_same_thread": False},
        )
        migration_session_local = sessionmaker(
            bind=migration_engine,
            autocommit=False,
            autoflush=False,
        )

        monkeypatch.setattr(database_module, "engine", migration_engine)
        monkeypatch.setattr(database_module, "SessionLocal", migration_session_local)

        database_module.init_db()

        with sqlite3.connect(legacy_db_path) as connection:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            assert "users" in table_names
            assert "invite_codes" in table_names

            session_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
            }
            assert "user_id" in session_columns

            conversation_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
            }
            assert "owner_user_id" in conversation_columns

            session_indexes = {
                row[1] for row in connection.execute("PRAGMA index_list(sessions)").fetchall()
            }
            assert database_module.SESSION_USER_INDEX_NAME in session_indexes

            conversation_indexes = {
                row[1]
                for row in connection.execute("PRAGMA index_list(conversations)").fetchall()
            }
            assert database_module.CONVERSATION_OWNER_USER_INDEX_NAME in conversation_indexes
    finally:
        if migration_engine is not None:
            migration_engine.dispose()
        rmtree(temp_dir, ignore_errors=True)



def test_login_sets_expected_cookie_attributes_for_test_env(client, create_user) -> None:
    create_user(username="alice", password="StrongPass123!")
    response = login(client)

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"]
    assert "campus_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" not in set_cookie


@pytest.mark.parametrize(
    ("app_env", "session_cookie_secure"),
    [("production", None), ("test", True)],
)
def test_login_sets_secure_cookie_when_enabled(
    client, monkeypatch, create_user, app_env: str, session_cookie_secure: bool | None
) -> None:
    monkeypatch.setattr(config_module.settings, "app_env", app_env)
    monkeypatch.setattr(config_module.settings, "session_cookie_secure", session_cookie_secure)
    create_user(username="alice", password="StrongPass123!")

    response = login(client)

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]



def test_unauthenticated_chat_page_redirects_to_public_gate(client) -> None:
    response = client.get("/chat", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/"



def test_session_status_returns_current_user_payload(client, create_user) -> None:
    user = create_user(username="alice", password="StrongPass123!")
    login_response = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "StrongPass123!"},
    )
    assert login_response.status_code == 200

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "user": {"id": user.id, "username": "alice", "isAdmin": False},
    }


def test_logout_returns_unauthenticated_session_payload(client, create_user) -> None:
    create_user(username="alice", password="StrongPass123!")
    login_response = login(client)
    assert login_response.status_code == 200

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json() == {"authenticated": False, "user": None}

    session_response = client.get("/api/auth/session")
    assert session_response.status_code == 200
    assert session_response.json() == {"authenticated": False, "user": None}


def test_logout_revokes_access_to_authenticated_frontend_routes(client, create_user) -> None:
    create_user(username="alice", password="StrongPass123!")
    login_response = login(client)
    assert login_response.status_code == 200
    assert client.get("/chat").status_code == 200

    logout_response = client.post("/api/auth/logout")

    assert logout_response.status_code == 200

    response = client.get("/chat", follow_redirects=False)
    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/"



def test_logout_removes_server_side_session(client, create_user) -> None:
    create_user(username="alice", password="StrongPass123!")
    login_response = login(client)
    token = login_response.cookies[COOKIE_NAME]

    with SessionLocal() as db:
        session = db.execute(
            select(SessionModel).where(SessionModel.token_hash == hash_token(token))
        ).scalar_one_or_none()
        assert session is not None

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200

    with SessionLocal() as db:
        session = db.execute(
            select(SessionModel).where(SessionModel.token_hash == hash_token(token))
        ).scalar_one_or_none()
        assert session is None

    client.cookies.set(COOKIE_NAME, token)
    reused_cookie_response = client.get("/api/auth/session")
    assert reused_cookie_response.status_code == 200
    assert reused_cookie_response.json() == {"authenticated": False, "user": None}



def test_expired_session_is_rejected(client) -> None:
    expired_token = "expired-session-token"

    with SessionLocal() as db:
        db.add(
            SessionModel(
                token_hash=hash_token(expired_token),
                expires_at=now_utc() - timedelta(seconds=1),
            )
        )
        db.commit()

    client.cookies.set(COOKIE_NAME, expired_token)
    response = client.get("/chat", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/"

    with SessionLocal() as db:
        session = db.execute(
            select(SessionModel).where(SessionModel.token_hash == hash_token(expired_token))
        ).scalar_one_or_none()
        assert session is None



def test_login_returns_429_after_five_failed_attempts_for_same_client_host(client, create_user) -> None:
    create_user(username="alice", password="StrongPass123!")
    for attempt in range(5):
        response = login(
            client,
            password="wrong-password",
            headers={"X-Forwarded-For": f"spoofed-{attempt}"},
        )
        assert response.status_code == 401

    blocked_response = login(
        client,
        password="wrong-password",
        headers={"X-Forwarded-For": "fresh-spoof"},
    )

    assert blocked_response.status_code == 429



def test_production_settings_reject_default_auth_secrets() -> None:
    with pytest.raises(ValueError, match="default auth secrets"):
        config_module.Settings(
            app_env="production",
            app_access_password="change-me",
            session_secret="change-me-too",
        )



def test_omitted_app_env_rejects_default_auth_secrets(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(ValueError, match="default auth secrets"):
        config_module.Settings(
            _env_file=None,
            app_access_password="change-me",
            session_secret="change-me-too",
        )
