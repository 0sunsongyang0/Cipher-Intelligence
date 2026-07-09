from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
    serialize_user,
)
from app.config import settings
from app.database import get_db
from app.rate_limit import clear_failed_attempts, is_rate_limited, record_failed_attempt
from app.schemas import AuthSuccess, LoginRequest, RegisterRequest, SessionStatus

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
    invite_code = get_invite_code_record(db, payload.inviteCode)
    if invite_code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite code is invalid",
        )

    user = create_user_account(db, username=payload.username, password=payload.password)
    consume_invite_code(db, invite_code)
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
    client_ip = get_client_ip(request)
    if is_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
        )

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


@router.post("/logout", response_model=SessionStatus)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> SessionStatus:
    delete_session(db, request.cookies.get(COOKIE_NAME))
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure_enabled,
    )
    return SessionStatus(authenticated=False, user=None)


@router.get("/session", response_model=SessionStatus)
def session_status(request: Request, db: Session = Depends(get_db)) -> SessionStatus:
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    user = get_session_user(db, session)
    return SessionStatus(
        authenticated=session is not None,
        user=serialize_user(user) if user is not None else None,
    )
