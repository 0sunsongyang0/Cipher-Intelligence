from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit
import base64

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User


CASDOOR_PROVIDER_LABELS: tuple[tuple[str, str], ...] = (
    ("google", "Google"),
    ("github", "GitHub"),
    ("apple", "Apple"),
    ("microsoftonline", "Microsoft"),
    ("azuread", "Microsoft Entra ID"),
    ("wechat", "微信"),
    ("qq", "QQ"),
    ("dingtalk", "钉钉"),
    ("lark", "飞书"),
    ("gitlab", "GitLab"),
    ("gitee", "Gitee"),
    ("linkedin", "LinkedIn"),
    ("slack", "Slack"),
    ("discord", "Discord"),
    ("facebook", "Facebook"),
    ("twitter", "X / Twitter"),
)


def _casdoor_server_endpoint() -> str:
    """Return the address used by backend-to-Casdoor HTTP calls."""
    return (settings.casdoor_internal_endpoint.strip() or settings.casdoor_endpoint).rstrip("/")


_casdoor_service_token: str | None = None
_casdoor_service_token_key: tuple[str, str] | None = None
_casdoor_service_token_expires_at = 0.0


class CasdoorAuthError(RuntimeError):
    """Raised when Casdoor cannot complete or validate an authentication flow."""


class CasdoorAccountError(RuntimeError):
    """Raised when a Casdoor identity cannot be mapped to a local account."""


@dataclass(frozen=True)
class CasdoorIdentity:
    subject: str
    username: str
    display_name: str | None
    email: str | None
    roles: frozenset[str]


@dataclass(frozen=True)
class CasdoorProfile:
    display_name: str | None
    email: str | None
    email_verified: bool
    avatar_url: str | None
    connected_providers: tuple[str, ...]
    mfa_enabled: bool
    password_enabled: bool
    last_signin_at: str | None


def build_authorization_url(*, redirect_uri: str, state: str, theme: str | None = None) -> str:
    parameters = {
        "client_id": settings.casdoor_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": settings.casdoor_scope,
        "state": state,
        "language": "zh",
    }
    if theme == "dark":
        parameters["theme"] = "dark"
    elif theme == "light":
        parameters["theme"] = "default"
    query = urlencode(parameters)
    return f"{settings.casdoor_endpoint.rstrip('/')}/login/oauth/authorize?{query}"


