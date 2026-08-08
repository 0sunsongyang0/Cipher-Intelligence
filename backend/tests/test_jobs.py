from __future__ import annotations

import asyncio
import gc
import os
from pathlib import Path
import sys
import time

import pytest
from fastapi.testclient import TestClient
TEST_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./backend/data/test.db")
TEST_DATABASE_PATH = Path(TEST_DATABASE_URL.removeprefix("sqlite:///"))

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password
from app.database import init_db
from app.database import SessionLocal
from app.database import engine
from app.jobs import JobContext, JobRunner, register_job_handler
from app.main import app
from app.models import Job, User, now_utc


def _unlink_with_retry(path: Path) -> None:
    for _ in range(20):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            gc.collect()
            time.sleep(0.05)

    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


def reset_test_database() -> None:
    engine.dispose()
    _unlink_with_retry(TEST_DATABASE_PATH)
    init_db()


@pytest.fixture()
def isolated_job_client(monkeypatch: pytest.MonkeyPatch):
    reset_test_database()
    monkeypatch.setattr("app.main.job_runner.start", lambda: None)

    async def _stop() -> None:
        return None

    monkeypatch.setattr("app.main.job_runner.stop", _stop)
    monkeypatch.setattr("app.routes.jobs.job_runner.wake", lambda: None)

    with TestClient(app) as test_client:
        yield test_client

    engine.dispose()
    _unlink_with_retry(TEST_DATABASE_PATH)


@pytest.fixture()
def create_job_user():
    def _create_job_user(*, username: str, password: str) -> User:
        with SessionLocal() as db:
            user = User(username=username, password_hash=hash_password(password))
            db.add(user)
            db.commit()
            db.refresh(user)
            db.expunge(user)
            return user

    return _create_job_user


