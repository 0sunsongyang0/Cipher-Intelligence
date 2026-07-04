import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database_module
from app.auth import COOKIE_NAME
from app.routes.auth import router as auth_router
from app.database import engine
from app.config import settings
from app.database import init_db
from app.deepseek import stream_chat_completion
from app.rate_limit import reset_failed_attempts
from app.routes.chat import router as chat_router
from app.routes.frontend import FRONTEND_ASSETS_DIR, router as frontend_router


def login(client) -> str:
    response = client.post("/api/auth/login", json={"password": "change-me"})
    assert response.status_code == 200
    return response.cookies[COOKIE_NAME]


@pytest.fixture()
def chat_client():
    test_database_path = Path("backend/data/test.db")
    engine.dispose()
    test_database_path.unlink(missing_ok=True)
    reset_failed_attempts()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
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
    app.include_router(chat_router)
    if FRONTEND_ASSETS_DIR.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="frontend-assets")
    app.include_router(frontend_router)

    with TestClient(app) as test_client:
        yield test_client

    reset_failed_attempts()
    engine.dispose()
    test_database_path.unlink(missing_ok=True)


@pytest.fixture()
def tmp_path():
    base_dir = Path(".pytest-tmp")
    base_dir.mkdir(exist_ok=True)
    temp_dir = Path(mkdtemp(dir=base_dir))

    try:
        yield temp_dir
    finally:
        rmtree(temp_dir, ignore_errors=True)


def test_init_db_migrates_existing_conversations_table_with_owner_session_id(
    tmp_path,
    monkeypatch,
) -> None:
    legacy_db_path = tmp_path / "legacy.db"
    migration_engine = None

    try:
        with sqlite3.connect(legacy_db_path) as connection:
            connection.execute(
                """
                CREATE TABLE conversations (
                    id INTEGER PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (1, "Legacy conversation", "2026-07-03T00:00:00+00:00", "2026-07-03T00:00:00+00:00"),
            )
            connection.commit()

        migration_engine = create_engine(
            f"sqlite:///{legacy_db_path}",
            connect_args={"check_same_thread": False},
        )
        migration_session_local = sessionmaker(
            bind=migration_engine,
            autocommit=False,
            autoflush=False,
        )

        monkeypatch.setattr(database_module, "engine", migration_engine)
        monkeypatch.setattr(database_module, "SessionLocal", migration_session_local)

        database_module.init_db()

        with sqlite3.connect(legacy_db_path) as connection:
            columns = {
                row[1]: row
                for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
            }
            assert "owner_session_id" in columns
            assert columns["owner_session_id"][3] == 1
            assert connection.execute(
                "SELECT owner_session_id FROM conversations WHERE id = 1"
            ).fetchone()[0] == 0

            indexes = {
                row[1]: row
                for row in connection.execute("PRAGMA index_list(conversations)").fetchall()
            }
            assert "ix_conversations_owner_session_id" in indexes
    finally:
        if migration_engine is not None:
            migration_engine.dispose()
        try:
            legacy_db_path.unlink(missing_ok=True)
        except PermissionError:
            pass


def test_init_db_repairs_missing_owner_session_id_index_when_column_already_exists(
    tmp_path,
    monkeypatch,
) -> None:
    intermediate_db_path = tmp_path / "intermediate.db"
    migration_engine = None

    try:
        with sqlite3.connect(intermediate_db_path) as connection:
            connection.execute(
                """
                CREATE TABLE conversations (
                    id INTEGER PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    owner_session_id INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at, owner_session_id) VALUES (?, ?, ?, ?, ?)",
                (
                    1,
                    "Intermediate conversation",
                    "2026-07-03T00:00:00+00:00",
                    "2026-07-03T00:00:00+00:00",
                    0,
                ),
            )
            connection.commit()

        migration_engine = create_engine(
            f"sqlite:///{intermediate_db_path}",
            connect_args={"check_same_thread": False},
        )
        migration_session_local = sessionmaker(
            bind=migration_engine,
            autocommit=False,
            autoflush=False,
        )

        monkeypatch.setattr(database_module, "engine", migration_engine)
        monkeypatch.setattr(database_module, "SessionLocal", migration_session_local)

        database_module.init_db()

        with sqlite3.connect(intermediate_db_path) as connection:
            indexes = {
                row[1]: row
                for row in connection.execute("PRAGMA index_list(conversations)").fetchall()
            }
            assert "ix_conversations_owner_session_id" in indexes
            assert connection.execute(
                "SELECT owner_session_id FROM conversations WHERE id = 1"
            ).fetchone()[0] == 0
    finally:
        if migration_engine is not None:
            migration_engine.dispose()
        try:
            intermediate_db_path.unlink(missing_ok=True)
        except PermissionError:
            pass


