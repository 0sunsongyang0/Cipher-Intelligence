from __future__ import annotations

import gc
from contextlib import asynccontextmanager
from pathlib import Path
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, hash_password
from app.config import settings
from app.database import engine, init_db, SessionLocal
from app.models import UsageLedgerEntry, User
from app.rate_limit import reset_failed_attempts
from app.routes.auth import router as auth_router
from app.routes.cape import get_cape_service, router as cape_router


def _unlink_with_retry(path: Path) -> None:
    for _ in range(20):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            gc.collect()
            time.sleep(0.05)


def login(client: TestClient) -> str:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "alice").one_or_none()
        if user is None:
            db.add(User(username="alice", password_hash=hash_password("StrongPass123!")))
            db.commit()

    response = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "StrongPass123!"},
    )
    assert response.status_code == 200
    return response.cookies[COOKIE_NAME]


@pytest.fixture()
def cape_client():
    test_database_path = Path(settings.database_url.removeprefix("sqlite:///"))
    engine.dispose()
    _unlink_with_retry(test_database_path)
    reset_failed_attempts()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        yield

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(auth_router)
    app.include_router(cape_router)

    with TestClient(app) as client:
        yield client

    reset_failed_attempts()
    engine.dispose()
    _unlink_with_retry(test_database_path)


