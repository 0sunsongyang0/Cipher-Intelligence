import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.account_profiles import AvatarValidationError, delete_avatar, prepare_avatar, save_avatar
from app.account_security import consume_recovery_code, record_login_event, reveal_secret, verify_totp
from app.audit import record_audit_event
from app.auth import (
    COOKIE_NAME,
    SESSION_TTL,
    authenticate_user,
    consume_invite_code,
    create_session,
    create_user_account,
    delete_session,
    get_client_ip,
    get_invite_code_record,
    get_session_record,
    get_session_user,
    is_duplicate_username_error,
    validate_registration_password,
    validate_registration_username,
    verify_shared_password,
    serialize_user,
)
from app.config import settings
from app.casdoor_auth import (
    CasdoorAccountError,
    CasdoorAuthError,
    build_authorization_url,
    exchange_code_for_userinfo,
    sync_casdoor_user,
)
from app.casdoor_commerce import sync_user_commerce
from app.database import get_db
from app.tenancy import sync_casdoor_tenancy
from app.rate_limit import clear_failed_attempts, is_rate_limited, record_failed_attempt
from app.schemas import (
    AuthSuccess,
    CasdoorAuthConfig,
    LoginRequest,
    RegisterRequest,
    SessionStatus,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/auth", tags=["auth"])
CASDOOR_FLOW_TTL_SECONDS = 10 * 60
CASDOOR_USER_FLOW_COOKIE = "cipher_casdoor_oauth"
CASDOOR_ADMIN_FLOW_COOKIE = "cipher_casdoor_admin_oauth"
CASDOOR_EMBEDDED_RETURN_TO = "/auth/casdoor/embedded"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=int(SESSION_TTL.total_seconds()),
        samesite="lax",
        secure=settings.session_cookie_secure_enabled,
    )


