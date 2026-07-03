from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

WINDOW = timedelta(minutes=5)
MAX_FAILURES = 5

_failed_attempts: dict[str, deque[datetime]] = defaultdict(deque)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _prune(ip_address: str, now: datetime) -> deque[datetime]:
    attempts = _failed_attempts[ip_address]
    cutoff = now - WINDOW
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    if not attempts:
        _failed_attempts.pop(ip_address, None)
    return attempts


def is_rate_limited(ip_address: str, now: datetime | None = None) -> bool:
    if not ip_address:
        return False

    current_time = now or _now_utc()
    attempts = _prune(ip_address, current_time)
    return len(attempts) >= MAX_FAILURES


def record_failed_attempt(ip_address: str, now: datetime | None = None) -> None:
    if not ip_address:
        return

    current_time = now or _now_utc()
    attempts = _prune(ip_address, current_time)
    attempts.append(current_time)
    _failed_attempts[ip_address] = attempts


def clear_failed_attempts(ip_address: str) -> None:
    if ip_address:
        _failed_attempts.pop(ip_address, None)


def reset_failed_attempts() -> None:
    _failed_attempts.clear()
