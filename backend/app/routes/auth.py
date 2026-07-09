from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from app.database import get_db
from app.rate_limit import clear_failed_attempts, is_rate_limited, record_failed_attempt
from app.schemas import AuthSuccess, LoginRequest, RegisterRequest, SessionStatus

router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/auth", tags=["auth"])


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=int(SESSION_TTL.total_seconds()),
        samesite="lax",
        secure=settings.session_cookie_secure_enabled,
    )


@router.post("/register", response_model=AuthSuccess, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSuccess:
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

    try:
        user = create_user_account(
            db,
            username=payload.username,
            password=payload.password,
            commit=False,
        )
        consume_invite_code(db, invite_code, commit=False)
        token = create_session(db, user=user, commit=False)
        db.commit()
        db.refresh(user)
    except IntegrityError as error:
        db.rollback()
        if is_duplicate_username_error(error):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username is already taken",
            ) from error
        raise
    except Exception:
        db.rollback()
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
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
        )

    if payload.username is None:
        if not allow_shared_password:
            record_failed_attempt(client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        if not verify_shared_password(payload.password):
            record_failed_attempt(client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password",
            )

        clear_failed_attempts(client_ip)
        token = create_session(db)
        set_session_cookie(response, token)
        return AuthSuccess(authenticated=True, user=None)

    user = authenticate_user(db, username=payload.username, password=payload.password)
    if user is None:
        record_failed_attempt(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    clear_failed_attempts(client_ip)
    token = create_session(db, user=user)
    set_session_cookie(response, token)
    return AuthSuccess(authenticated=True, user=serialize_user(user))


@router.post("/login", response_model=AuthSuccess)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSuccess:
    return login_impl(payload, request, response, db, allow_shared_password=True)


@admin_router.post("/login", response_model=AuthSuccess)
def admin_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSuccess:
    return login_impl(payload, request, response, db, allow_shared_password=False)


def logout_impl(request: Request, response: Response, db: Session) -> SessionStatus:
    delete_session(db, request.cookies.get(COOKIE_NAME))
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