def _casdoor_flow_cookie_name(*, admin: bool, state: str) -> str:
    prefix = CASDOOR_ADMIN_FLOW_COOKIE if admin else CASDOOR_USER_FLOW_COOKIE
    return f"{prefix}_{state}"


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _encode_casdoor_flow(*, state: str, return_to: str, admin: bool) -> str:
    payload = json.dumps(
        {
            "state": state,
            "returnTo": return_to,
            "admin": admin,
            "expiresAt": int(time.time()) + CASDOOR_FLOW_TTL_SECONDS,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(
        settings.session_secret.encode("utf-8"), payload, hashlib.sha256
    ).digest()
    return f"{_base64url_encode(payload)}.{_base64url_encode(signature)}"


def _decode_casdoor_flow(value: str | None, *, state: str, admin: bool) -> str:
    if not value:
        raise HTTPException(status_code=400, detail="Casdoor login state is missing or expired")
    try:
        payload_segment, signature_segment = value.split(".", 1)
        payload = _base64url_decode(payload_segment)
        signature = _base64url_decode(signature_segment)
        expected_signature = hmac.new(
            settings.session_secret.encode("utf-8"), payload, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("invalid signature")
        flow = json.loads(payload)
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="Invalid Casdoor login state") from error

    if (
        not isinstance(flow, dict)
        or flow.get("state") != state
        or flow.get("admin") is not admin
        or not isinstance(flow.get("expiresAt"), int)
        or flow["expiresAt"] < int(time.time())
        or not isinstance(flow.get("returnTo"), str)
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired Casdoor login state")
    return _normalize_return_to(flow["returnTo"], admin=admin)


def _normalize_return_to(value: str | None, *, admin: bool) -> str:
    fallback = "/" if admin else "/chat"
    if not value or len(value) > 2048:
        return fallback
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return fallback
    if parsed.path.startswith("/api"):
        return fallback
    return urlunsplit(("", "", parsed.path, parsed.query, ""))


def _append_query(url: str, key: str, value: str) -> str:
    parsed = urlsplit(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append((key, value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _embedded_casdoor_response(
    *,
    success: bool,
    top_level_return_to: str,
    message: str | None = None,
) -> HTMLResponse:
    nonce = secrets.token_urlsafe(18)
    payload = json.dumps(
        {
            "type": "cipher:casdoor-auth",
            "status": "success" if success else "error",
            "message": message,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    top_level_return_to_json = json.dumps(
        top_level_return_to,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    top_level_return_to_json = (
        top_level_return_to_json.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    title = "登录完成" if success else "登录未完成"
    response = HTMLResponse(
        "<!doctype html>"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{title}</title></head>"
        f'<body><p>{title}，正在返回 Cipher。</p><script nonce="{nonce}">'
        f"const payload={payload};"
        "if(window.top===window){"
        f"window.location.replace({top_level_return_to_json});"
        "}else{window.parent.postMessage(payload,window.location.origin);}"
        "</script></body></html>"
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; frame-ancestors 'self'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _finish_casdoor_flow(
    *,
    state: str,
    return_to: str,
    admin: bool,
    token: str | None = None,
    error: str | None = None,
) -> Response:
    if return_to == CASDOOR_EMBEDDED_RETURN_TO:
        if token is not None:
            top_level_return_to = _normalize_return_to(None, admin=admin)
        else:
            top_level_return_to = _append_query(
                "/",
                "casdoor_error",
                (error or "Casdoor login was cancelled")[:240],
            )
        response: Response = _embedded_casdoor_response(
            success=token is not None,
            top_level_return_to=top_level_return_to,
            message=error,
        )
    elif error is not None:
        error_return_to = return_to if admin else "/"
        response = RedirectResponse(
            _append_query(error_return_to, "casdoor_error", error[:240]),
            status_code=302,
        )
    else:
        response = RedirectResponse(return_to, status_code=302)

    if token is not None:
        set_session_cookie(response, token)
    _delete_casdoor_flow_cookie(response, state=state, admin=admin)
    return response


def _casdoor_redirect_uri(request: Request, *, admin: bool) -> str:
    configured = (
        settings.casdoor_admin_redirect_uri if admin else settings.casdoor_redirect_uri
    ).strip()
    if configured:
        return configured
    route_name = "casdoor_admin_callback" if admin else "casdoor_callback"
    return str(request.url_for(route_name))


def _set_casdoor_flow_cookie(
    response: Response, *, state: str, return_to: str, admin: bool
) -> None:
    response.set_cookie(
        key=_casdoor_flow_cookie_name(admin=admin, state=state),
        value=_encode_casdoor_flow(state=state, return_to=return_to, admin=admin),
        httponly=True,
        max_age=CASDOOR_FLOW_TTL_SECONDS,
        path="/api/auth/casdoor",
        samesite="lax",
        secure=settings.session_cookie_secure_enabled,
    )


def _delete_casdoor_flow_cookie(response: Response, *, state: str, admin: bool) -> None:
    response.delete_cookie(
        key=_casdoor_flow_cookie_name(admin=admin, state=state),
        path="/api/auth/casdoor",
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure_enabled,
    )


def _casdoor_config(*, include_management_url: bool) -> CasdoorAuthConfig:
    return CasdoorAuthConfig(
        enabled=settings.casdoor_auth_enabled,
        displayName=settings.casdoor_display_name.strip() or "Casdoor",
        managementUrl=(
            settings.casdoor_endpoint.rstrip("/") if include_management_url else ""
        ),
    )


def _require_local_auth_enabled() -> None:
    # Cipher is SSO-only. Keep the legacy endpoints as explicit tombstones so
    # old clients cannot silently fall back to a local account or shared
    # password when Casdoor is unavailable.
    raise HTTPException(status_code=404, detail="Local authentication is disabled")


def _start_casdoor_login(
    request: Request, *, return_to: str | None, theme: str | None, admin: bool
) -> RedirectResponse:
    if not settings.casdoor_auth_enabled:
        raise HTTPException(status_code=404, detail="Casdoor login is not enabled")
    normalized_return_to = _normalize_return_to(return_to, admin=admin)
    state = secrets.token_urlsafe(32)
    redirect_uri = _casdoor_redirect_uri(request, admin=admin)
    response = RedirectResponse(
        build_authorization_url(redirect_uri=redirect_uri, state=state, theme=theme),
        status_code=302,
    )
    _set_casdoor_flow_cookie(
        response, state=state, return_to=normalized_return_to, admin=admin
    )
    return response


async def _complete_casdoor_login(
    request: Request,
    *,
    code: str | None,
    state: str | None,
    oauth_error: str | None,
    oauth_error_description: str | None,
    admin: bool,
    db: Session,
) -> Response:
    if not settings.casdoor_auth_enabled:
        raise HTTPException(status_code=404, detail="Casdoor login is not enabled")
    if not state:
        raise HTTPException(status_code=400, detail="Casdoor login state is missing")

    return_to = _decode_casdoor_flow(
        request.cookies.get(_casdoor_flow_cookie_name(admin=admin, state=state)),
        state=state,
        admin=admin,
    )
    if oauth_error or not code:
        message = (oauth_error_description or oauth_error or "Casdoor login was cancelled")[:240]
        return _finish_casdoor_flow(
            state=state,
            return_to=return_to,
            admin=admin,
            error=message,
        )

    try:
        userinfo = await exchange_code_for_userinfo(
            code=code,
            redirect_uri=_casdoor_redirect_uri(request, admin=admin),
        )
        user = sync_casdoor_user(db, userinfo)
        sync_casdoor_tenancy(db, user, userinfo)
        try:
            await sync_user_commerce(db, user)
        except CasdoorAuthError:
            # Authentication must remain available during a temporary commerce
            # API outage. The last successfully synchronized tier is retained.
            pass
        if admin and not user.is_admin:
            db.commit()
            return _finish_casdoor_flow(
                state=state,
                return_to=return_to,
                admin=admin,
                error="该账号没有 Cipher 管理权限。",
            )
        token = create_session(db, user=user, request=request, commit=False)
        record_login_event(db, request, user, username=user.username, method="casdoor", outcome="success")
        db.commit()
    except CasdoorAccountError as error:
        db.rollback()
        return _finish_casdoor_flow(
            state=state,
            return_to=return_to,
            admin=admin,
            error=str(error)[:240],
        )
    except (CasdoorAuthError, IntegrityError):
        db.rollback()
        return _finish_casdoor_flow(
            state=state,
            return_to=return_to,
            admin=admin,
            error="Casdoor 登录失败，请重试。",
        )

    return _finish_casdoor_flow(
        state=state,
        return_to=return_to,
        admin=admin,
        token=token,
    )


@router.get("/casdoor/config", response_model=CasdoorAuthConfig)
def casdoor_config() -> CasdoorAuthConfig:
    return _casdoor_config(include_management_url=False)


@admin_router.get("/casdoor/config", response_model=CasdoorAuthConfig)
def casdoor_admin_config() -> CasdoorAuthConfig:
    return _casdoor_config(include_management_url=True)


@router.get("/casdoor/login", response_model=None)
def casdoor_login(
    request: Request,
    return_to: str | None = Query(default=None),
    theme: str | None = Query(default=None),
) -> Response:
    return _start_casdoor_login(request, return_to=return_to, theme=theme, admin=False)


@admin_router.get("/casdoor/login", response_model=None)
def casdoor_admin_login(
    request: Request,
    return_to: str | None = Query(default=None),
) -> Response:
    return _start_casdoor_login(request, return_to=return_to, theme=None, admin=True)


@router.get("/casdoor/callback", response_model=None, name="casdoor_callback")
async def casdoor_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    return await _complete_casdoor_login(
        request,
        code=code,
        state=state,
        oauth_error=error,
        oauth_error_description=error_description,
        admin=False,
        db=db,
    )


@admin_router.get(
    "/casdoor/callback", response_model=None, name="casdoor_admin_callback"
)
async def casdoor_admin_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    return await _complete_casdoor_login(
        request,
        code=code,
        state=state,
        oauth_error=error,
        oauth_error_description=error_description,
        admin=True,
        db=db,
    )


@router.post("/register", response_model=AuthSuccess, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSuccess:
    _require_local_auth_enabled()
    username_error = validate_registration_username(db, payload.username)
    if username_error is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=username_error,
        )

    password_error = validate_registration_password(payload.password)
    if password_error is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=password_error,
        )

    invite_code = get_invite_code_record(db, payload.inviteCode)
    if invite_code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite code is invalid",
        )

    prepared_avatar: bytes | None = None
    if payload.avatarDataUrl is not None:
        try:
            prepared_avatar = prepare_avatar(payload.avatarDataUrl)
        except AvatarValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error

    saved_avatar: str | None = None
    try:
        user = create_user_account(
            db,
            username=payload.username,
            password=payload.password,
            display_name=payload.displayName,
            commit=False,
        )
        if prepared_avatar is not None:
            saved_avatar = save_avatar(user.id, prepared_avatar)
            user.avatar_filename = saved_avatar
            db.add(user)
        consume_invite_code(db, invite_code, commit=False)
        token = create_session(db, user=user, commit=False)
        db.commit()
        db.refresh(user)
    except IntegrityError as error:
        db.rollback()
        delete_avatar(saved_avatar)
        if is_duplicate_username_error(error):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username is already taken",
            ) from error
        raise
    except Exception:
        db.rollback()
        delete_avatar(saved_avatar)
        raise

    set_session_cookie(response, token)
    return AuthSuccess(authenticated=True, user=serialize_user(user))


def login_impl(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session,
    *,
    allow_shared_password: bool,
) -> AuthSuccess:
    client_ip = get_client_ip(request)
    if is_rate_limited(client_ip):
        record_audit_event(db, event_type="auth.login", action="login", request=request,
                           actor_username=payload.username, outcome="blocked",
                           resource_type="session", detail={"reason": "rate_limited"})
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
        )

    if payload.username is None:
        if not allow_shared_password:
            record_failed_attempt(client_ip)
            record_audit_event(db, event_type="auth.login", action="login", request=request,
                               outcome="denied", resource_type="admin_session",
                               detail={"reason": "shared_password_not_allowed"})
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        if not verify_shared_password(payload.password):
            record_failed_attempt(client_ip)
            record_audit_event(db, event_type="auth.login", action="login", request=request,
                               outcome="denied", resource_type="session",
                               detail={"reason": "invalid_credentials"})
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password",
            )

        clear_failed_attempts(client_ip)
        token = create_session(db, request=request)
        record_audit_event(db, event_type="auth.login", action="login", request=request,
                           resource_type="session", detail={"method": "shared_password"})
        db.commit()
        set_session_cookie(response, token)
        return AuthSuccess(authenticated=True, user=None)

    user = authenticate_user(db, username=payload.username, password=payload.password)
    if user is None:
        record_failed_attempt(client_ip)
        record_audit_event(db, event_type="auth.login", action="login", request=request,
                           actor_username=payload.username, outcome="denied",
                           resource_type="session", detail={"reason": "invalid_credentials"})
        record_login_event(db, request, None, username=payload.username, method="local_password", outcome="failure")
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if user.totp_enabled:
        totp_valid = bool(payload.passcode and user.totp_secret and verify_totp(reveal_secret(user.totp_secret), payload.passcode))
        recovery_valid = bool(payload.recoveryCode and consume_recovery_code(db, user, payload.recoveryCode))
        if not (totp_valid or recovery_valid):
            record_login_event(db, request, user, username=user.username, method="local_mfa", outcome="failure")
            db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要有效的多因素验证码或恢复码。")

    clear_failed_attempts(client_ip)
    token = create_session(db, user=user, request=request)
    login_event = record_login_event(db, request, user, username=user.username, method="local_password", outcome="success")
    record_audit_event(db, event_type="auth.login", action="login", request=request,
                       actor_user_id=user.id, resource_type="session",
                       detail={"method": "local_password", "admin": user.is_admin, "suspicious": login_event.suspicious})
    db.commit()
    set_session_cookie(response, token)
    return AuthSuccess(authenticated=True, user=serialize_user(user))


@router.post("/login", response_model=AuthSuccess)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSuccess:
    _require_local_auth_enabled()
    return login_impl(payload, request, response, db, allow_shared_password=True)


@admin_router.post("/login", response_model=AuthSuccess)
def admin_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSuccess:
    _require_local_auth_enabled()
    return login_impl(payload, request, response, db, allow_shared_password=False)


def logout_impl(request: Request, response: Response, db: Session) -> SessionStatus:
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    delete_session(db, request.cookies.get(COOKIE_NAME))
    record_audit_event(db, event_type="auth.logout", action="logout", request=request,
                       actor_user_id=session.user_id if session is not None else None,
                       resource_type="session")
    db.commit()
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure_enabled,
    )
    return SessionStatus(authenticated=False, user=None)


@router.post("/logout", response_model=SessionStatus)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> SessionStatus:
    return logout_impl(request, response, db)


@admin_router.post("/logout", response_model=SessionStatus)
def admin_logout(request: Request, response: Response, db: Session = Depends(get_db)) -> SessionStatus:
    return logout_impl(request, response, db)


def session_status_impl(request: Request, db: Session) -> SessionStatus:
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    user = get_session_user(db, session)
    return SessionStatus(
        authenticated=session is not None,
        user=serialize_user(user) if user is not None else None,
    )


def admin_session_status_impl(request: Request, db: Session) -> SessionStatus:
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    user = get_session_user(db, session)
    return SessionStatus(
        authenticated=user is not None,
        user=serialize_user(user) if user is not None else None,
    )


@router.get("/session", response_model=SessionStatus)
def session_status(request: Request, db: Session = Depends(get_db)) -> SessionStatus:
    return session_status_impl(request, db)


@admin_router.get("/session", response_model=SessionStatus)
def admin_session_status(request: Request, db: Session = Depends(get_db)) -> SessionStatus:
    return admin_session_status_impl(request, db)
