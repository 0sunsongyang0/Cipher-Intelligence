import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Session as SessionModel
from app.models import now_utc

COOKIE_NAME = "campus_session"
SESSION_TTL = timedelta(days=7)


def hash_token(token: str) -> str:
    return hashlib.sha256(f"{settings.session_secret}:{token}".encode("utf-8")).hexdigest()


def verify_password(password: str) -> bool:
    return secrets.compare_digest(password, settings.app_access_password)


def get_client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else ""


def create_session(db: Session) -> str:
    token = secrets.token_urlsafe(32)
    session = SessionModel(
        token_hash=hash_token(token),
        expires_at=now_utc() + SESSION_TTL,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return token


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def get_session_record(db: Session, token: str | None) -> SessionModel | None:
    if not token:
        return None

    session = db.execute(
        select(SessionModel).where(SessionModel.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if session is None:
        return None

    if _coerce_utc(session.expires_at) <= now_utc():
        db.delete(session)
        db.commit()
        return None

    return session


def delete_session(db: Session, token: str | None) -> None:
    session = get_session_record(db, token)
    if session is not None:
        db.delete(session)
        db.commit()


def require_session(
    request: Request,
    db: Session = Depends(get_db),
) -> SessionModel:
    session = get_session_record(db, request.cookies.get(COOKIE_NAME))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return session