def test_chat_requires_authenticated_session(chat_client) -> None:
    response = chat_client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_chat_streams_plain_text_response_for_authenticated_session(chat_client, monkeypatch) -> None:
    login(chat_client)

    async def fake_stream_chat_completion(messages):
        assert messages == [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "hello"},
        ]
        yield "Hello"
        yield " campus"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "hello"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Hello campus"


def test_primary_app_mounts_server_chat_route(client, monkeypatch) -> None:
    login(client)

    async def fake_stream_chat_completion(messages):
        assert messages == [{"role": "user", "content": "ping"}]
        yield "ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "ping"}]},
    )

    assert response.status_code == 200
    assert response.text == "ok"


@pytest.mark.parametrize("api_key", ["", "unset", "   "])
def test_server_chat_route_returns_503_when_deepseek_key_is_missing(
    client, monkeypatch, api_key
) -> None:
    login(client)
    monkeypatch.setattr(settings, "deepseek_api_key", api_key)

    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "ping"}]},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "DeepSeek API key is not configured."}


@pytest.mark.anyio
async def test_stream_chat_completion_translates_http_status_errors(monkeypatch) -> None:
    original_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=401, request=request)

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)

    with pytest.raises(
        RuntimeError,
        match=r"^DeepSeek upstream returned 401 Unauthorized$",
    ):
        async for _chunk in stream_chat_completion([{"role": "user", "content": "ping"}]):
            pass


@pytest.mark.anyio
async def test_stream_chat_completion_translates_request_errors(monkeypatch) -> None:
    original_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network unavailable", request=request)

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)

    with pytest.raises(
        RuntimeError,
        match=r"^DeepSeek request failed before streaming completed\.$",
    ):
        async for _chunk in stream_chat_completion([{"role": "user", "content": "ping"}]):
            pass


def test_chat_rejects_empty_message_history(chat_client) -> None:
    login(chat_client)

    response = chat_client.post(
        "/api/chat",
        json={"messages": []},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "At least one message is required"}


def test_chat_forwards_message_history_exactly_as_provided(chat_client, monkeypatch) -> None:
    login(chat_client)

    async def fake_stream_chat_completion(messages):
        assert messages == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "follow up"},
        ]
        yield "done"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "follow up"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.text == "done"


def test_chat_surfaces_upstream_errors_for_authenticated_session(chat_client, monkeypatch) -> None:
    login(chat_client)

    async def failing_stream_chat_completion(messages):
        if messages:
            pass
        raise RuntimeError("DeepSeek upstream returned 401 Unauthorized")
        yield

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        failing_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "DeepSeek upstream returned 401 Unauthorized"}


def test_chat_surfaces_synchronous_upstream_errors_for_authenticated_session(
    chat_client, monkeypatch
) -> None:
    login(chat_client)

    def failing_stream_chat_completion(_messages):
        raise RuntimeError("DeepSeek request setup failed")

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        failing_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "DeepSeek request setup failed"}


def test_server_conversation_routes_are_not_mounted_in_primary_app(client) -> None:
    login(client)

    list_response = client.get("/api/conversations")
    create_response = client.post("/api/conversations", json={"title": "legacy chat"})
    messages_response = client.get("/api/conversations/1/messages")
    delete_response = client.delete("/api/conversations/1")

    for response in (list_response, create_response, messages_response, delete_response):
        assert response.status_code in {404, 410}
        if response.status_code == 404:
            assert response.json() == {"detail": "Not Found"}
