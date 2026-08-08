import sqlite3
from datetime import timedelta
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.database as database_module
import app.config as config_module
from app.auth import COOKIE_NAME, hash_token
from app.database import SessionLocal
from app.models import InviteCode, Session as SessionModel, User, now_utc


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


def test_register_rejects_duplicate_username(client, create_user, create_invite_code) -> None:
    create_user(username="alice", password="StrongPass123!")
    create_invite_code(code="SMBU@2014520uu-", max_uses=3)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "password": "StrongPass123!",
            "inviteCode": "SMBU@2014520uu-",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Username is already taken"}


def test_register_rejects_weak_password(client, create_invite_code) -> None:
    create_invite_code(code="SMBU@2014520uu-", max_uses=3)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "password": "short",
            "inviteCode": "SMBU@2014520uu-",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Password must be at least 8 characters and include letters and numbers"
    }


def test_login_rejects_nonexistent_user(client) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": "missing-user", "password": "StrongPass123!"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}


def test_login_rejects_disabled_user(client, create_user) -> None:
    create_user(username="alice", password="StrongPass123!", is_active=False)

    response = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "StrongPass123!"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}


def test_legacy_password_only_login_still_succeeds(client) -> None:
    response = client.post(
        "/api/auth/login",
        json={"password": config_module.settings.app_access_password},
    )

    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "user": None}
    assert "campus_session" in response.cookies


def test_register_rolls_back_user_and_invite_if_session_creation_fails(
    client, create_invite_code, monkeypatch
) -> None:
    create_invite_code(code="SMBU@2014520uu-", max_uses=3)

    def fail_create_session(db, user=None, commit=True):
        raise RuntimeError("session write failed")

    monkeypatch.setattr("app.routes.auth.create_session", fail_create_session)

    with pytest.raises(RuntimeError, match="session write failed"):
        client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "StrongPass123!",
                "inviteCode": "SMBU@2014520uu-",
            },
        )

    with SessionLocal() as db:
        invite_code = db.execute(
            select(InviteCode).where(InviteCode.code == "SMBU@2014520uu-")
        ).scalar_one()
        assert invite_code.used_count == 0
        assert db.execute(select(User).where(User.username == "alice")).scalar_one_or_none() is None


def test_register_translates_duplicate_username_integrity_error_to_clean_400(
    client, create_user, create_invite_code, monkeypatch
) -> None:
    create_user(username="alice", password="StrongPass123!")
    create_invite_code(code="SMBU@2014520uu-", max_uses=3)
    monkeypatch.setattr("app.routes.auth.validate_registration_username", lambda db, username: None)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "password": "StrongPass123!",
            "inviteCode": "SMBU@2014520uu-",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Username is already taken"}


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

            user_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            assert "display_name" in user_columns
            assert "avatar_filename" in user_columns
            assert "casdoor_subject" in user_columns

            user_indexes = {
                row[1] for row in connection.execute("PRAGMA index_list(users)").fetchall()
            }
            assert database_module.USER_USERNAME_NORMALIZED_INDEX_NAME in user_indexes
            assert database_module.USER_CASDOOR_SUBJECT_INDEX_NAME in user_indexes

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
        "user": {
            "id": user.id,
            "username": "alice",
            "displayName": "alice",
            "avatarUrl": None,
            "isAdmin": False,
        },
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


def configure_casdoor(monkeypatch, *, admin_users: str = "") -> None:
    values = {
        "casdoor_enabled": True,
        "casdoor_endpoint": "https://login.example.test",
        "casdoor_client_id": "cipher-client",
        "casdoor_client_secret": "cipher-secret",
        "casdoor_organization_name": "cipher",
        "casdoor_application_name": "cipher-ai",
        "casdoor_display_name": "Cipher SSO",
        "casdoor_admin_users": admin_users,
        "casdoor_admin_roles": "",
        "session_cookie_secure": False,
    }
    for name, value in values.items():
        monkeypatch.setattr(config_module.settings, name, value)


