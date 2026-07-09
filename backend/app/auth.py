import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import InviteCode
from app.models import Session as SessionModel
from app.models import User
from app.models import now_utc
from app.schemas import UserPayload

COOKIE_NAME = "campus_session"
SESSION_TTL = timedelta(days=7)
PASSWORD_HASH_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 8


def hash_token(token: str) -> str:
    return hashlib.sha256(f"{settings.session_secret}:{token}".encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    algorithm, iterations, salt, expected_digest = password_hash.split("$", 3)
    if algorithm != "pbkdf2_sha256":
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    ).hex()
    return secrets.compare_digest(actual_digest, expected_digest)


def verify_shared_password(password: str) -> bool:
    return secrets.compare_digest(password, settings.app_access_password)


def get_client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else ""


def create_session(db: Session, user: User | None = None, *, commit: bool = True) -> str:
    token = secrets.token_urlsafe(32)
    session = SessionModel(
        user_id=user.id if user is not None else None,
        token_hash=hash_token(token),
        expires_at=now_utc() + SESSION_TTL,
    )
    db.add(session)
    if commit:
        db.commit()
        db.refresh(session)
    else:
        db.flush()
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


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.execute(select(User).where(User.username == username)).scalar_one_or_none()


def validate_registration_username(db: Session, username: str) -> str | None:
    if get_user_by_username(db, username) is not None:
        return "Username is already taken"
    return None


def validate_registration_password(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return "Password must be at least 8 characters and include letters and numbers"
    if not any(character.isalpha() for character in password):
        return "Password must be at least 8 characters and include letters and numbers"
    if not any(character.isdigit() for character in password):
        return "Password must be at least 8 characters and include letters and numbers"
    return None


def create_user_account(
    db: Session, *, username: str, password: str, commit: bool = True
) -> User:
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    if commit:
        db.commit()
        db.refresh(user)
    return user


def authenticate_user(db: Session, *, username: str, password: str) -> User | None:
    user = get_user_by_username(db, username)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_invite_code_record(db: Session, code: str) -> InviteCode | None:
    invite_code = db.execute(select(InviteCode).where(InviteCode.code == code)).scalar_one_or_none()
    if invite_code is None or not invite_code.is_active:
        return None
    if invite_code.expires_at is not None and _coerce_utc(invite_code.expires_at) <= now_utc():
        return None
    if invite_code.max_uses is not None and invite_code.used_count >= invite_code.max_uses:
        return None
    return invite_code


def consume_invite_code(db: Session, invite_code: InviteCode, *, commit: bool = True) -> InviteCode:
    invite_code.used_count += 1
    db.add(invite_code)
    if commit:
        db.commit()
        db.refresh(invite_code)
    return invite_code


def is_duplicate_username_error(error: IntegrityError) -> bool:
    return "users.username" in str(error.orig)


def get_session_user(db: Session, session: SessionModel | None) -> User | None:
    if session is None or session.user_id is None:
        return None
    return db.execute(select(User).where(User.id == session.user_id)).scalar_one_or_none()


def serialize_user(user: User) -> UserPayload:
    return UserPayload(id=user.id, username=user.username, isAdmin=user.is_admin)


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


def require_user_session(
    request: Request,
    db: Session = Depends(get_db),
) -> SessionModel:
    session = require_session(request, db)
    if session.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User authentication required",
        )
    return session


def require_admin_user_session(
    request: Request,
    db: Session = Depends(get_db),
) -> SessionModel:
    session = require_user_session(request, db)
    user = get_session_user(db, session)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User authentication required",
        )
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return session
