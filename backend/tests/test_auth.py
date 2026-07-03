from datetime import timedelta

import pytest
from sqlalchemy import select

import app.config as config_module
from app.auth import COOKIE_NAME, hash_token
from app.database import SessionLocal
from app.models import Session as SessionModel, now_utc


def login(client, password: str = "change-me", headers: dict[str, str] | None = None):
    return client.post(
        "/api/auth/login",
        json={"password": password},
        headers=headers or {},
    )


def test_login_sets_campus_session_cookie(client) -> None:
    response = login(client)

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    assert "campus_session" in response.cookies



def test_login_sets_expected_cookie_attributes_for_test_env(client) -> None:
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
    client, monkeypatch, app_env: str, session_cookie_secure: bool | None
) -> None:
    monkeypatch.setattr(config_module.settings, "app_env", app_env)
    monkeypatch.setattr(config_module.settings, "session_cookie_secure", session_cookie_secure)

    response = login(client)

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]



def test_unauthenticated_conversations_request_returns_401(client) -> None:
    response = client.get("/api/conversations")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}



def test_session_status_reflects_login_and_logout(client) -> None:
    login_response = login(client)
    assert login_response.status_code == 200

    session_response = client.get("/api/auth/session")
    assert session_response.status_code == 200
    assert session_response.json() == {"authenticated": True}

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json() == {"authenticated": False}

    session_response = client.get("/api/auth/session")
    assert session_response.status_code == 200
    assert session_response.json() == {"authenticated": False}



def test_logout_removes_server_side_session(client) -> None:
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
    assert reused_cookie_response.json() == {"authenticated": False}



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
    response = client.get("/api/conversations")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}

    with SessionLocal() as db:
        session = db.execute(
            select(SessionModel).where(SessionModel.token_hash == hash_token(expired_token))
        ).scalar_one_or_none()
        assert session is None



def test_login_returns_429_after_five_failed_attempts_for_same_client_host(client) -> None:
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
