import asyncio
import base64
import io

from PIL import Image
from sqlalchemy import select

from app.config import settings
from app.casdoor_auth import send_casdoor_email_verification, update_casdoor_profile
from app.database import SessionLocal
from app.models import User
from app.routes.account import update_profile
from app.schemas import AccountUpdateRequest


def build_avatar_data_url(
    *,
    size: tuple[int, int] = (128, 128),
    color: tuple[int, int, int] = (91, 74, 196),
) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def login(client, username: str, password: str = "StrongPass123!"):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )


def configure_casdoor_sync(monkeypatch) -> None:
    values = {
        "casdoor_enabled": True,
        "casdoor_endpoint": "https://login.example.test",
        "casdoor_internal_endpoint": "",
        "casdoor_client_id": "cipher-client",
        "casdoor_client_secret": "cipher-secret",
        "casdoor_organization_name": "cipher",
        "casdoor_application_name": "cipher-ai",
        "casdoor_application_owner": "admin",
        "casdoor_display_name": "Cipher SSO",
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def attach_casdoor_subject(user_id: int, subject: str = "cipher/alice") -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.casdoor_subject = subject
        db.add(user)
        db.commit()


def test_registration_accepts_avatar_and_optional_display_name(
    client, create_invite_code, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "avatar_storage_path", str(tmp_path / "avatars"))
    create_invite_code(code="profile-invite", max_uses=1)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "Alice",
            "password": "StrongPass123!",
            "inviteCode": "profile-invite",
            "displayName": "Alice Chen",
            "avatarDataUrl": build_avatar_data_url(),
        },
    )

    assert response.status_code == 201
    user_payload = response.json()["user"]
    assert user_payload["username"] == "Alice"
    assert user_payload["displayName"] == "Alice Chen"
    assert user_payload["avatarUrl"].startswith("/api/account/avatars/user-")

    avatar_response = client.get(user_payload["avatarUrl"])
    assert avatar_response.status_code == 200
    assert avatar_response.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(avatar_response.content)) as avatar:
        assert avatar.format == "WEBP"
        assert max(avatar.size) <= 512


def test_usernames_are_unique_without_case_sensitivity(
    client, create_user, create_invite_code
) -> None:
    create_user(username="Alice", password="StrongPass123!")
    create_invite_code(code="case-invite", max_uses=1)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "password": "StrongPass123!",
            "inviteCode": "case-invite",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Username is already taken"}


def test_login_username_lookup_is_case_insensitive(client, create_user) -> None:
    create_user(username="Alice", password="StrongPass123!")

    response = login(client, "alice")

    assert response.status_code == 200
    assert response.json()["user"]["username"] == "Alice"


def test_profile_update_changes_display_name_but_rejects_username(
    client, create_user
) -> None:
    user = create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200

    updated = client.patch(
        "/api/account/profile",
        json={"displayName": "Security Researcher"},
    )
    forbidden = client.patch(
        "/api/account/profile",
        json={"username": "renamed"},
    )

    assert updated.status_code == 200
    assert updated.json()["user"]["displayName"] == "Security Researcher"
    assert forbidden.status_code == 422
    with SessionLocal() as db:
        stored_user = db.execute(select(User).where(User.id == user.id)).scalar_one()
        assert stored_user.username == "alice"
        assert stored_user.display_name == "Security Researcher"


def test_display_names_can_repeat(client, create_user) -> None:
    first = create_user(username="alice", password="StrongPass123!")
    second = create_user(username="bob", password="StrongPass123!")

    assert login(client, "alice").status_code == 200
    assert client.patch(
        "/api/account/profile", json={"displayName": "Analyst"}
    ).status_code == 200
    assert login(client, "bob").status_code == 200
    assert client.patch(
        "/api/account/profile", json={"displayName": "Analyst"}
    ).status_code == 200

    with SessionLocal() as db:
        display_names = db.execute(
            select(User.display_name).where(User.id.in_([first.id, second.id]))
        ).scalars().all()
        assert display_names == ["Analyst", "Analyst"]


def test_profile_avatar_can_be_replaced_and_removed(
    client, create_user, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "avatar_storage_path", str(tmp_path / "avatars"))
    create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200

    first_update = client.patch(
        "/api/account/profile",
        json={"avatarDataUrl": build_avatar_data_url(color=(20, 40, 80))},
    )
    assert first_update.status_code == 200
    avatar_url = first_update.json()["user"]["avatarUrl"]
    assert avatar_url is not None
    assert client.get(avatar_url).status_code == 200

    removed = client.patch("/api/account/profile", json={"removeAvatar": True})
    assert removed.status_code == 200
    assert removed.json()["user"]["avatarUrl"] is None
    assert client.get(avatar_url).status_code == 404


