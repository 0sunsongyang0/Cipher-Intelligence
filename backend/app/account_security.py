import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import PASSWORD_HASH_ITERATIONS, hash_password, verify_password
from app.config import settings
from app.models import AccountRecoveryCode, LoginEvent, Notification, Session as SessionModel, User, now_utc

REAUTH_WINDOW = timedelta(minutes=10)
RECOVERY_CODE_COUNT = 10


def _key() -> bytes:
    return hashlib.sha256((settings.session_secret + ":account-security").encode()).digest()


def protect_secret(secret: str) -> str:
    nonce = secrets.token_bytes(16)
    source = secret.encode()
    stream = b""
    counter = 0
    while len(stream) < len(source):
        stream += hmac.new(_key(), nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    ciphertext = bytes(left ^ right for left, right in zip(source, stream))
    tag = hmac.new(_key(), nonce + ciphertext, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + ciphertext + tag).decode()


def reveal_secret(value: str) -> str:
    raw = base64.urlsafe_b64decode(value.encode())
    nonce, ciphertext, tag = raw[:16], raw[16:-32], raw[-32:]
    if not hmac.compare_digest(tag, hmac.new(_key(), nonce + ciphertext, hashlib.sha256).digest()):
        raise ValueError("invalid protected secret")
    stream = b""
    counter = 0
    while len(stream) < len(ciphertext):
        stream += hmac.new(_key(), nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(left ^ right for left, right in zip(ciphertext, stream)).decode()


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def verify_totp(secret: str, passcode: str, *, now: int | None = None) -> bool:
    if len(passcode) != 6 or not passcode.isdigit():
        return False
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    timestamp = int(time.time() if now is None else now)
    for offset in (-1, 0, 1):
        counter = timestamp // 30 + offset
        digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
        position = digest[-1] & 15
        number = (struct.unpack(">I", digest[position:position + 4])[0] & 0x7fffffff) % 1_000_000
        if secrets.compare_digest(f"{number:06d}", passcode):
            return True
    return False


def hash_recovery_code(code: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.upper().encode(), salt.encode(), PASSWORD_HASH_ITERATIONS).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def rotate_recovery_codes(db: Session, user: User) -> list[str]:
    codes = [f"{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}" for _ in range(RECOVERY_CODE_COUNT)]
    db.execute(delete(AccountRecoveryCode).where(AccountRecoveryCode.user_id == user.id))
    db.add_all(AccountRecoveryCode(user_id=user.id, code_hash=hash_recovery_code(code)) for code in codes)
    return codes


def consume_recovery_code(db: Session, user: User, code: str) -> bool:
    rows = db.execute(select(AccountRecoveryCode).where(
        AccountRecoveryCode.user_id == user.id, AccountRecoveryCode.used_at.is_(None)
    )).scalars()
    for row in rows:
        try:
            valid = verify_password(code.upper(), row.code_hash)
        except (ValueError, TypeError):
            valid = False
        if valid:
            row.used_at = now_utc()
            db.add(row)
            return True
    return False


def verify_reauthentication(user: User, *, password: str | None, passcode: str | None) -> None:
    password_valid = False
    if password and user.auth_source in {"local", "hybrid"}:
        try:
            password_valid = verify_password(password, user.password_hash)
        except (ValueError, TypeError):
            pass
    totp_valid = bool(passcode and user.totp_enabled and user.totp_secret and verify_totp(reveal_secret(user.totp_secret), passcode))
    if not (password_valid or totp_valid):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="身份重新验证失败。")


def record_login_event(db: Session, request: Request, user: User | None, *, username: str | None, method: str, outcome: str) -> LoginEvent:
    ip = request.client.host[:64] if request.client else None
    previous_ips = set(db.execute(select(LoginEvent.ip_address).where(LoginEvent.user_id == user.id, LoginEvent.outcome == "success").limit(20)).scalars()) if user else set()
    suspicious = bool(user and previous_ips and ip not in previous_ips)
    event = LoginEvent(user_id=user.id if user else None, username=(user.username if user else username), method=method, outcome=outcome, suspicious=suspicious, ip_address=ip, user_agent=request.headers.get("user-agent", "")[:512])
    db.add(event)
    db.flush()
    if suspicious and user and user.suspicious_login_alerts:
        db.add(Notification(
            user_id=user.id,
            organization_id=None,
            notification_type="security_login",
            title="检测到新的登录位置",
            body="如果这不是你的操作，请立即在账号安全页退出所有设备并修改密码。",
            resource_type="login_event",
            resource_id=str(event.id),
            resource_url="/account",
            idempotency_key=f"security-login-{event.id}",
        ))
    return event


def set_local_password(user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.auth_source = "hybrid" if user.casdoor_subject else "local"
