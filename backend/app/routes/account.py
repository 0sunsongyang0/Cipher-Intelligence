import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import delete, update, select, func

from app.account_profiles import (
    AvatarValidationError,
    delete_avatar,
    prepare_avatar,
    resolve_avatar,
    save_avatar,
)
from app.auth import COOKIE_NAME, get_session_user, hash_token, require_user_session, serialize_user, validate_registration_password
from app.account_security import generate_totp_secret, protect_secret, rotate_recovery_codes, set_local_password, verify_reauthentication, verify_totp
from app.casdoor_auth import (
    CASDOOR_PROVIDER_LABELS,
    CasdoorAuthError,
    apply_casdoor_profile,
    fetch_casdoor_user,
    initiate_casdoor_totp,
    get_casdoor_link_providers,
    enable_casdoor_totp,
    delete_casdoor_mfa,
    send_casdoor_email_verification,
    update_casdoor_profile,
    verify_casdoor_email,
)
from app.config import settings
from app.database import get_db
from app.models import User, Conversation, InvestigationCase, Session as SessionRow, UsageLedgerEntry, OrganizationMember, WorkspaceMember, CaseAccess, CaseFollower, CaseComment, Notification, AuditLog, AccountRecoveryCode, LoginEvent
from app.models import Session as SessionModel
from app.schemas import (
    AccountIdentityPayload,
    AccountEmailVerificationResponse,
    AccountEmailCodeRequest,
    AccountMfaConfirmRequest,
    AccountMfaSetupPayload,
    AccountProviderListPayload,
    AccountProviderPayload,
    AccountOverview,
    AccountUpdateRequest,
    ConnectedAccountPayload,
    AccountSecurityOverview, PasswordChangeRequest, ReauthenticationRequest,
    TotpSetupRequest, LocalTotpConfirmRequest, RecoveryCodePayload,
    SessionItemPayload, LoginEventPayload, SecurityAlertUpdate,
)


router = APIRouter(prefix="/api/account", tags=["account"])


def _require_sensitive_reauth(user: User, session: SessionModel, payload: ReauthenticationRequest) -> None:
    if user.auth_source == "casdoor" and not user.totp_enabled:
        created_at = session.created_at
        if created_at.tzinfo is None:
            from datetime import timezone
            created_at = created_at.replace(tzinfo=timezone.utc)
        from datetime import timedelta
        from app.models import now_utc
        if now_utc() - created_at <= timedelta(minutes=10):
            return
        raise HTTPException(status_code=401, detail="请先通过 Casdoor 重新登录，再执行此敏感操作。")
    verify_reauthentication(user, password=payload.password, passcode=payload.passcode)


def _security_overview(db: Session, user: User) -> AccountSecurityOverview:
    remaining = db.scalar(select(func.count()).select_from(AccountRecoveryCode).where(
        AccountRecoveryCode.user_id == user.id, AccountRecoveryCode.used_at.is_(None)
    )) or 0
    return AccountSecurityOverview(
        authSource=user.auth_source,
        localPasswordEnabled=user.auth_source in {"local", "hybrid"},
        totpEnabled=user.totp_enabled,
        recoveryCodesRemaining=remaining,
        suspiciousLoginAlerts=user.suspicious_login_alerts,
    )


def _display_ip(value: str | None) -> str | None:
    if not value:
        return None
    if ":" in value:
        return value.split(":", 2)[0] + ":…"
    parts = value.split(".")
    return ".".join(parts[:3] + ["x"]) if len(parts) == 4 else "已记录"


