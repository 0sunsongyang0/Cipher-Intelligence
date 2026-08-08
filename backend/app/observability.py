from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.models import ObservabilityEvent

logger = logging.getLogger("cipher.observability")
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
SENSITIVE_KEYS = {
    "password",
    "passwd",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "set-cookie",
    "secret",
    "client_secret",
    "api_key",
    "apikey",
}


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]" if str(k).lower() in SENSITIVE_KEYS else scrub(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value[:20]]
    if isinstance(value, str):
        return value[:256]
    return value


def emit_event(db, *, event_name: str, request_id: str | None = None, user_id: int | None = None,
               organization_id: int | None = None, route: str | None = None, model_id: str | None = None,
               task_id: str | None = None, duration_ms: float | None = None, input_tokens: int = 0,
               output_tokens: int = 0, error_type: str | None = None, status_code: int | None = None,
               metadata: dict[str, Any] | None = None) -> ObservabilityEvent:
    payload = {"event_name": event_name, "request_id": request_id or request_id_var.get(), "user_id": user_id,
               "organization_id": organization_id, "route": route, "model_id": model_id, "task_id": task_id,
               "duration_ms": duration_ms, "input_tokens": input_tokens, "output_tokens": output_tokens,
               "error_type": error_type, "status_code": status_code, **scrub(metadata or {})}
    logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    item = ObservabilityEvent(event_name=event_name, request_id=payload["request_id"], user_id=user_id,
        organization_id=organization_id, route=route, model_id=model_id, task_id=task_id,
        duration_ms=duration_ms, input_tokens=max(0, int(input_tokens or 0)), output_tokens=max(0, int(output_tokens or 0)),
        error_type=error_type, status_code=status_code, metadata_json=json.dumps(scrub(metadata or {}), ensure_ascii=False))
    db.add(item)
    return item


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        error_type = None
        response = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            duration = round((time.perf_counter() - started) * 1000, 2)
            if response is not None:
                response.headers["x-request-id"] = request_id
            # Persistence is intentionally best-effort; request handling must not fail on telemetry.
            try:
                from app.database import SessionLocal
                with SessionLocal() as db:
                    emit_event(db, event_name="http.request", request_id=request_id, route=request.url.path,
                               user_id=getattr(request.state, "user_id", None),
                               organization_id=getattr(request.state, "organization_id", None),
                               duration_ms=duration, error_type=error_type, status_code=status_code)
                    db.commit()
            except Exception:
                logger.exception("observability_persist_failed")
            request_id_var.reset(token)