def test_cape_submit_requires_user_session(cape_client: TestClient) -> None:
    response = cape_client.post(
        "/api/cape/submit",
        files={"file": ("sample.exe", b"MZ", "application/octet-stream")},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_new_cape_task_records_configured_cost(cape_client: TestClient, monkeypatch) -> None:
    token = login(cape_client)
    cape_client.cookies.set(COOKIE_NAME, token)
    monkeypatch.setattr(settings, "cape_task_cost_microusd", 250_000)

    class StubCapeService:
        async def submit_file(self, **_kwargs):
            class Result:
                task_id = 98
                status = "submitted"
                raw = {"reusedExistingTask": False}

            return Result()

    cape_client.app.dependency_overrides[get_cape_service] = lambda: StubCapeService()
    try:
        response = cape_client.post(
            "/api/cape/submit",
            files={"file": ("sample.exe", b"MZ", "application/octet-stream")},
        )
    finally:
        cape_client.app.dependency_overrides.clear()

    assert response.status_code == 200
    with SessionLocal() as db:
        entry = db.query(UsageLedgerEntry).filter_by(resource_type="cape").one()
        assert entry.cost_microusd == 250_000
        assert entry.storage_bytes == 2


def test_new_cape_task_converts_cny_cost_to_budget_currency(cape_client: TestClient, monkeypatch) -> None:
    token = login(cape_client)
    cape_client.cookies.set(COOKIE_NAME, token)
    monkeypatch.setattr(settings, "cape_task_cost_microusd", 0)
    monkeypatch.setattr(settings, "cape_task_cost_cny", 1)
    monkeypatch.setattr(settings, "billing_cny_per_usd", 7.2)

    class StubCapeService:
        async def submit_file(self, **_kwargs):
            class Result:
                task_id = 99
                status = "submitted"
                raw = {"reusedExistingTask": False}

            return Result()

    cape_client.app.dependency_overrides[get_cape_service] = lambda: StubCapeService()
    try:
        response = cape_client.post(
            "/api/cape/submit",
            files={"file": ("sample.exe", b"MZ", "application/octet-stream")},
        )
    finally:
        cape_client.app.dependency_overrides.clear()

    assert response.status_code == 200
    with SessionLocal() as db:
        entry = db.query(UsageLedgerEntry).filter_by(resource_type="cape").one()
        assert entry.cost_microusd == 138_889


def test_cape_task_is_blocked_before_projected_cost_exceeds_budget(cape_client: TestClient, monkeypatch) -> None:
    token = login(cape_client)
    cape_client.cookies.set(COOKIE_NAME, token)
    monkeypatch.setattr(settings, "cape_task_cost_microusd", 600_000)
    with SessionLocal() as db:
        user = db.query(User).filter_by(username="alice").one()
        user.subscription_tier = "free"
        db.commit()

    class StubCapeService:
        async def submit_file(self, **_kwargs):
            raise AssertionError("quota must be checked before CAPE submission")

    cape_client.app.dependency_overrides[get_cape_service] = lambda: StubCapeService()
    try:
        response = cape_client.post(
            "/api/cape/submit",
            files={"file": ("sample.exe", b"MZ", "application/octet-stream")},
        )
    finally:
        cape_client.app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "QUOTA_EXCEEDED"
    assert "monthly cost budget" in response.json()["detail"]["message"]


def test_cape_routes_use_service_layer(cape_client: TestClient) -> None:
    token = login(cape_client)
    cape_client.cookies.set(COOKIE_NAME, token)

    captured_submit_kwargs: dict[str, object] = {}

    class StubCapeService:
        async def submit_file(self, **_kwargs):
            captured_submit_kwargs.update(_kwargs)
            class Result:
                task_id = 99
                status = "submitted"
                raw = {"reusedExistingTask": True}

            return Result()

        async def get_task_snapshot(self, _task_id: int):
            class Result:
                task_id = 99
                status = "reported"
                completed = True
                score = 8.2
                target_filename = "payload.exe"
                machine = "win10"

            return Result()

        async def get_analysis_summary(self, _task_id: int):
            class Result:
                task_id = 99
                status = "reported"
                score = 8.2
                submitted_filename = "payload.exe"
                sha256 = "abc"
                iocs = {
                    "domains": ["evil.example"],
                    "ips": ["8.8.8.8"],
                    "urls": ["http://evil.example/payload"],
                }
                tactics = [
                    {
                        "technique": "T1547.001",
                        "signature": "run_key",
                        "description": "Persists",
                    }
                ]
                dropped_files = [
                    {
                        "name": "stage2.dll",
                        "path": "C:/Temp/stage2.dll",
                        "type": "PE32 DLL",
                        "sha256": "def",
                    }
                ]
                signatures = [{"name": "run_key"}]

            return Result()

    cape_client.app.dependency_overrides[get_cape_service] = lambda: StubCapeService()
    try:
        submit_response = cape_client.post(
            "/api/cape/submit?machine=win10&tags=trojan,cape",
            files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
        )
        status_response = cape_client.get("/api/cape/tasks/99")
        summary_response = cape_client.get("/api/cape/tasks/99/summary")
    finally:
        cape_client.app.dependency_overrides.clear()

    assert submit_response.status_code == 200
    assert submit_response.json() == {"taskId": 99, "status": "submitted", "reusedExistingTask": True}
    assert status_response.status_code == 200
    assert status_response.json() == {
        "taskId": 99,
        "status": "reported",
        "completed": True,
        "score": 8.2,
        "targetFilename": "payload.exe",
        "machine": "win10",
    }
    assert summary_response.status_code == 200
    assert summary_response.json()["iocs"]["domains"] == ["evil.example"]
    assert captured_submit_kwargs["tags"] == ["trojan", "cape"]


def test_cape_submit_infers_x64_tag_from_filename_when_none_provided(cape_client: TestClient) -> None:
    token = login(cape_client)
    cape_client.cookies.set(COOKIE_NAME, token)

    captured_submit_kwargs: dict[str, object] = {}

    class StubCapeService:
        async def submit_file(self, **kwargs):
            captured_submit_kwargs.update(kwargs)

            class Result:
                task_id = 101
                status = "submitted"
                raw = {}

            return Result()

    cape_client.app.dependency_overrides[get_cape_service] = lambda: StubCapeService()
    try:
        submit_response = cape_client.post(
            "/api/cape/submit",
            files={"file": ("npp.8.9.6.2.Installer.x64.exe", b"MZ", "application/octet-stream")},
        )
    finally:
        cape_client.app.dependency_overrides.clear()

    assert submit_response.status_code == 200
    assert submit_response.json() == {"taskId": 101, "status": "submitted", "reusedExistingTask": False}
    assert captured_submit_kwargs["tags"] == ["x64"]


def test_cape_submit_prefers_pe_arch_over_misleading_filename_hint(cape_client: TestClient) -> None:
    token = login(cape_client)
    cape_client.cookies.set(COOKIE_NAME, token)

    captured_submit_kwargs: dict[str, object] = {}

    class StubCapeService:
        async def submit_file(self, **kwargs):
            captured_submit_kwargs.update(kwargs)

            class Result:
                task_id = 102
                status = "submitted"
                raw = {}

            return Result()

    # Minimal PE with IMAGE_FILE_MACHINE_I386 so route inference should pick x86
    pe_stub = bytearray(0x90)
    pe_stub[0:2] = b"MZ"
    pe_stub[0x3C:0x40] = (0x80).to_bytes(4, "little")
    pe_stub[0x80:0x84] = b"PE\x00\x00"
    pe_stub[0x84:0x86] = (0x14C).to_bytes(2, "little")

    cape_client.app.dependency_overrides[get_cape_service] = lambda: StubCapeService()
    try:
        submit_response = cape_client.post(
            "/api/cape/submit",
            files={"file": ("npp.8.9.6.2.Installer.x64.exe", bytes(pe_stub), "application/octet-stream")},
        )
    finally:
        cape_client.app.dependency_overrides.clear()

    assert submit_response.status_code == 200
    assert submit_response.json() == {"taskId": 102, "status": "submitted", "reusedExistingTask": False}
    assert captured_submit_kwargs["tags"] == ["x86"]


def test_cape_summary_returns_conflict_when_report_is_not_ready(cape_client: TestClient) -> None:
    token = login(cape_client)
    cape_client.cookies.set(COOKIE_NAME, token)

    class StubCapeService:
        async def get_analysis_summary(self, _task_id: int):
            raise ValueError("Task is still being analyzed")

    cape_client.app.dependency_overrides[get_cape_service] = lambda: StubCapeService()
    try:
        response = cape_client.get("/api/cape/tasks/99/summary")
    finally:
        cape_client.app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": "Task is still being analyzed"}