def login(client: TestClient, *, username: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def test_job_model_has_durable_lifecycle_fields() -> None:
    columns = Job.__table__.columns.keys()
    assert {"status", "progress", "progress_message", "error_message", "retry_count", "started_at", "completed_at", "timeout_seconds", "cancel_requested"}.issubset(columns)
    assert Job.__table__.columns["status"].type.length == 16


def test_job_create_is_idempotent_for_same_user_type_and_key(isolated_job_client: TestClient, create_job_user) -> None:
    create_job_user(username="job-user", password="StrongPass123!")
    login(isolated_job_client, username="job-user", password="StrongPass123!")

    headers = {"Idempotency-Key": "job-key-1"}
    first = isolated_job_client.post(
        "/api/jobs",
        json={"taskType": "report_generation", "payload": {"messages": [{"role": "user", "content": "hi"}]}, "timeoutSeconds": 5},
        headers=headers,
    )
    second = isolated_job_client.post(
        "/api/jobs",
        json={"taskType": "report_generation", "payload": {"messages": [{"role": "user", "content": "hi"}]}, "timeoutSeconds": 5},
        headers=headers,
    )

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["id"] == second.json()["id"]
    assert isolated_job_client.get("/api/jobs").json()["items"][0]["id"] == first.json()["id"]


def test_job_cancel_marks_queued_task_cancelled(isolated_job_client: TestClient, create_job_user) -> None:
    create_job_user(username="cancel-user", password="StrongPass123!")
    login(isolated_job_client, username="cancel-user", password="StrongPass123!")

    response = isolated_job_client.post(
        "/api/jobs",
        json={"taskType": "file_parse", "payload": {"filename": "sample.zip", "contentBase64": ""}, "timeoutSeconds": 10},
    )
    assert response.status_code == 202, response.text

    job_id = response.json()["id"]
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        job.cancel_requested = False
        db.commit()

    cancel_response = isolated_job_client.post(f"/api/jobs/{job_id}/cancel")
    assert cancel_response.status_code == 200, cancel_response.text
    payload = cancel_response.json()
    assert payload["status"] == "cancelled"
    assert payload["completedAt"] is not None
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        assert job.status == "cancelled"


def test_job_retry_requeues_failed_task_and_enforces_limit(isolated_job_client: TestClient, create_job_user) -> None:
    user = create_job_user(username="retry-user", password="StrongPass123!")
    login(isolated_job_client, username="retry-user", password="StrongPass123!")

    with SessionLocal() as db:
        job = Job(
            owner_user_id=user.id,
            task_type="model_inference",
            status="failed",
            progress=100,
            progress_message="执行失败",
            error_message="boom",
            max_retries=1,
            payload_json='{"messages":[{"role":"user","content":"hi"}]}',
            completed_at=now_utc(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    retry_response = isolated_job_client.post(f"/api/jobs/{job_id}/retry")
    assert retry_response.status_code == 202, retry_response.text
    retry_payload = retry_response.json()
    assert retry_payload["status"] == "queued"
    assert retry_payload["retryCount"] == 1
    assert retry_payload["errorMessage"] is None

    limit_response = isolated_job_client.post(f"/api/jobs/{job_id}/retry")
    assert limit_response.status_code == 409


def test_job_runner_timeout_and_cancellation_paths() -> None:
    reset_test_database()

    async def slow_handler(context: JobContext, _payload: dict[str, object]) -> dict[str, object]:
        await context.update(25, "slow path")
        await asyncio.sleep(0.05)
        return {"ok": True}

    async def cancellable_handler(context: JobContext, _payload: dict[str, object]) -> dict[str, object]:
        await context.update(30, "working")
        with SessionLocal() as db:
            job = db.get(Job, context.job_id)
            assert job is not None
            job.cancel_requested = True
            db.commit()
        await context.checkpoint()
        return {"ok": True}

    register_job_handler("job_test_timeout", slow_handler)
    register_job_handler("job_test_cancel", cancellable_handler)
    runner = JobRunner(poll_interval=0.01)

    with SessionLocal() as db:
        owner = User(username="runner-owner", password_hash=hash_password("StrongPass123!"))
        db.add(owner)
        db.flush()
        timeout_job = Job(
            owner_user_id=owner.id,
            task_type="job_test_timeout",
            timeout_seconds=0,
            payload_json="{}",
        )
        cancel_job = Job(
            owner_user_id=owner.id,
            task_type="job_test_cancel",
            timeout_seconds=5,
            payload_json="{}",
        )
        db.add_all([timeout_job, cancel_job])
        db.commit()
        db.refresh(timeout_job)
        db.refresh(cancel_job)
        timeout_id = timeout_job.id
        cancel_id = cancel_job.id

    asyncio.run(runner._execute(timeout_id))
    asyncio.run(runner._execute(cancel_id))

    with SessionLocal() as db:
        timeout_job = db.get(Job, timeout_id)
        cancel_job = db.get(Job, cancel_id)
        assert timeout_job is not None
        assert cancel_job is not None
        assert timeout_job.status == "failed"
        assert timeout_job.error_message and "超时" in timeout_job.error_message
        assert timeout_job.completed_at is not None
        assert cancel_job.status == "cancelled"
        assert cancel_job.completed_at is not None


def test_job_runner_records_handler_failure() -> None:
    reset_test_database()

    async def failing_handler(_context: JobContext, _payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")

    register_job_handler("job_test_fail", failing_handler)
    runner = JobRunner(poll_interval=0.01)

    with SessionLocal() as db:
        owner = User(username="runner-fail-owner", password_hash=hash_password("StrongPass123!"))
        db.add(owner)
        db.flush()
        job = Job(owner_user_id=owner.id, task_type="job_test_fail", timeout_seconds=5, payload_json="{}")
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    asyncio.run(runner._execute(job_id))

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error_message == "boom"
        assert job.completed_at is not None


def test_job_runner_can_be_reused_across_event_loops() -> None:
    reset_test_database()
    runner = JobRunner(poll_interval=0.01)

    async def start_and_stop() -> None:
        runner.start()
        await asyncio.sleep(0)
        await runner.stop()

    asyncio.run(start_and_stop())
    asyncio.run(start_and_stop())
    assert runner._loop_task is None