def test_casdoor_config_is_public_and_disabled_by_default(client, monkeypatch) -> None:
    monkeypatch.setattr(config_module.settings, "casdoor_enabled", False)

    response = client.get("/api/auth/casdoor/config")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "provider": "casdoor",
        "displayName": config_module.settings.casdoor_display_name,
        "managementUrl": "",
    }


def test_casdoor_login_redirect_uses_authorization_code_flow(client, monkeypatch) -> None:
    configure_casdoor(monkeypatch)

    response = client.get(
        "/api/auth/casdoor/login?return_to=%2Fchat",
        follow_redirects=False,
    )

    assert response.status_code == 302
    authorization_url = urlsplit(response.headers["location"])
    query = parse_qs(authorization_url.query)
    assert authorization_url.scheme == "https"
    assert authorization_url.netloc == "login.example.test"
    assert authorization_url.path == "/login/oauth/authorize"
    assert query["client_id"] == ["cipher-client"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid profile email"]
    assert query["language"] == ["zh"]
    assert "theme" not in query
    assert query["redirect_uri"] == ["http://testserver/api/auth/casdoor/callback"]
    assert query["state"][0]
    assert any(
        name.startswith("cipher_casdoor_oauth_") for name in response.cookies.keys()
    )


def test_casdoor_login_forwards_supported_theme(client, monkeypatch) -> None:
    configure_casdoor(monkeypatch)

    response = client.get(
        "/api/auth/casdoor/login?return_to=%2Fchat&theme=dark",
        follow_redirects=False,
    )

    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["theme"] == ["dark"]


def test_casdoor_login_maps_light_theme_to_casdoor_default(client, monkeypatch) -> None:
    configure_casdoor(monkeypatch)

    response = client.get(
        "/api/auth/casdoor/login?return_to=%2Fchat&theme=light",
        follow_redirects=False,
    )

    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["theme"] == ["default"]


def test_casdoor_login_ignores_unsupported_theme(client, monkeypatch) -> None:
    configure_casdoor(monkeypatch)

    response = client.get(
        "/api/auth/casdoor/login?return_to=%2Fchat&theme=neon",
        follow_redirects=False,
    )

    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert "theme" not in query


def test_parallel_casdoor_login_flows_keep_independent_state_cookies(
    client, monkeypatch
) -> None:
    configure_casdoor(monkeypatch)

    async def fake_exchange(**_kwargs):
        return {
            "sub": "cipher/parallel-user-id",
            "preferred_username": "parallel-user",
        }

    monkeypatch.setattr("app.routes.auth.exchange_code_for_userinfo", fake_exchange)
    light_response = client.get(
        "/api/auth/casdoor/login?return_to=%2Fauth%2Fcasdoor%2Fembedded&theme=light",
        follow_redirects=False,
    )
    dark_response = client.get(
        "/api/auth/casdoor/login?return_to=%2Fauth%2Fcasdoor%2Fembedded&theme=dark",
        follow_redirects=False,
    )
    light_state = parse_qs(urlsplit(light_response.headers["location"]).query)["state"][0]
    dark_state = parse_qs(urlsplit(dark_response.headers["location"]).query)["state"][0]

    assert light_state != dark_state
    assert f"cipher_casdoor_oauth_{light_state}" in client.cookies
    assert f"cipher_casdoor_oauth_{dark_state}" in client.cookies

    callback_response = client.get(
        f"/api/auth/casdoor/callback?code=parallel-code&state={light_state}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 200
    assert '"status":"success"' in callback_response.text


def test_local_login_and_registration_are_disabled_when_casdoor_is_enabled(
    client, monkeypatch
) -> None:
    configure_casdoor(monkeypatch)

    login_response = client.post(
        "/api/auth/login",
        json={"username": "local-user", "password": "local-password"},
    )
    register_response = client.post(
        "/api/auth/register",
        json={
            "username": "local-user",
            "password": "StrongPass123!",
            "inviteCode": "unused",
        },
    )

    assert login_response.status_code == 404
    assert register_response.status_code == 404
    assert login_response.json() == {"detail": "Local authentication is disabled"}
    assert register_response.json() == {"detail": "Local authentication is disabled"}


def test_casdoor_callback_provisions_user_and_issues_cipher_session(
    client, monkeypatch
) -> None:
    configure_casdoor(monkeypatch)

    async def fake_exchange(*, code: str, redirect_uri: str):
        assert code == "authorization-code"
        assert redirect_uri == "http://testserver/api/auth/casdoor/callback"
        return {
            "sub": "cipher/alice-id",
            "preferred_username": "alice",
            "name": "Alice Analyst",
            "email": "alice@example.test",
        }

    monkeypatch.setattr("app.routes.auth.exchange_code_for_userinfo", fake_exchange)
    login_response = client.get("/api/auth/casdoor/login", follow_redirects=False)
    state = parse_qs(urlsplit(login_response.headers["location"]).query)["state"][0]

    callback_response = client.get(
        f"/api/auth/casdoor/callback?code=authorization-code&state={state}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 302
    assert callback_response.headers["location"] == "/chat"
    assert COOKIE_NAME in callback_response.cookies
    session_response = client.get("/api/auth/session")
    assert session_response.status_code == 200
    assert session_response.json()["user"] == {
        "id": 1,
        "username": "alice",
        "displayName": "Alice Analyst",
        "avatarUrl": None,
        "isAdmin": False,
    }
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.username == "alice")).scalar_one()
        assert user.casdoor_subject == "cipher/alice-id"


def test_embedded_casdoor_callback_returns_same_origin_completion_bridge(
    client, monkeypatch
) -> None:
    configure_casdoor(monkeypatch)

    async def fake_exchange(**_kwargs):
        return {
            "sub": "cipher/embedded-user-id",
            "preferred_username": "embedded-user",
        }

    monkeypatch.setattr("app.routes.auth.exchange_code_for_userinfo", fake_exchange)
    login_response = client.get(
        "/api/auth/casdoor/login?return_to=%2Fauth%2Fcasdoor%2Fembedded",
        follow_redirects=False,
    )
    state = parse_qs(urlsplit(login_response.headers["location"]).query)["state"][0]

    callback_response = client.get(
        f"/api/auth/casdoor/callback?code=embedded-code&state={state}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 200
    assert callback_response.headers["content-type"].startswith("text/html")
    assert "cipher:casdoor-auth" in callback_response.text
    assert '"status":"success"' in callback_response.text
    assert "window.top===window" in callback_response.text
    assert 'window.location.replace("/chat")' in callback_response.text
    assert "frame-ancestors 'self'" in callback_response.headers["content-security-policy"]
    assert COOKIE_NAME in callback_response.cookies


def test_embedded_casdoor_error_returns_completion_bridge_without_session(
    client, monkeypatch
) -> None:
    configure_casdoor(monkeypatch)
    login_response = client.get(
        "/api/auth/casdoor/login?return_to=%2Fauth%2Fcasdoor%2Fembedded",
        follow_redirects=False,
    )
    state = parse_qs(urlsplit(login_response.headers["location"]).query)["state"][0]

    callback_response = client.get(
        f"/api/auth/casdoor/callback?error=access_denied&state={state}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 200
    assert '"status":"error"' in callback_response.text
    assert "access_denied" in callback_response.text
    assert 'window.location.replace("/?casdoor_error=access_denied")' in callback_response.text
    assert COOKIE_NAME not in callback_response.cookies


def test_casdoor_callback_rejects_state_not_bound_to_browser(client, monkeypatch) -> None:
    configure_casdoor(monkeypatch)
    client.get("/api/auth/casdoor/login", follow_redirects=False)

    response = client.get(
        "/api/auth/casdoor/callback?code=authorization-code&state=attacker-state",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Casdoor login state is missing or expired"}


def test_enabled_casdoor_settings_require_complete_application_config() -> None:
    with pytest.raises(ValueError, match="CASDOOR_ENABLED requires"):
        config_module.Settings(
            _env_file=None,
            app_env="test",
            casdoor_enabled=True,
            casdoor_endpoint="https://login.example.test",
        )