@router.get("/security", response_model=AccountSecurityOverview)
def get_security_overview(session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    return _security_overview(db, _get_account_user(db, session))


@router.put("/security/password", response_model=AccountSecurityOverview)
def change_password(payload: PasswordChangeRequest, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    user = _get_account_user(db, session)
    _require_sensitive_reauth(user, session, payload)
    password_error = validate_registration_password(payload.newPassword)
    if password_error:
        raise HTTPException(status_code=400, detail="新密码至少 8 位，并同时包含字母和数字。")
    set_local_password(user, payload.newPassword)
    db.execute(delete(SessionRow).where(SessionRow.user_id == user.id, SessionRow.id != session.id))
    db.commit()
    return _security_overview(db, user)


@router.post("/security/totp/setup")
def setup_local_totp(payload: TotpSetupRequest, response: Response, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    user = _get_account_user(db, session)
    _require_sensitive_reauth(user, session, payload)
    secret = generate_totp_secret()
    response.headers["Cache-Control"] = "no-store"
    label = quote(user.email or user.username, safe="")
    issuer = quote("Cipher", safe="")
    return {"secret": secret, "otpauthUri": f"otpauth://totp/{issuer}:{label}?secret={secret}&issuer={issuer}"}


@router.post("/security/totp/confirm", response_model=RecoveryCodePayload)
def confirm_local_totp(payload: LocalTotpConfirmRequest, response: Response, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    user = _get_account_user(db, session)
    _require_sensitive_reauth(user, session, payload)
    if not verify_totp(payload.secret, payload.confirmationCode):
        raise HTTPException(status_code=400, detail="验证码无效，TOTP 尚未启用。")
    user.totp_secret = protect_secret(payload.secret)
    user.totp_enabled = True
    codes = rotate_recovery_codes(db, user)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return RecoveryCodePayload(codes=codes)


@router.post("/security/recovery-codes", response_model=RecoveryCodePayload)
def rotate_codes(payload: ReauthenticationRequest, response: Response, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    user = _get_account_user(db, session)
    _require_sensitive_reauth(user, session, payload)
    codes = rotate_recovery_codes(db, user)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return RecoveryCodePayload(codes=codes)


@router.get("/security/sessions", response_model=list[SessionItemPayload])
def list_sessions(request: Request, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    rows = db.execute(select(SessionRow).where(SessionRow.user_id == session.user_id).order_by(SessionRow.created_at.desc())).scalars()
    return [SessionItemPayload(id=row.id, current=row.id == session.id, ipAddress=_display_ip(row.ip_address), userAgent=row.user_agent, createdAt=row.created_at, lastSeenAt=row.last_seen_at) for row in rows]


@router.delete("/security/sessions/{session_id}", status_code=204)
def revoke_session(session_id: int, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    db.execute(delete(SessionRow).where(SessionRow.id == session_id, SessionRow.user_id == session.user_id, SessionRow.id != session.id))
    db.commit()


@router.post("/security/sessions/revoke-all")
def revoke_all_sessions(payload: ReauthenticationRequest, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    user = _get_account_user(db, session)
    _require_sensitive_reauth(user, session, payload)
    result = db.execute(delete(SessionRow).where(SessionRow.user_id == user.id, SessionRow.id != session.id))
    db.commit()
    return {"revoked": result.rowcount or 0}


@router.get("/security/login-history", response_model=list[LoginEventPayload])
def login_history(session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    rows = db.execute(select(LoginEvent).where(LoginEvent.user_id == session.user_id).order_by(LoginEvent.created_at.desc()).limit(50)).scalars()
    return [LoginEventPayload(id=row.id, method=row.method, outcome=row.outcome, suspicious=row.suspicious, ipAddress=_display_ip(row.ip_address), userAgent=row.user_agent, createdAt=row.created_at) for row in rows]


@router.put("/security/alerts", response_model=AccountSecurityOverview)
def update_security_alerts(payload: SecurityAlertUpdate, session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    user = _get_account_user(db, session)
    user.suspicious_login_alerts = payload.enabled
    db.commit()
    return _security_overview(db, user)

@router.delete("", status_code=204)
def delete_account(session: SessionModel = Depends(require_user_session), db: Session = Depends(get_db)):
    user = db.get(User, session.user_id)
    if user is None: return
    avatar_filename = user.avatar_filename
    # Content is user-owned and is deleted immediately; billing/audit rows are
    # retained only in aggregate or with the actor foreign key nulled.
    for model, column in ((Conversation, Conversation.owner_user_id), (InvestigationCase, InvestigationCase.owner_user_id), (UsageLedgerEntry, UsageLedgerEntry.user_id), (OrganizationMember, OrganizationMember.user_id), (WorkspaceMember, WorkspaceMember.user_id), (CaseAccess, CaseAccess.user_id), (CaseFollower, CaseFollower.user_id), (CaseComment, CaseComment.author_user_id), (Notification, Notification.user_id)):
        db.execute(delete(model).where(column == user.id))
    db.execute(delete(SessionRow).where(SessionRow.user_id == user.id))
    db.execute(update(AuditLog).where(AuditLog.actor_user_id == user.id).values(actor_user_id=None, actor_username="deleted-user", actor_ip=None, user_agent=None))
    from app.retention import rehash_audit_chain
    rehash_audit_chain(db)
    db.delete(user); db.commit(); delete_avatar(avatar_filename)


def _get_account_user(db: Session, session: SessionModel) -> User:
    user = get_session_user(db, session)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User authentication required",
        )
    return user


def _connected_accounts(user: User) -> list[ConnectedAccountPayload]:
    try:
        values = json.loads(user.casdoor_providers_json or "[]")
    except (json.JSONDecodeError, TypeError):
        values = []
    provider_ids = {value for value in values if isinstance(value, str)}
    return [
        ConnectedAccountPayload(provider=provider, label=label)
        for provider, label in CASDOOR_PROVIDER_LABELS
        if provider in provider_ids
    ]


def _account_overview(user: User, *, sync_status: str) -> AccountOverview:
    casdoor_account = user.casdoor_subject is not None
    sync_available = casdoor_account and settings.casdoor_auth_enabled
    management_url = (
        f"{settings.casdoor_endpoint.rstrip('/')}/account"
        if sync_available and settings.casdoor_endpoint.strip()
        else ""
    )
    return AccountOverview(
        user=serialize_user(user),
        workspaceAvatarUrl=(
            f"/api/account/avatars/{user.avatar_filename}"
            if user.avatar_filename
            else None
        ),
        identityAvatarUrl=user.casdoor_avatar_url,
        identity=AccountIdentityPayload(
            source="casdoor" if casdoor_account else "local",
            providerName=(
                settings.casdoor_display_name.strip() or "Casdoor"
                if casdoor_account
                else "Cipher"
            ),
            email=user.email,
            emailVerified=user.email_verified,
            connectedAccounts=_connected_accounts(user),
            mfaEnabled=user.casdoor_mfa_enabled,
            passwordEnabled=user.casdoor_password_enabled,
            lastSignInAt=user.casdoor_last_signin_at,
            lastSyncedAt=user.casdoor_last_synced_at,
            syncStatus=sync_status,
            syncAvailable=sync_available,
            managementUrl=management_url,
        ),
    )


def _casdoor_account_id(user: User) -> str:
    casdoor_name = user.casdoor_name or user.username
    organization = settings.casdoor_organization_name.strip() or "cipher"
    return f"{organization}/{casdoor_name}"


def _require_casdoor_account(user: User) -> str:
    if user.casdoor_subject is None or not settings.casdoor_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前账号无法使用 Cipher SSO 安全设置。",
        )
    return _casdoor_account_id(user)


async def _sync_casdoor_account(user: User, db: Session) -> None:
    if user.casdoor_subject is None:
        return
    userinfo = await fetch_casdoor_user(_casdoor_account_id(user))
    apply_casdoor_profile(user, userinfo)
    db.add(user)
    db.commit()
    db.refresh(user)


@router.get("", response_model=AccountOverview)
async def get_account_overview(
    session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> AccountOverview:
    user = _get_account_user(db, session)
    sync_status = "local"
    if user.casdoor_subject is not None:
        sync_status = "stale"
        if settings.casdoor_auth_enabled:
            try:
                await _sync_casdoor_account(user, db)
                sync_status = "current"
            except CasdoorAuthError:
                db.rollback()
    return _account_overview(user, sync_status=sync_status)


@router.post("/sync", response_model=AccountOverview)
async def sync_account(
    session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> AccountOverview:
    user = _get_account_user(db, session)
    if user.casdoor_subject is None:
        return _account_overview(user, sync_status="local")
    try:
        await _sync_casdoor_account(user, db)
    except CasdoorAuthError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Casdoor 资料同步失败，请稍后重试。",
        ) from error
    return _account_overview(user, sync_status="current")


@router.post("/email-verification", response_model=AccountEmailVerificationResponse)
async def send_email_verification(
    session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> AccountEmailVerificationResponse:
    user = _get_account_user(db, session)
    if user.casdoor_subject is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前账号不由 Cipher SSO 管理。",
        )
    if not settings.casdoor_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cipher SSO 暂未启用。",
        )
    if not user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前账号还没有邮箱。",
        )
    if user.email_verified:
        return AccountEmailVerificationResponse(
            email=user.email,
            sent=False,
            message="邮箱已经验证。",
        )

    try:
        await send_casdoor_email_verification(_casdoor_account_id(user), user.email)
    except CasdoorAuthError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="验证邮件发送失败，请稍后重试。",
        ) from error
    return AccountEmailVerificationResponse(
        email=user.email,
        sent=True,
        message="验证邮件已发送，请查看邮箱。",
    )


@router.post("/email-verification/confirm", response_model=AccountOverview)
async def confirm_email_verification(
    payload: AccountEmailCodeRequest,
    session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> AccountOverview:
    user = _get_account_user(db, session)
    if user.casdoor_subject is None or not user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前账号没有可验证的 Cipher SSO 邮箱。",
        )
    if user.email_verified:
        return _account_overview(user, sync_status="current")

    try:
        userinfo = await verify_casdoor_email(
            _casdoor_account_id(user), user.email, payload.code
        )
        apply_casdoor_profile(user, userinfo)
        db.add(user)
        db.commit()
        db.refresh(user)
    except CasdoorAuthError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码无效或已过期，请重新获取。",
        ) from error
    return _account_overview(user, sync_status="current")


@router.post("/mfa/totp/setup", response_model=AccountMfaSetupPayload)
async def setup_totp(
    response: Response,
    session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> AccountMfaSetupPayload:
    user = _get_account_user(db, session)
    account_id = _require_casdoor_account(user)
    try:
        setup = await initiate_casdoor_totp(account_id)
    except CasdoorAuthError as error:
        raise HTTPException(status_code=502, detail="无法创建身份验证器，请稍后重试。") from error
    label = quote(user.email or user.casdoor_name or user.username, safe="")
    issuer = quote(settings.casdoor_display_name.strip() or "Cipher", safe="")
    response.headers["Cache-Control"] = "no-store"
    return AccountMfaSetupPayload(
        secret=setup["secret"],
        recoveryCode=setup["recoveryCode"],
        otpauthUri=f"otpauth://totp/{issuer}:{label}?secret={quote(setup['secret'], safe='')}&issuer={issuer}",
    )


@router.get("/providers", response_model=AccountProviderListPayload)
async def list_account_providers(
    session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> AccountProviderListPayload:
    user = _get_account_user(db, session)
    _require_casdoor_account(user)
    try:
        configured = await get_casdoor_link_providers()
    except CasdoorAuthError as error:
        raise HTTPException(status_code=502, detail="无法读取第三方账号配置。") from error
    connected = {item.provider for item in _connected_accounts(user)}
    return AccountProviderListPayload(items=[
        AccountProviderPayload(
            provider=item["provider"],
            label=item["label"],
            connected=(item["provider"] in connected or (
                item["provider"] == "azuread" and "microsoftonline" in connected
            )),
            authorizationUrl=None if item["provider"] in connected else item["authorizationUrl"],
        ) for item in configured
    ])


@router.post("/mfa/totp/confirm", response_model=AccountOverview)
async def confirm_totp(
    payload: AccountMfaConfirmRequest,
    session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> AccountOverview:
    user = _get_account_user(db, session)
    account_id = _require_casdoor_account(user)
    try:
        await enable_casdoor_totp(
            account_id,
            secret=payload.secret,
            recovery_code=payload.recoveryCode,
            passcode=payload.passcode,
        )
        await _sync_casdoor_account(user, db)
    except CasdoorAuthError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail="验证码无效，身份验证器尚未启用。") from error
    return _account_overview(user, sync_status="current")


@router.delete("/mfa", response_model=AccountOverview)
async def remove_mfa(
    session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> AccountOverview:
    user = _get_account_user(db, session)
    account_id = _require_casdoor_account(user)
    try:
        await delete_casdoor_mfa(account_id)
        await _sync_casdoor_account(user, db)
    except CasdoorAuthError as error:
        db.rollback()
        raise HTTPException(status_code=502, detail="无法重置多因素认证，请稍后重试。") from error
    return _account_overview(user, sync_status="current")


@router.patch("/profile", response_model=AccountOverview)
async def update_profile(
    payload: AccountUpdateRequest,
    session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> AccountOverview:
    user = _get_account_user(db, session)

    fields = payload.model_fields_set
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No profile changes were provided",
        )
    if "displayName" in fields and payload.displayName is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Display name cannot be blank",
        )
    if "email" in fields and payload.email is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email cannot be blank",
        )
    if payload.avatarDataUrl is not None and payload.removeAvatar:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose either a new avatar or remove the current avatar",
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

    previous_avatar = user.avatar_filename
    new_avatar: str | None = None
    try:
        upstream_fields = fields.intersection({"displayName", "email"})
        if upstream_fields and user.casdoor_subject is not None:
            try:
                userinfo = await update_casdoor_profile(
                    _casdoor_account_id(user),
                    display_name=(payload.displayName if "displayName" in fields else None),
                    email=(payload.email if "email" in fields else None),
                )
            except CasdoorAuthError as error:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Casdoor 暂时无法更新账号资料，本次更改未保存。",
                ) from error
            apply_casdoor_profile(user, userinfo)

        if "displayName" in fields:
            user.display_name = payload.displayName
        if "email" in fields and user.casdoor_subject is None:
            user.email = payload.email
            user.email_verified = False

        if prepared_avatar is not None:
            new_avatar = save_avatar(user.id, prepared_avatar)
            user.avatar_filename = new_avatar
        elif payload.removeAvatar:
            user.avatar_filename = None

        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        delete_avatar(new_avatar)
        raise

    if previous_avatar != user.avatar_filename:
        delete_avatar(previous_avatar)

    return _account_overview(
        user,
        sync_status=("current" if user.casdoor_subject is not None else "local"),
    )


@router.get("/avatars/{filename}", response_model=None)
def get_avatar(filename: str) -> FileResponse:
    path = resolve_avatar(filename)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
