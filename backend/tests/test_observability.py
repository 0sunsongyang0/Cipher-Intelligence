import json

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ObservabilityEvent, Session as SessionModel
from app.observability import emit_event, scrub
from app.routes.admin import get_admin_observability


def test_scrub_redacts_sensitive_fields() -> None:
    payload = scrub({
        "password": "secret",
        "nested": {"authorization": "Bearer abc", "note": "ok"},
        "long": "x" * 300,
    })

    assert payload["password"] == "[REDACTED]"
    assert payload["nested"]["authorization"] == "[REDACTED]"
    assert payload["nested"]["note"] == "ok"
    assert payload["long"] == "x" * 256


def test_emit_event_persists_unified_fields(client) -> None:
    with SessionLocal() as db:
        emit_event(
            db,
            event_name="model.call",
            request_id="req-1",
            user_id=7,
            organization_id=11,
            route="/api/chat",
            model_id="deepseek-v4-pro",
            task_id="metric-1",
            duration_ms=123.4,
            input_tokens=10,
            output_tokens=20,
            status_code=200,
            metadata={"token": "hidden", "provider": "deepseek"},
        )
        db.commit()

        item = db.scalar(select(ObservabilityEvent).where(ObservabilityEvent.request_id == "req-1"))

    assert item is not None
    assert item.user_id == 7
    assert item.organization_id == 11
    assert item.route == "/api/chat"
    assert item.model_id == "deepseek-v4-pro"
    assert item.input_tokens == 10
    assert item.output_tokens == 20
    assert json.loads(item.metadata_json)["token"] == "[REDACTED]"


def test_admin_observability_aggregates_core_metrics(client) -> None:
    with SessionLocal() as db:
        db.add_all([
            ObservabilityEvent(event_name="http.request", user_id=1, route="/api/chat", duration_ms=100, status_code=200),
            ObservabilityEvent(event_name="http.request", user_id=2, route="/api/chat", duration_ms=300, status_code=500),
            ObservabilityEvent(event_name="model.call", user_id=1, model_id="m1", duration_ms=250, input_tokens=12, output_tokens=8, status_code=200),
            ObservabilityEvent(event_name="model.call", user_id=2, model_id="m2", duration_ms=400, input_tokens=5, output_tokens=7, error_type="UpstreamError", status_code=502),
            ObservabilityEvent(event_name="cape.task", user_id=1, task_id="42", duration_ms=900, status_code=200),
        ])
        db.commit()

        payload = get_admin_observability(days=30, db=db, _session=SessionModel(user_id=1))

    assert payload.requestSuccessRate == 50
    assert payload.averageResponseTimeMs == 200
    assert payload.modelFailureRate == 50
    assert payload.tokenUsage == {"input": 17, "output": 15, "total": 32}
    assert payload.capeTaskAverageDurationMs == 900
    assert payload.activeUsers == 2
    assert payload.events == 5


def test_admin_observability_requires_admin_session(client) -> None:
    response = client.get("/api/admin/observability")

    assert response.status_code == 401
