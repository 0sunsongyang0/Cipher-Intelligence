from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE_NAME,
    SESSION_TTL,
    create_session,
    delete_session,
    get_client_ip,
    get_session_record,
    verify_password,
)
from app.database import get_db
from app.rate_limit import clear_failed_attempts, is_rate_limited, record_failed_attempt
from app.schemas import AuthSuccess, LoginRequest, SessionStatus

router = APIRouter(prefix="/api/auth", tags=["auth"])


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

    if not verify_password(payload.password):
        record_failed_attempt(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    clear_failed_attempts(client_ip)
    token = create_session(db)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=int(SESSION_TTL.total_seconds()),
        samesite="lax",
    )
    return AuthSuccess(authenticated=True)


@router.post("/logout", response_model=SessionStatus)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> SessionStatus:
    delete_session(db, request.cookies.get(COOKIE_NAME))
    response.delete_cookie(key=COOKIE_NAME, httponly=True, samesite="lax")
    return SessionStatus(authenticated=False)


@router.get("/session", response_model=SessionStatus)
def session_status(request: Request, db: Session = Depends(get_db)) -> SessionStatus:
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    return SessionStatus(authenticated=session is not None)