async def exchange_code_for_userinfo(*, code: str, redirect_uri: str) -> dict[str, Any]:
    endpoint = _casdoor_server_endpoint()
    token_payload = {
        "grant_type": "authorization_code",
        "client_id": settings.casdoor_client_id,
        "client_secret": settings.casdoor_client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.casdoor_timeout_seconds) as client:
            token_response = await client.post(
                f"{endpoint}/api/login/oauth/access_token",
                data=token_payload,
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            token_data = token_response.json()
            if not isinstance(token_data, dict):
                raise CasdoorAuthError("Casdoor returned an invalid token response")
            access_token = token_data.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise CasdoorAuthError("Casdoor token response did not contain an access token")

            userinfo_response = await client.get(
                f"{endpoint}/api/userinfo",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
            userinfo_response.raise_for_status()
            userinfo = userinfo_response.json()
    except CasdoorAuthError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise CasdoorAuthError("Casdoor authentication request failed") from error

    if not isinstance(userinfo, dict):
        raise CasdoorAuthError("Casdoor returned invalid user information")
    return userinfo


def _claim_text(userinfo: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = userinfo.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _claim_bool(userinfo: dict[str, Any], *names: str) -> bool:
    for name in names:
        value = userinfo.get(name)
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no", ""}:
                return False
    return False


def _safe_web_url(value: str | None) -> str | None:
    if value is None or len(value) > 2048:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def parse_casdoor_profile(userinfo: dict[str, Any]) -> CasdoorProfile:
    connected_providers = tuple(
        provider
        for provider, _label in CASDOOR_PROVIDER_LABELS
        if userinfo.get(provider) not in (None, "", False)
    )
    mfa_enabled = any(
        _claim_bool(userinfo, name)
        for name in (
            "mfaEmailEnabled",
            "mfaPhoneEnabled",
            "mfaPushEnabled",
            "mfaRadiusEnabled",
        )
    ) or any(
        bool(userinfo.get(name))
        for name in ("multiFactorAuths", "mfaItems", "webauthnCredentials", "totpSecret")
    )
    email = _claim_text(userinfo, "email")
    if email is not None:
        email = email[:320]

    return CasdoorProfile(
        # Casdoor's management API uses `name` for the immutable username,
        # while OIDC commonly uses it as the display name. Prefer the explicit
        # Casdoor display-name fields so an account refresh never renames the
        # profile back to its login name.
        display_name=_claim_text(userinfo, "displayName", "display_name", "name"),
        email=email,
        email_verified=_claim_bool(userinfo, "email_verified", "emailVerified"),
        avatar_url=_safe_web_url(_claim_text(userinfo, "picture", "avatar")),
        connected_providers=connected_providers,
        mfa_enabled=mfa_enabled,
        password_enabled=bool(_claim_text(userinfo, "password")),
        last_signin_at=_claim_text(userinfo, "lastSigninTime", "last_signin_time"),
    )


def apply_casdoor_profile(user: User, userinfo: dict[str, Any]) -> CasdoorProfile:
    profile = parse_casdoor_profile(userinfo)
    if profile.display_name:
        user.display_name = profile.display_name[:80]
    user.email = profile.email
    user.email_verified = profile.email_verified
    user.casdoor_avatar_url = profile.avatar_url
    user.casdoor_providers_json = json.dumps(
        list(profile.connected_providers), separators=(",", ":")
    )
    user.casdoor_mfa_enabled = profile.mfa_enabled
    user.casdoor_password_enabled = profile.password_enabled
    user.casdoor_last_signin_at = profile.last_signin_at
    user.casdoor_last_synced_at = datetime.now(timezone.utc)
    # Subscription is administered through Casdoor's built-in User type field.
    # This is directly editable in the user screen and is included in both the
    # management API payload and OIDC user information.
    plan = _claim_text(userinfo, "type", "userType", "user_type")
    normalized_plan = (plan or "").strip().lower()
    if not settings.casdoor_commerce_enabled and normalized_plan in {"free", "standard", "pro", "enterprise"}:
        user.subscription_tier = normalized_plan
    return profile


async def _casdoor_api_access_token(client: httpx.AsyncClient) -> str:
    global _casdoor_service_token
    global _casdoor_service_token_expires_at
    global _casdoor_service_token_key

    endpoint = _casdoor_server_endpoint()
    token_key = (endpoint, settings.casdoor_client_id)
    if (
        _casdoor_service_token is not None
        and _casdoor_service_token_key == token_key
        and time.monotonic() < _casdoor_service_token_expires_at
    ):
        return _casdoor_service_token

    try:
        response = await client.post(
                f"{endpoint}/api/login/oauth/access_token",
            data={
                "grant_type": "client_credentials",
                "client_id": settings.casdoor_client_id,
                "client_secret": settings.casdoor_client_secret,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise CasdoorAuthError("Casdoor service authentication failed") from error

    access_token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise CasdoorAuthError("Casdoor service token response was invalid")
    expires_in = payload.get("expires_in")
    token_lifetime = (
        float(expires_in)
        if isinstance(expires_in, (int, float)) and expires_in > 0
        else 300.0
    )
    _casdoor_service_token = access_token
    _casdoor_service_token_key = token_key
    _casdoor_service_token_expires_at = time.monotonic() + max(30.0, token_lifetime - 30.0)
    return access_token


def _casdoor_api_payload(response: httpx.Response, *, require_user: bool) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise CasdoorAuthError("Casdoor account request failed") from error

    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise CasdoorAuthError("Casdoor rejected the account request")
    data = payload.get("data")
    if require_user and not isinstance(data, dict):
        raise CasdoorAuthError("Casdoor returned invalid account data")
    return data if isinstance(data, dict) else {}


async def _get_casdoor_user_with_client(
    client: httpx.AsyncClient, *, account_id: str, access_token: str
) -> dict[str, Any]:
    try:
        response = await client.get(
            f"{_casdoor_server_endpoint()}/api/get-user",
            params={"id": account_id},
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
        )
    except httpx.HTTPError as error:
        raise CasdoorAuthError("Casdoor account request failed") from error
    return _casdoor_api_payload(response, require_user=True)


async def fetch_casdoor_user(account_id: str) -> dict[str, Any]:
    if not settings.casdoor_auth_enabled:
        raise CasdoorAuthError("Casdoor account sync is not enabled")
    if not account_id or len(account_id) > 255 or "/" not in account_id:
        raise CasdoorAuthError("Casdoor account identifier is invalid")

    async with httpx.AsyncClient(timeout=settings.casdoor_timeout_seconds) as client:
        access_token = await _casdoor_api_access_token(client)
        return await _get_casdoor_user_with_client(
            client, account_id=account_id, access_token=access_token
        )


async def update_casdoor_profile(
    account_id: str,
    *,
    display_name: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    if not settings.casdoor_auth_enabled:
        raise CasdoorAuthError("Casdoor account sync is not enabled")
    if not account_id or len(account_id) > 255 or "/" not in account_id:
        raise CasdoorAuthError("Casdoor account identifier is invalid")

    async with httpx.AsyncClient(timeout=settings.casdoor_timeout_seconds) as client:
        access_token = await _casdoor_api_access_token(client)
        userinfo = await _get_casdoor_user_with_client(
            client, account_id=account_id, access_token=access_token
        )
        if display_name is not None:
            userinfo["displayName"] = display_name
        if email is not None:
            previous_email = _claim_text(userinfo, "email")
            userinfo["email"] = email
            if previous_email != email:
                # A newly bound address must not inherit verification from the
                # old one. Casdoor remains the source of truth for this flag.
                userinfo["emailVerified"] = False
                userinfo["email_verified"] = False
        try:
            response = await client.post(
                f"{_casdoor_server_endpoint()}/api/update-user",
                params={"id": account_id},
                json=userinfo,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
        except httpx.HTTPError as error:
            raise CasdoorAuthError("Casdoor profile update failed") from error
        _casdoor_api_payload(response, require_user=False)
        return userinfo


async def send_casdoor_email_verification(account_id: str, email: str) -> None:
    if not settings.casdoor_auth_enabled:
        raise CasdoorAuthError("Casdoor account sync is not enabled")
    if not account_id or len(account_id) > 255 or "/" not in account_id:
        raise CasdoorAuthError("Casdoor account identifier is invalid")
    normalized_email = email.strip()
    if not normalized_email:
        raise CasdoorAuthError("Casdoor account email is missing")

    api_endpoint = settings.casdoor_internal_endpoint.strip() or settings.casdoor_endpoint
    async with httpx.AsyncClient(timeout=settings.casdoor_timeout_seconds) as client:
        access_token = await _casdoor_api_access_token(client)
        payload = {
            "type": "email",
            "dest": normalized_email,
            "applicationId": (
                f"{settings.casdoor_application_owner}/"
                f"{settings.casdoor_application_name}"
            ),
            "method": "login",
            "captchaType": "none",
        }
        try:
            response = await client.post(
                f"{api_endpoint.rstrip('/')}/api/send-verification-code",
                data=payload,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
        except httpx.HTTPError as error:
            raise CasdoorAuthError("Casdoor email verification request failed") from error
        _casdoor_api_payload(response, require_user=False)


async def verify_casdoor_email(account_id: str, email: str, code: str) -> dict[str, Any]:
    if not settings.casdoor_auth_enabled:
        raise CasdoorAuthError("Casdoor account sync is not enabled")
    if not account_id or len(account_id) > 255 or "/" not in account_id:
        raise CasdoorAuthError("Casdoor account identifier is invalid")
    normalized_email = email.strip()
    normalized_code = code.strip()
    if not normalized_email or not normalized_code.isdigit() or len(normalized_code) > 12:
        raise CasdoorAuthError("Casdoor email verification input is invalid")

    organization, username = account_id.split("/", 1)
    async with httpx.AsyncClient(timeout=settings.casdoor_timeout_seconds) as client:
        access_token = await _casdoor_api_access_token(client)
        try:
            response = await client.post(
                f"{_casdoor_server_endpoint()}/api/verify-code",
                json={
                    "organization": organization,
                    "name": username,
                    "username": normalized_email,
                    "code": normalized_code,
                },
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
        except httpx.HTTPError as error:
            raise CasdoorAuthError("Casdoor email code verification failed") from error
        _casdoor_api_payload(response, require_user=False)

        userinfo = await _get_casdoor_user_with_client(
            client, account_id=account_id, access_token=access_token
        )
        if _claim_text(userinfo, "email") != normalized_email:
            raise CasdoorAuthError("Casdoor account email changed during verification")
        userinfo["emailVerified"] = True
        userinfo["email_verified"] = True
        try:
            update_response = await client.post(
                f"{_casdoor_server_endpoint()}/api/update-user",
                params={"id": account_id},
                json=userinfo,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
        except httpx.HTTPError as error:
            raise CasdoorAuthError("Casdoor email verification update failed") from error
        _casdoor_api_payload(update_response, require_user=False)
        return userinfo


async def _post_casdoor_mfa(path: str, data: dict[str, str]) -> dict[str, Any]:
    if not settings.casdoor_auth_enabled:
        raise CasdoorAuthError("Casdoor account sync is not enabled")
    async with httpx.AsyncClient(timeout=settings.casdoor_timeout_seconds) as client:
        access_token = await _casdoor_api_access_token(client)
        try:
            response = await client.post(
                f"{_casdoor_server_endpoint()}{path}",
                data=data,
                headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as error:
            raise CasdoorAuthError("Casdoor MFA request failed") from error
        return _casdoor_api_payload(response, require_user=False)


async def initiate_casdoor_totp(account_id: str) -> dict[str, str]:
    owner, name = account_id.split("/", 1)
    data = await _post_casdoor_mfa(
        "/api/mfa/setup/initiate", {"owner": owner, "name": name, "mfaType": "totp"}
    )
    secret = data.get("secret")
    recovery_codes = data.get("recoveryCodes")
    if not isinstance(secret, str) or not secret or not isinstance(recovery_codes, list) or not recovery_codes:
        raise CasdoorAuthError("Casdoor returned invalid MFA setup data")
    recovery_code = recovery_codes[0]
    if not isinstance(recovery_code, str) or not recovery_code:
        raise CasdoorAuthError("Casdoor returned invalid recovery code")
    return {"secret": secret, "recoveryCode": recovery_code}


async def enable_casdoor_totp(
    account_id: str, *, secret: str, recovery_code: str, passcode: str
) -> None:
    await _post_casdoor_mfa(
        "/api/mfa/setup/verify",
        {"mfaType": "totp", "secret": secret, "passcode": passcode},
    )
    owner, name = account_id.split("/", 1)
    await _post_casdoor_mfa(
        "/api/mfa/setup/enable",
        {
            "owner": owner,
            "name": name,
            "mfaType": "totp",
            "secret": secret,
            "recoveryCodes": recovery_code,
        },
    )


async def delete_casdoor_mfa(account_id: str) -> None:
    owner, name = account_id.split("/", 1)
    await _post_casdoor_mfa("/api/delete-mfa", {"owner": owner, "name": name})


async def get_casdoor_link_providers() -> list[dict[str, str]]:
    endpoints = {
        "Google": ("google", "Google", "https://accounts.google.com/signin/oauth", "profile+email"),
        "GitHub": ("github", "GitHub", "https://github.com/login/oauth/authorize", "user:email+read:user"),
        "AzureAD": ("azuread", "Microsoft", "https://login.microsoftonline.com/common/oauth2/v2.0/authorize", "user.read"),
        "MicrosoftOnline": ("microsoftonline", "Microsoft", "https://login.microsoftonline.com/common/oauth2/v2.0/authorize", "openid%20profile%20email"),
    }
    async with httpx.AsyncClient(timeout=settings.casdoor_timeout_seconds) as client:
        token = await _casdoor_api_access_token(client)
        try:
            response = await client.get(
                f"{_casdoor_server_endpoint()}/api/get-application",
                params={"id": f"{settings.casdoor_application_owner}/{settings.casdoor_application_name}"},
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as error:
            raise CasdoorAuthError("Casdoor provider request failed") from error
        application = _casdoor_api_payload(response, require_user=True)
    result: list[dict[str, str]] = []
    for item in application.get("providers", []):
        provider = item.get("provider") if isinstance(item, dict) else None
        provider_type = provider.get("type") if isinstance(provider, dict) else None
        metadata = endpoints.get(provider_type)
        if metadata is None or not item.get("canSignIn"):
            continue
        provider_id, label, endpoint, default_scope = metadata
        provider_name = item.get("name")
        client_id = provider.get("clientId")
        if not isinstance(provider_name, str) or not isinstance(client_id, str) or not client_id:
            continue
        query = (
            f"?&application={settings.casdoor_application_name}"
            f"&provider={provider_name}&method=link&from=/cipher-link-callback"
        )
        state = base64.b64encode(query.encode()).decode()
        scope = provider.get("scopes") or default_scope
        authorization_url = endpoint + "?" + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": f"{settings.casdoor_endpoint.rstrip('/')}/callback",
                "scope": scope.replace("+", " ").replace("%20", " "),
                "response_type": "code",
                "state": state,
            }
        )
        result.append({"provider": provider_id, "label": label, "authorizationUrl": authorization_url})
    return result


def _claim_roles(userinfo: dict[str, Any]) -> frozenset[str]:
    values: list[Any] = []
    for name in ("roles", "groups"):
        claim = userinfo.get(name)
        if isinstance(claim, list):
            values.extend(claim)
        elif isinstance(claim, str):
            values.extend(claim.split(","))

    roles: set[str] = set()
    for value in values:
        if isinstance(value, str) and value.strip():
            roles.add(value.strip().casefold())
        elif isinstance(value, dict):
            role_name = value.get("name")
            if isinstance(role_name, str) and role_name.strip():
                roles.add(role_name.strip().casefold())
    return frozenset(roles)


def parse_casdoor_identity(userinfo: dict[str, Any]) -> CasdoorIdentity:
    subject = _claim_text(userinfo, "sub", "id")
    if subject is None or len(subject) > 255:
        raise CasdoorAuthError("Casdoor user information is missing a valid subject")

    preferred_username = _claim_text(userinfo, "preferred_username", "username")
    email = _claim_text(userinfo, "email")
    username = preferred_username or (email.split("@", 1)[0] if email else None)
    if username is None:
        username = subject.rsplit("/", 1)[-1]
    username = username.strip()[:64]
    if len(username) < 3:
        username = f"user-{username}"[:64]

    return CasdoorIdentity(
        subject=subject,
        username=username,
        display_name=_claim_text(userinfo, "name", "displayName", "display_name"),
        email=email,
        roles=_claim_roles(userinfo),
    )


def _get_user_by_username(db: Session, username: str) -> User | None:
    return db.execute(
        select(User).where(func.lower(User.username) == username.casefold())
    ).scalar_one_or_none()


def _available_external_username(db: Session, identity: CasdoorIdentity) -> str:
    candidate = identity.username
    if _get_user_by_username(db, candidate) is None:
        return candidate

    suffix = hashlib.sha256(identity.subject.encode("utf-8")).hexdigest()[:8]
    candidate = f"{identity.username[:55]}-{suffix}"
    if _get_user_by_username(db, candidate) is None:
        return candidate

    for _ in range(20):
        random_suffix = secrets.token_hex(3)
        candidate = f"{identity.username[:57]}-{random_suffix}"
        if _get_user_by_username(db, candidate) is None:
            return candidate
    raise CasdoorAccountError("Unable to allocate a local username for this Casdoor account")


def _mapped_admin_status(identity: CasdoorIdentity) -> bool | None:
    configured_users = settings.casdoor_admin_user_set
    configured_roles = settings.casdoor_admin_role_set
    if not configured_users and not configured_roles:
        return None

    identity_values = {identity.subject.casefold(), identity.username.casefold()}
    if identity.email:
        identity_values.add(identity.email.casefold())
    return bool(
        configured_users.intersection(identity_values)
        or configured_roles.intersection(identity.roles)
    )


def sync_casdoor_user(db: Session, userinfo: dict[str, Any]) -> User:
    if _claim_bool(userinfo, "isForbidden", "isDeleted", "forbidden", "deleted"):
        raise CasdoorAccountError("This Casdoor account is disabled")
    identity = parse_casdoor_identity(userinfo)
    user = db.execute(
        select(User).where(User.casdoor_subject == identity.subject)
    ).scalar_one_or_none()

    if user is None:
        username_match = _get_user_by_username(db, identity.username)
        if (
            username_match is not None
            and username_match.casdoor_subject is None
            and settings.casdoor_auto_link_users
        ):
            user = username_match
            user.casdoor_subject = identity.subject
            user.auth_source = "hybrid"
        elif settings.casdoor_auto_create_users:
            user = User(
                username=_available_external_username(db, identity),
                casdoor_subject=identity.subject,
                display_name=identity.display_name,
                password_hash=f"casdoor_external$0${secrets.token_hex(16)}${secrets.token_hex(32)}",
                auth_source="casdoor",
                is_active=True,
                is_admin=False,
            )
            db.add(user)
        else:
            raise CasdoorAccountError("This Casdoor account has not been linked to Cipher")

    if not user.is_active:
        raise CasdoorAccountError("This Cipher account is disabled")

    user.casdoor_name = identity.username
    if user.casdoor_subject is not None and user.auth_source != "local":
        user.auth_source = "casdoor"
    apply_casdoor_profile(user, userinfo)
    mapped_admin_status = _mapped_admin_status(identity)
    if mapped_admin_status is not None:
        user.is_admin = mapped_admin_status

    db.add(user)
    db.flush()
    return user