def test_avatar_validation_rejects_unsafe_or_invalid_files(
    client, create_user
) -> None:
    create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200

    svg_payload = base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>").decode()
    invalid_type = client.patch(
        "/api/account/profile",
        json={"avatarDataUrl": f"data:image/svg+xml;base64,{svg_payload}"},
    )
    tiny_image = client.patch(
        "/api/account/profile",
        json={"avatarDataUrl": build_avatar_data_url(size=(16, 16))},
    )

    assert invalid_type.status_code == 400
    assert invalid_type.json() == {"detail": "Avatar must be a JPEG, PNG, or WebP image"}
    assert tiny_image.status_code == 400
    assert tiny_image.json() == {"detail": "Avatar must be at least 32 x 32 pixels"}


def test_account_overview_syncs_email_providers_and_security_from_casdoor(
    client, create_user, monkeypatch
) -> None:
    user = create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200
    attach_casdoor_subject(user.id)
    configure_casdoor_sync(monkeypatch)

    async def fake_fetch(subject: str):
        assert subject == "cipher/alice"
        return {
            "name": "alice",
            "displayName": "Alice from Casdoor",
            "email": "alice@example.test",
            "emailVerified": True,
            "avatar": "https://cdn.example.test/alice.png",
            "github": "alice-gh",
            "google": "alice-google",
            "mfaEmailEnabled": True,
            "password": "hashed-value",
            "lastSigninTime": "2026-08-06T08:00:00Z",
        }

    monkeypatch.setattr("app.routes.account.fetch_casdoor_user", fake_fetch)

    response = client.get("/api/account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["displayName"] == "Alice from Casdoor"
    assert payload["user"]["avatarUrl"] == "https://cdn.example.test/alice.png"
    assert payload["workspaceAvatarUrl"] is None
    assert payload["identityAvatarUrl"] == "https://cdn.example.test/alice.png"
    assert payload["identity"] == {
        "source": "casdoor",
        "providerName": "Cipher SSO",
        "email": "alice@example.test",
        "emailVerified": True,
        "connectedAccounts": [
            {"provider": "google", "label": "Google"},
            {"provider": "github", "label": "GitHub"},
        ],
        "mfaEnabled": True,
        "passwordEnabled": True,
        "lastSignInAt": "2026-08-06T08:00:00Z",
        "lastSyncedAt": payload["identity"]["lastSyncedAt"],
        "syncStatus": "current",
        "syncAvailable": True,
        "managementUrl": "https://login.example.test/account",
    }
    assert payload["identity"]["lastSyncedAt"] is not None

    with SessionLocal() as db:
        stored = db.get(User, user.id)
        assert stored is not None
        assert stored.email == "alice@example.test"
        assert stored.email_verified is True
        assert stored.casdoor_providers_json == '["google","github"]'


def test_account_overview_exposes_sso_management_url(
    client, create_user, monkeypatch
) -> None:
    user = create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200
    attach_casdoor_subject(user.id)
    configure_casdoor_sync(monkeypatch)

    async def fake_fetch(_subject: str):
        return {
            "name": "alice",
            "email": "alice@example.test",
            "emailVerified": False,
        }

    monkeypatch.setattr("app.routes.account.fetch_casdoor_user", fake_fetch)

    response = client.get("/api/account")

    assert response.status_code == 200
    assert response.json()["identity"]["managementUrl"] == "https://login.example.test/account"


def test_unverified_casdoor_account_can_request_email_verification(
    client, create_user, monkeypatch
) -> None:
    user = create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200
    attach_casdoor_subject(user.id)
    configure_casdoor_sync(monkeypatch)
    with SessionLocal() as db:
        stored = db.get(User, user.id)
        assert stored is not None
        stored.email = "alice@example.test"
        stored.email_verified = False
        db.commit()

    calls: list[tuple[str, str]] = []

    async def fake_send(account_id: str, email: str) -> None:
        calls.append((account_id, email))

    monkeypatch.setattr("app.routes.account.send_casdoor_email_verification", fake_send)

    response = client.post("/api/account/email-verification")

    assert response.status_code == 200
    assert response.json() == {
        "email": "alice@example.test",
        "sent": True,
        "message": "验证邮件已发送，请查看邮箱。",
    }
    assert calls == [("cipher/alice", "alice@example.test")]


def test_verified_casdoor_email_does_not_send_duplicate_verification(
    client, create_user, monkeypatch
) -> None:
    user = create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200
    attach_casdoor_subject(user.id)
    configure_casdoor_sync(monkeypatch)
    with SessionLocal() as db:
        stored = db.get(User, user.id)
        assert stored is not None
        stored.email = "alice@example.test"
        stored.email_verified = True
        db.commit()

    async def should_not_send(_account_id: str, _email: str) -> None:
        raise AssertionError("verified emails should not request another code")

    monkeypatch.setattr("app.routes.account.send_casdoor_email_verification", should_not_send)

    response = client.post("/api/account/email-verification")

    assert response.status_code == 200
    assert response.json() == {
        "email": "alice@example.test",
        "sent": False,
        "message": "邮箱已经验证。",
    }


def test_unverified_casdoor_email_can_confirm_code(
    client, create_user, monkeypatch
) -> None:
    user = create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200
    attach_casdoor_subject(user.id)
    configure_casdoor_sync(monkeypatch)
    with SessionLocal() as db:
        stored = db.get(User, user.id)
        assert stored is not None
        stored.email = "alice@example.test"
        stored.email_verified = False
        db.commit()

    calls: list[tuple[str, str, str]] = []

    async def fake_verify(account_id: str, email: str, code: str):
        calls.append((account_id, email, code))
        return {
            "displayName": "Alice",
            "email": email,
            "emailVerified": True,
            "github": "alice",
        }

    monkeypatch.setattr("app.routes.account.verify_casdoor_email", fake_verify)

    response = client.post(
        "/api/account/email-verification/confirm", json={"code": "123456"}
    )

    assert response.status_code == 200
    assert response.json()["identity"]["emailVerified"] is True
    assert calls == [("cipher/alice", "alice@example.test", "123456")]


def test_email_confirmation_rejects_non_numeric_code(client, create_user) -> None:
    create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200

    response = client.post(
        "/api/account/email-verification/confirm", json={"code": "not-code"}
    )

    assert response.status_code == 422


def test_account_overview_uses_cached_identity_when_casdoor_is_unavailable(
    client, create_user, monkeypatch
) -> None:
    user = create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200
    attach_casdoor_subject(user.id)
    configure_casdoor_sync(monkeypatch)
    with SessionLocal() as db:
        stored = db.get(User, user.id)
        assert stored is not None
        stored.email = "cached@example.test"
        stored.email_verified = True
        stored.casdoor_providers_json = '["github"]'
        db.commit()

    async def unavailable(_subject: str):
        from app.casdoor_auth import CasdoorAuthError

        raise CasdoorAuthError("offline")

    monkeypatch.setattr("app.routes.account.fetch_casdoor_user", unavailable)

    response = client.get("/api/account")

    assert response.status_code == 200
    assert response.json()["identity"]["syncStatus"] == "stale"
    assert response.json()["identity"]["email"] == "cached@example.test"
    assert response.json()["identity"]["connectedAccounts"] == [
        {"provider": "github", "label": "GitHub"}
    ]


def test_casdoor_profile_update_is_written_upstream_once_before_local_commit(
    client, create_user, monkeypatch
) -> None:
    user = create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200
    attach_casdoor_subject(user.id)
    configure_casdoor_sync(monkeypatch)
    calls: list[tuple[str, str | None, str | None]] = []

    async def fake_update(
        subject: str,
        *,
        display_name: str | None = None,
        email: str | None = None,
    ):
        calls.append((subject, display_name, email))
        return {
            "displayName": display_name,
            "email": email,
            "emailVerified": False,
        }

    monkeypatch.setattr("app.routes.account.update_casdoor_profile", fake_update)

    response = client.patch(
        "/api/account/profile",
        json={
            "displayName": "Threat Hunter",
            "email": "hunter@example.test",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["displayName"] == "Threat Hunter"
    assert payload["identity"]["email"] == "hunter@example.test"
    assert payload["identity"]["emailVerified"] is False
    assert calls == [("cipher/alice", "Threat Hunter", "hunter@example.test")]
    with SessionLocal() as db:
        stored = db.get(User, user.id)
        assert stored is not None
        assert stored.display_name == "Threat Hunter"
        assert stored.email == "hunter@example.test"
        assert stored.email_verified is False


def test_profile_update_rejects_invalid_email_without_calling_casdoor(
    client, create_user, monkeypatch
) -> None:
    user = create_user(username="alice", password="StrongPass123!")
    assert login(client, "alice").status_code == 200
    attach_casdoor_subject(user.id)
    configure_casdoor_sync(monkeypatch)
    calls: list[str] = []

    async def should_not_update(*args, **kwargs):
        calls.append("called")
        raise AssertionError("Casdoor should not be called for an invalid request")

    monkeypatch.setattr("app.routes.account.update_casdoor_profile", should_not_update)

    response = client.patch(
        "/api/account/profile",
        json={"email": "not-an-email"},
    )

    assert response.status_code == 422
    assert calls == []
    with SessionLocal() as db:
        stored = db.get(User, user.id)
        assert stored is not None
        assert stored.email is None


def test_casdoor_profile_client_resets_verification_when_email_changes(
    monkeypatch,
) -> None:
    configure_casdoor_sync(monkeypatch)
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"status": "ok", "data": None}

    class FakeAsyncClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, **kwargs):
            requests.append({"url": url, **kwargs})
            return FakeResponse()

    async def fake_access_token(_client) -> str:
        return "service-token"

    async def fake_get_user(_client, *, account_id: str, access_token: str):
        assert account_id == "cipher/alice"
        assert access_token == "service-token"
        return {
            "name": "alice",
            "displayName": "Alice",
            "email": "alice@example.test",
            "emailVerified": True,
        }

    monkeypatch.setattr("app.casdoor_auth.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("app.casdoor_auth._casdoor_api_access_token", fake_access_token)
    monkeypatch.setattr("app.casdoor_auth._get_casdoor_user_with_client", fake_get_user)

    updated = asyncio.run(
        update_casdoor_profile(
            "cipher/alice",
            display_name="Threat Hunter",
            email="hunter@example.test",
        )
    )

    assert updated["displayName"] == "Threat Hunter"
    assert updated["email"] == "hunter@example.test"
    assert updated["emailVerified"] is False
    assert updated["email_verified"] is False
    assert len(requests) == 1
    assert requests[0]["url"] == "https://login.example.test/api/update-user"
    assert requests[0]["params"] == {"id": "cipher/alice"}
    assert requests[0]["json"]["emailVerified"] is False


def test_casdoor_email_verification_uses_supported_form_contract(monkeypatch) -> None:
    configure_casdoor_sync(monkeypatch)
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"status": "ok", "data": None}

    class FakeAsyncClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, **kwargs):
            requests.append({"url": url, **kwargs})
            return FakeResponse()

    async def fake_access_token(_client) -> str:
        return "service-token"

    monkeypatch.setattr("app.casdoor_auth.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("app.casdoor_auth._casdoor_api_access_token", fake_access_token)

    asyncio.run(send_casdoor_email_verification("cipher/alice", " alice@example.test "))

    assert len(requests) == 1
    assert requests[0]["url"] == "https://login.example.test/api/send-verification-code"
    assert requests[0]["data"] == {
        "type": "email",
        "dest": "alice@example.test",
        "applicationId": "admin/cipher-ai",
        "method": "login",
        "captchaType": "none",
    }
    assert "json" not in requests[0]


def test_profile_route_commits_combined_casdoor_changes_once(monkeypatch) -> None:
    user = User(
        id=1,
        username="alice",
        display_name="Alice",
        is_admin=False,
        is_active=True,
        casdoor_subject="subject-id",
        casdoor_name="alice",
        email="alice@example.test",
        email_verified=True,
    )
    calls: list[tuple[str, str | None, str | None]] = []

    class FakeDb:
        commits = 0
        rollbacks = 0

        def add(self, _value) -> None:
            return None

        def commit(self) -> None:
            self.commits += 1

        def refresh(self, _value) -> None:
            return None

        def rollback(self) -> None:
            self.rollbacks += 1

    async def fake_update(
        account_id: str,
        *,
        display_name: str | None = None,
        email: str | None = None,
    ) -> dict:
        calls.append((account_id, display_name, email))
        return {
            "name": "alice",
            "displayName": display_name,
            "email": email,
            "emailVerified": False,
        }

    fake_db = FakeDb()
    monkeypatch.setattr("app.routes.account._get_account_user", lambda *_args: user)
    monkeypatch.setattr("app.routes.account.update_casdoor_profile", fake_update)

    result = asyncio.run(
        update_profile(
            AccountUpdateRequest(
                displayName="Threat Hunter",
                email="hunter@example.test",
            ),
            session=object(),
            db=fake_db,
        )
    )

    assert calls == [("cipher/alice", "Threat Hunter", "hunter@example.test")]
    assert fake_db.commits == 1
    assert fake_db.rollbacks == 0
    assert result.user.displayName == "Threat Hunter"
    assert result.identity.email == "hunter@example.test"
    assert result.identity.emailVerified is False
