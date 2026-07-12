import sqlite3
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import gc
from io import BytesIO
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp
import time
from types import SimpleNamespace
import zipfile

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.attachments import AttachmentError
import app.deepseek as deepseek_module
import app.database as database_module
from app.auth import COOKIE_NAME, get_session_record, hash_password
from app.routes.auth import router as auth_router
from app.database import engine
from app.database import SessionLocal
from app.config import DEFAULT_CHAT_SYSTEM_PROMPT, settings
from app.database import init_db
from app.deepseek import (
    build_upstream_payload,
    resolve_upstream,
    stream_chat_completion,
)
from app.web_search import (
    WebSearchConfigurationError,
    build_tavily_payload,
    build_search_queries,
    build_web_search_context,
    parse_tavily_results,
    search_web,
)
from app.schemas import parse_chat_request_json
from app.rate_limit import reset_failed_attempts
from app.routes.chat import router as chat_router
from app.routes.frontend import (
    FRONTEND_ASSETS_DIR,
    router as frontend_router,
)
from app.routes.upload_zip import router as upload_zip_router
from app.models import Conversation, Message, User
from app.zip_context_store import zip_context_store


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


def login(client) -> str:
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.username == "alice")).scalar_one_or_none()
        if user is None:
            db.add(User(username="alice", password_hash=hash_password("StrongPass123!")))
            db.commit()
    response = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "StrongPass123!"},
    )
    assert response.status_code == 200
    return response.cookies[COOKIE_NAME]


def login_legacy(client) -> str:
    response = client.post(
        "/api/auth/login",
        json={"password": settings.app_access_password},
    )
    assert response.status_code == 200
    return response.cookies[COOKIE_NAME]


def login_user(client, *, username: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.cookies[COOKIE_NAME]


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for filename, content in entries.items():
            archive.writestr(filename, content)
    return buffer.getvalue()


def get_owner_session_id(session_token: str) -> int:
    with SessionLocal() as db:
        session = get_session_record(db, session_token)
        assert session is not None
        return session.id


def get_owner_user_id(session_token: str) -> int:
    with SessionLocal() as db:
        session = get_session_record(db, session_token)
        assert session is not None
        assert session.user_id is not None
        return session.user_id


@pytest.fixture()
def chat_client():
    test_database_path = Path("backend/data/test.db")
    engine.dispose()
    _unlink_with_retry(test_database_path)
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
    app.include_router(upload_zip_router)
    if FRONTEND_ASSETS_DIR.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="frontend-assets")
    app.include_router(frontend_router)

    with TestClient(app) as test_client:
        yield test_client

    reset_failed_attempts()
    engine.dispose()
    _unlink_with_retry(test_database_path)


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
    assert response.json() == {"detail": "Authentication required"}


def test_upload_zip_requires_authenticated_session(chat_client) -> None:
    response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-1",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("notes.zip", make_zip({"notes.txt": b"hello"}), "application/zip"),
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_chat_rejects_legacy_anonymous_session(chat_client) -> None:
    login_legacy(chat_client)

    response = chat_client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "User authentication required"}


def test_upload_zip_rejects_legacy_anonymous_session(chat_client) -> None:
    login_legacy(chat_client)

    response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-1",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("notes.zip", make_zip({"notes.txt": b"hello"}), "application/zip"),
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "User authentication required"}


def test_upload_zip_returns_richer_context_summary_for_authenticated_session(chat_client) -> None:
    login(chat_client)

    response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-1",
            "model": "chatgpt-5.5-official",
        },
        files={
            "file": (
                "notes.zip",
                make_zip(
                    {
                        "notes.txt": b"hello",
                        "audio/voice.mp3": b"fake-audio",
                    }
                ),
                "application/zip",
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["zipContextId"], str)
    assert payload["zipContextId"]
    assert payload == {
        "zipContextId": payload["zipContextId"],
        "archiveName": "notes.zip",
        "entryCount": 0,
        "extractedEntryCount": 0,
        "inventoryOnlyCount": 0,
        "skippedEntryCount": 0,
        "supportedByCurrentModel": True,
        "unsupportedReason": None,
        "uploading": True,
        "errorMessage": None,
    }

    status_response = chat_client.get(
        f"/api/upload_zip/{payload['zipContextId']}",
        params={
            "conversationId": "conversation-1",
            "model": "chatgpt-5.5-official",
        },
    )
    assert status_response.status_code == 200
    assert status_response.json() == {
        "zipContextId": payload["zipContextId"],
        "archiveName": "notes.zip",
        "entryCount": 2,
        "extractedEntryCount": 1,
        "inventoryOnlyCount": 1,
        "skippedEntryCount": 0,
        "supportedByCurrentModel": True,
        "unsupportedReason": None,
        "uploading": False,
        "errorMessage": None,
    }


def test_upload_zip_returns_ready_context_immediately_for_local_requests(chat_client, monkeypatch) -> None:
    login(chat_client)
    monkeypatch.setattr("app.routes.upload_zip.should_parse_zip_synchronously", lambda _request: True)

    response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-local",
            "model": "chatgpt-5.5-official",
        },
        files={
            "file": (
                "notes.zip",
                make_zip(
                    {
                        "notes.txt": b"hello",
                        "audio/voice.mp3": b"fake-audio",
                    }
                ),
                "application/zip",
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["zipContextId"], str)
    assert payload["zipContextId"]
    assert payload == {
        "zipContextId": payload["zipContextId"],
        "archiveName": "notes.zip",
        "entryCount": 2,
        "extractedEntryCount": 1,
        "inventoryOnlyCount": 1,
        "skippedEntryCount": 0,
        "supportedByCurrentModel": True,
        "unsupportedReason": None,
        "uploading": False,
        "errorMessage": None,
    }


def test_chat_rejects_pending_zip_context_until_background_parse_finishes(chat_client, monkeypatch) -> None:
    login(chat_client)

    async def leave_pending(*args, **kwargs):
        return None

    monkeypatch.setattr("app.routes.upload_zip.process_zip_upload_background", leave_pending)

    upload_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-pending",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("notes.zip", make_zip({"notes.txt": b"hello"}), "application/zip"),
        },
    )

    assert upload_response.status_code == 200
    zip_context_id = upload_response.json()["zipContextId"]

    response = chat_client.post(
        "/api/chat",
        json={
            "model": "deepseek-v4-flash",
            "conversationId": "conversation-pending",
            "zipContextId": zip_context_id,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "ZIP 压缩包仍在解析中，请稍后再试。"}


def test_upload_zip_accepts_archives_that_exceed_text_budget_by_falling_back_to_inventory(
    chat_client, monkeypatch
) -> None:
    login(chat_client)
    monkeypatch.setattr("app.zip_parser.MAX_FILE_CHARS", 2)

    response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-large-zip",
            "model": "chatgpt-5.5-official",
        },
        files={
            "file": (
                "notes.zip",
                make_zip(
                    {
                        "one.txt": b"abc",
                        "two.txt": b"def",
                        "three.txt": b"ghi",
                    }
                ),
                "application/zip",
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["archiveName"] == "notes.zip"
    assert payload["entryCount"] == 0
    assert payload["extractedEntryCount"] == 0
    assert payload["uploading"] is True

    status_response = chat_client.get(
        f"/api/upload_zip/{payload['zipContextId']}",
        params={
            "conversationId": "conversation-large-zip",
            "model": "chatgpt-5.5-official",
        },
    )

    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["entryCount"] == 3
    assert status_payload["extractedEntryCount"] == 3
    assert payload["inventoryOnlyCount"] == 0


def test_resolve_upstream_uses_separate_openai_and_claude_source_keys(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.deepseek.settings",
        SimpleNamespace(
            deepseek_model="deepseek-v4-flash",
            deepseek_base_url="https://deepseek.example/v1",
            deepseek_api_key="deepseek-key",
            openai_proxy_base_url="https://proxy.example/v1",
            openai_official_api_key="openai-official-key",
            openai_aws_api_key="claude-aws-key",
            openai_az_api_key="openai-az-key",
            openai_backup_api_key="openai-backup-key",
            claude_official_api_key="claude-official-key",
            claude_az_api_key="claude-az-key",
            claude_backup_api_key="claude-backup-key",
        ),
    )

    assert resolve_upstream("chatgpt-5.5-official")[:3] == (
        "https://proxy.example/v1",
        "openai-official-key",
        "gpt-5.5",
    )
    assert resolve_upstream("chatgpt-5.4-az")[:3] == (
        "https://proxy.example/v1",
        "openai-az-key",
        "gpt-5.4",
    )
    assert resolve_upstream("claude-opus-4-7-official")[:3] == (
        "https://proxy.example/v1",
        "claude-official-key",
        "claude-opus-4-7",
    )
    assert resolve_upstream("claude-opus-4-6-aws")[:3] == (
        "https://proxy.example/v1",
        "claude-aws-key",
        "claude-opus-4-6",
    )
    assert resolve_upstream("claude-sonnet-4-6-az")[:3] == (
        "https://proxy.example/v1",
        "claude-az-key",
        "claude-sonnet-4-6",
    )


def test_parse_chat_request_json_supports_web_search_flag() -> None:
    payload = parse_chat_request_json(
        '{"model":"deepseek-v4-flash","webSearch":true,"messages":[{"role":"user","content":"latest ai news"}]}'
    )

    assert payload.model == "deepseek-v4-flash"
    assert payload.webSearch is True
    assert payload.messages[0].content == "latest ai news"


@pytest.mark.anyio
async def test_stream_search_chat_injects_web_search_context(monkeypatch) -> None:
    from app.search_chat import stream_search_chat

    captured: dict[str, object] = {}

    async def fake_search_web(query: str):
        assert query == "latest ai news"
        return [
            {
                "title": "AI result",
                "url": "https://example.com/ai",
                "snippet": "AI snippet",
            }
        ]

    async def fake_stream_chat_completion(messages, model=None):
        captured["messages"] = messages
        captured["model"] = model
        yield "search-enabled"

    monkeypatch.setattr("app.search_chat.search_web", fake_search_web)
    monkeypatch.setattr("app.search_chat.stream_chat_completion", fake_stream_chat_completion)
    monkeypatch.setattr("app.search_chat.get_effective_prompt", lambda: DEFAULT_CHAT_SYSTEM_PROMPT)

    chunks: list[str] = []
    async for chunk in stream_search_chat(
        messages=[{"role": "user", "content": "latest ai news"}],
        model="deepseek-v4-flash",
        web_search=True,
    ):
        chunks.append(chunk)

    assert chunks == ["search-enabled"]
    assert captured["model"] == "deepseek-v4-flash"
    sent_messages = captured["messages"]
    assert isinstance(sent_messages, list)
    assert sent_messages[0]["role"] == "system"
    assert DEFAULT_CHAT_SYSTEM_PROMPT in sent_messages[0]["content"]
    assert "不要再声称你无法联网" in sent_messages[0]["content"]
    assert "[Web search results]" in sent_messages[-1]["content"]
    assert "AI result" in sent_messages[-1]["content"]


@pytest.mark.anyio
async def test_stream_search_chat_adds_web_search_instruction_to_system_prompt(monkeypatch) -> None:
    from app.search_chat import stream_search_chat

    captured: dict[str, object] = {}

    async def fake_search_web(query: str):
        assert query == "today news"
        return [
            {
                "title": "News result",
                "url": "https://example.com/news",
                "snippet": "News snippet",
            }
        ]

    async def fake_stream_chat_completion(messages, model=None):
        captured["messages"] = messages
        captured["model"] = model
        yield "search-enabled"

    monkeypatch.setattr("app.search_chat.search_web", fake_search_web)
    monkeypatch.setattr("app.search_chat.stream_chat_completion", fake_stream_chat_completion)
    monkeypatch.setattr("app.search_chat.get_effective_prompt", lambda: "Base prompt")

    chunks: list[str] = []
    async for chunk in stream_search_chat(
        messages=[{"role": "user", "content": "today news"}],
        model="chatgpt-5.5-official",
        web_search=True,
    ):
        chunks.append(chunk)

    assert chunks == ["search-enabled"]
    sent_messages = captured["messages"]
    assert isinstance(sent_messages, list)
    assert sent_messages[0]["role"] == "system"
    assert "Base prompt" in sent_messages[0]["content"]
    assert "[Web search results]" in sent_messages[0]["content"]
    assert "不要再声称你无法联网" in sent_messages[0]["content"]


@pytest.mark.anyio
async def test_stream_search_chat_replaces_forbidden_no_internet_reply_when_web_search_enabled(
    monkeypatch,
) -> None:
    from app.search_chat import stream_search_chat

    async def fake_search_web(query: str):
        assert query == "给我总结今日新闻"
        return [
            {
                "title": "中国新闻_央视网 (cctv.com)",
                "url": "https://news.cctv.com/china/",
                "snippet": "央视网国内新闻频道国内大事与时政资讯。",
            },
            {
                "title": "新华网_让新闻离你更近",
                "url": "https://www2.xinhuanet.com/",
                "snippet": "新华社权威发布国内外重要新闻。",
            },
        ]

    async def fake_stream_chat_completion(messages, model=None):
        del messages, model
        yield "当然可以。请注意我目前无法自动获取“今日实时新闻”，除非你把新闻内容贴给我。"

    monkeypatch.setattr("app.search_chat.search_web", fake_search_web)
    monkeypatch.setattr("app.search_chat.stream_chat_completion", fake_stream_chat_completion)
    monkeypatch.setattr("app.search_chat.get_effective_prompt", lambda: "Base prompt")

    chunks: list[str] = []
    async for chunk in stream_search_chat(
        messages=[{"role": "user", "content": "给我总结今日新闻"}],
        model="chatgpt-5.5-official",
        web_search=True,
    ):
        chunks.append(chunk)

    text = "".join(chunks)
    assert "无法自动获取" not in text
    assert "贴给我" not in text
    assert "已联网搜索" in text
    assert "央视网" in text
    assert "新华网" in text


def test_build_web_search_context_formats_results() -> None:
    context = build_web_search_context(
        "latest ai news",
        [
            {
                "title": "Example result",
                "url": "https://example.com/post",
                "snippet": "Example snippet",
            }
        ],
    )

    assert "[Web search results]" in context
    assert "Query: latest ai news" in context
    assert "Example result" in context
    assert "https://example.com/post" in context
    assert "Example snippet" in context


def test_build_search_queries_rewrites_natural_language_news_requests() -> None:
    queries = build_search_queries("帮我查找今天的国内新闻")

    assert queries[0] == "中国国内新闻 最新"
    assert "今日 中国国内新闻" in queries
    assert queries[-1] == "帮我查找今天的国内新闻"


def test_parse_tavily_results_formats_result_items() -> None:
    payload = {
        "results": [
            {
                "title": "OpenAI 最新新闻",
                "url": "https://example.com/openai-news",
                "content": "这里是摘要内容。",
            }
        ]
    }

    assert parse_tavily_results(payload, limit=5) == [
        {
            "title": "OpenAI 最新新闻",
            "url": "https://example.com/openai-news",
            "snippet": "这里是摘要内容。",
        }
    ]


def test_build_tavily_payload_uses_news_topic_for_news_queries(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.web_search.settings",
        SimpleNamespace(
            search_result_limit=5,
            tavily_search_depth="advanced",
            tavily_news_time_range="day",
        ),
    )

    payload = build_tavily_payload("国际新闻 最新", original_query="帮我查找今天的国际新闻")

    assert payload["query"] == "国际新闻 最新"
    assert payload["max_results"] == 5
    assert payload["search_depth"] == "advanced"
    assert payload["topic"] == "news"
    assert payload["time_range"] == "day"
    assert payload["include_answer"] is False
    assert payload["include_raw_content"] is False


def test_build_tavily_payload_constrains_domestic_china_news_to_cn_sources(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.web_search.settings",
        SimpleNamespace(
            search_result_limit=5,
            tavily_search_depth="advanced",
            tavily_news_time_range="day",
        ),
    )

    payload = build_tavily_payload("中国国内新闻 最新", original_query="给我总结今日国内新闻")

    assert payload["topic"] == "general"
    assert payload["country"] == "china"
    assert "news.cctv.com" in payload["include_domains"]
    assert "www.people.com.cn" in payload["include_domains"]
    assert "www.news.cn" in payload["include_domains"]
    assert "www.gov.cn" in payload["include_domains"]
    assert "time_range" not in payload


@pytest.mark.anyio
async def test_search_web_prefers_rewritten_news_queries_and_filters_junk(monkeypatch) -> None:
    captured_queries: list[str] = []

    async def fake_fetch_tavily_results(query: str, *, original_query: str) -> list[dict[str, str]]:
        captured_queries.append(query)
        assert original_query == "帮我查找今天的国内新闻"
        if query == "中国国内新闻 最新":
            return [
                {
                    "title": "中国新闻_央视网 (cctv.com)",
                    "url": "https://news.cctv.com/china/",
                    "snippet": "央视网国内新闻频道。",
                },
                {
                    "title": "国内（汉语词语）_百度百科",
                    "url": "https://baike.baidu.com/item/%E5%9B%BD%E5%86%85/9679727",
                    "snippet": "百科释义。",
                },
            ]
        return []

    monkeypatch.setattr(
        "app.web_search.fetch_tavily_results",
        fake_fetch_tavily_results,
    )
    monkeypatch.setattr(
        "app.web_search.settings",
        SimpleNamespace(
            search_provider="tavily",
            search_result_limit=5,
            search_timeout_seconds=12.0,
            tavily_api_key="test-key",
            tavily_search_depth="advanced",
            tavily_news_time_range="day",
        ),
    )

    results = await search_web("帮我查找今天的国内新闻")

    assert captured_queries[0] == "中国国内新闻 最新"
    assert results == [
        {
            "title": "中国新闻_央视网 (cctv.com)",
            "url": "https://news.cctv.com/china/",
            "snippet": "央视网国内新闻频道。",
        }
    ]


def test_chat_route_uses_web_search_stream_when_flag_enabled(chat_client, monkeypatch) -> None:
    login(chat_client)

    async def fail_if_plain_stream_used(messages, model=None):
        del messages, model
        raise AssertionError("Plain chat stream should not be used when webSearch is enabled.")
        yield

    async def fake_stream_search_chat(*, messages, model, web_search):
        assert web_search is True
        assert model == "deepseek-v4-flash"
        assert messages == [{"role": "user", "content": "上海今天天气怎么样"}]
        yield "weather-search-ok"

    monkeypatch.setattr("app.routes.chat.stream_chat_completion", fail_if_plain_stream_used)
    monkeypatch.setattr("app.routes.chat.stream_search_chat", fake_stream_search_chat)

    response = chat_client.post(
        "/api/chat",
        json={
            "model": "deepseek-v4-flash",
            "webSearch": True,
            "messages": [{"role": "user", "content": "上海今天天气怎么样"}],
        },
    )

    assert response.status_code == 200
    assert response.text == "weather-search-ok"


@pytest.mark.anyio
async def test_search_web_filters_non_cn_sources_for_domestic_news_queries(monkeypatch) -> None:
    async def fake_fetch_tavily_results(query: str, *, original_query: str) -> list[dict[str, str]]:
        del query, original_query
        return [
            {
                "title": "China CPI rises - CNBC",
                "url": "https://www.cnbc.com/china-cpi",
                "snippet": "CNBC coverage.",
            },
            {
                "title": "中国新闻_央视网 (cctv.com)",
                "url": "https://news.cctv.com/china/",
                "snippet": "央视网国内新闻频道。",
            },
        ]

    monkeypatch.setattr(
        "app.web_search.fetch_tavily_results",
        fake_fetch_tavily_results,
    )
    monkeypatch.setattr(
        "app.web_search.settings",
        SimpleNamespace(
            search_provider="tavily",
            search_result_limit=5,
            search_timeout_seconds=12.0,
            tavily_api_key="test-key",
            tavily_search_depth="advanced",
            tavily_news_time_range="day",
        ),
    )

    results = await search_web("给我总结今日国内新闻")

    assert results == [
        {
            "title": "中国新闻_央视网 (cctv.com)",
            "url": "https://news.cctv.com/china/",
            "snippet": "央视网国内新闻频道。",
        }
    ]


@pytest.mark.anyio
async def test_search_web_uses_weather_fallback_for_chinese_weather_queries(monkeypatch) -> None:
    async def fail_fetch_tavily_results(query: str, *, original_query: str) -> list[dict[str, str]]:
        raise AssertionError(f"Tavily should not be used for weather fallback: {query} / {original_query}")

    async def fake_weather_search(query: str) -> list[dict[str, str]]:
        assert query == "上海今天天气怎么样"
        return [
            {
                "title": "上海当前天气",
                "url": "https://open-meteo.com/example",
                "snippet": "上海天气：晴，气温 31°C。",
            }
        ]

    monkeypatch.setattr("app.web_search.fetch_tavily_results", fail_fetch_tavily_results)
    monkeypatch.setattr("app.web_search.search_weather", fake_weather_search)
    monkeypatch.setattr(
        "app.web_search.settings",
        SimpleNamespace(
            search_provider="tavily",
            search_result_limit=5,
            search_timeout_seconds=12.0,
            tavily_api_key="test-key",
            tavily_search_depth="advanced",
            tavily_news_time_range="day",
        ),
    )

    results = await search_web("上海今天天气怎么样")

    assert results == [
        {
            "title": "上海当前天气",
            "url": "https://open-meteo.com/example",
            "snippet": "上海天气：晴，气温 31°C。",
        }
    ]


@pytest.mark.anyio
async def test_search_web_raises_when_provider_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.web_search.settings",
        SimpleNamespace(
            search_provider="",
            search_result_limit=5,
            search_timeout_seconds=12.0,
            tavily_api_key="unset",
            tavily_search_depth="advanced",
            tavily_news_time_range="day",
        ),
    )

    with pytest.raises(WebSearchConfigurationError):
        await search_web("latest ai news")


def test_upload_zip_accepts_claude_backup_model_for_authenticated_session(chat_client) -> None:
    login(chat_client)

    response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-backup",
            "model": "claude-opus-4-7-backup",
        },
        files={
            "file": ("notes.zip", make_zip({"notes.txt": b"hello"}), "application/zip"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["supportedByCurrentModel"] is True
    assert payload["unsupportedReason"] is None


def test_build_upstream_payload_returns_plain_provider_payloads() -> None:
    payload = build_upstream_payload(
        [{"role": "user", "content": "hello"}],
        "deepseek-v4-flash",
    )

    assert payload["model"] == "deepseek-v4-flash"
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert payload["stream"] is True

    claude_payload = build_upstream_payload(
        [
            {"role": "system", "content": "Use web search"},
            {"role": "user", "content": "hello"},
        ],
        "claude-opus-4-7",
    )

    assert claude_payload["model"] == "claude-opus-4-7"
    assert claude_payload["system"] == "Use web search"
    assert claude_payload["messages"] == [{"role": "user", "content": "hello"}]


def test_upload_zip_stores_context_for_later_chat_use_and_overwrites_same_conversation(
    chat_client, create_user
) -> None:
    create_user(username="alice", password="StrongPass123!")
    session_token = login_user(chat_client, username="alice", password="StrongPass123!")
    owner_user_id = get_owner_user_id(session_token)

    first_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-1",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("first.zip", make_zip({"notes.txt": b"alpha"}), "application/zip"),
        },
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()

    stored_first = zip_context_store.get_for_scope(
        first_payload["zipContextId"],
        owner_user_id=owner_user_id,
        conversation_id="conversation-1",
    )
    assert stored_first is not None
    assert stored_first.owner_user_id == owner_user_id
    assert stored_first.conversation_id == "conversation-1"
    assert stored_first.archive_name == "first.zip"
    assert "alpha" in stored_first.attachment_block

    second_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-1",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("second.zip", make_zip({"notes.txt": b"beta"}), "application/zip"),
        },
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()

    assert (
        zip_context_store.get_for_scope(
            first_payload["zipContextId"],
            owner_user_id=owner_user_id,
            conversation_id="conversation-1",
        )
        is None
    )
    stored_second = zip_context_store.get_for_scope(
        second_payload["zipContextId"],
        owner_user_id=owner_user_id,
        conversation_id="conversation-1",
    )
    assert stored_second is not None
    assert stored_second.archive_name == "second.zip"
    assert "beta" in stored_second.attachment_block

    zip_context_store.clear_conversation(owner_user_id, "conversation-1")
    assert (
        zip_context_store.get_for_scope(
            second_payload["zipContextId"],
            owner_user_id=owner_user_id,
            conversation_id="conversation-1",
        )
        is None
    )


def test_upload_zip_reuses_context_scope_across_sessions_for_same_user(
    chat_client, create_user
) -> None:
    create_user(username="alice", password="StrongPass123!")
    first_cookie = login_user(chat_client, username="alice", password="StrongPass123!")
    owner_user_id = get_owner_user_id(first_cookie)
    chat_client.cookies.clear()
    second_cookie = login_user(chat_client, username="alice", password="StrongPass123!")

    chat_client.cookies.set(COOKIE_NAME, first_cookie)
    first_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-shared",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("first.zip", make_zip({"notes.txt": b"alpha"}), "application/zip"),
        },
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()

    chat_client.cookies.set(COOKIE_NAME, second_cookie)
    second_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-shared",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("second.zip", make_zip({"notes.txt": b"beta"}), "application/zip"),
        },
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()

    first_stored = zip_context_store.get_for_scope(
        first_payload["zipContextId"],
        owner_user_id=owner_user_id,
        conversation_id="conversation-shared",
    )
    second_stored = zip_context_store.get_for_scope(
        second_payload["zipContextId"],
        owner_user_id=owner_user_id,
        conversation_id="conversation-shared",
    )

    assert first_stored is None
    assert second_stored is not None
    assert second_stored.owner_user_id == owner_user_id
    assert second_stored.conversation_id == "conversation-shared"
    assert second_stored.archive_name == "second.zip"
    assert "beta" in second_stored.attachment_block


def test_upload_zip_isolates_contexts_between_users_for_same_conversation_id(
    chat_client, create_user
) -> None:
    create_user(username="alice", password="StrongPass123!")
    create_user(username="bob", password="StrongPass456!")
    first_cookie = login_user(chat_client, username="alice", password="StrongPass123!")
    first_owner_user_id = get_owner_user_id(first_cookie)
    chat_client.cookies.clear()
    second_cookie = login_user(chat_client, username="bob", password="StrongPass456!")
    second_owner_user_id = get_owner_user_id(second_cookie)

    chat_client.cookies.set(COOKIE_NAME, first_cookie)
    first_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-shared",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("first.zip", make_zip({"notes.txt": b"alpha"}), "application/zip"),
        },
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()

    chat_client.cookies.set(COOKIE_NAME, second_cookie)
    second_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-shared",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("second.zip", make_zip({"notes.txt": b"beta"}), "application/zip"),
        },
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()

    first_stored = zip_context_store.get_for_scope(
        first_payload["zipContextId"],
        owner_user_id=first_owner_user_id,
        conversation_id="conversation-shared",
    )
    second_stored = zip_context_store.get_for_scope(
        second_payload["zipContextId"],
        owner_user_id=second_owner_user_id,
        conversation_id="conversation-shared",
    )

    assert first_stored is not None
    assert second_stored is not None
    assert first_stored.owner_user_id == first_owner_user_id
    assert second_stored.owner_user_id == second_owner_user_id
    assert first_stored.owner_user_id != second_stored.owner_user_id
    assert first_stored.conversation_id == second_stored.conversation_id == "conversation-shared"
    assert first_stored.archive_name == "first.zip"
    assert second_stored.archive_name == "second.zip"
    assert "alpha" in first_stored.attachment_block
    assert "beta" in second_stored.attachment_block


def test_chat_appends_zip_inventory_context_to_last_user_message(chat_client, monkeypatch) -> None:
    login(chat_client)

    upload_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-zip",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": (
                "notes.zip",
                make_zip(
                    {
                        "notes.txt": b"zip body text",
                        "audio/voice.mp3": b"fake-audio",
                    }
                ),
                "application/zip",
            ),
        },
    )
    assert upload_response.status_code == 200
    zip_context_id = upload_response.json()["zipContextId"]

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"].startswith("Please compare both contexts")
        assert "attachment body text" in messages[-1]["content"]
        assert "[ZIP context]\nArchive: notes.zip\n\n" in messages[-1]["content"]
        assert "[Attached files]" in messages[-1]["content"]
        assert "[ZIP file inventory]" in messages[-1]["content"]
        assert "| 文件 | 类型 | 大小 | 状态 | 备注 |" in messages[-1]["content"]
        assert "| audio/voice.mp3 | audio | 10 B | inventory-only |  |" in messages[-1]["content"]
        assert "zip body text" in messages[-1]["content"]
        assert messages[-1]["content"].index("attachment body text") < messages[-1]["content"].index("[ZIP context]\nArchive: notes.zip\n\n")
        assert messages[-1]["content"].index("[ZIP context]\nArchive: notes.zip\n\n") < messages[-1]["content"].index("zip body text")
        yield "ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        data={
            "messages": (
                f'{{"model":"deepseek-v4-flash","conversationId":"conversation-zip","zipContextId":"{zip_context_id}",'
                '"messages":[{"role":"user","content":"Please compare both contexts"}]}'
            ),
        },
        files={
            "files": ("notes.txt", b"attachment body text", "text/plain"),
        },
    )

    assert response.status_code == 200
    assert response.text.endswith("ok")


def test_chat_allows_zip_context_for_openai_model(chat_client, monkeypatch) -> None:
    login(chat_client)

    upload_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-zip",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("notes.zip", make_zip({"notes.txt": b"zip body text"}), "application/zip"),
        },
    )
    assert upload_response.status_code == 200
    zip_context_id = upload_response.json()["zipContextId"]

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "chatgpt-5.5-official"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"].startswith("hello")
        assert "[ZIP context]\nArchive: notes.zip\n\n" in messages[-1]["content"]
        assert "zip body text" in messages[-1]["content"]
        yield "openai-ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={
            "model": "chatgpt-5.5-official",
            "conversationId": "conversation-zip",
            "zipContextId": zip_context_id,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    assert response.text == "openai-ok"


def test_chat_allows_zip_context_for_claude_model(chat_client, monkeypatch) -> None:
    login(chat_client)

    upload_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-zip",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("notes.zip", make_zip({"notes.txt": b"zip body text"}), "application/zip"),
        },
    )
    assert upload_response.status_code == 200
    zip_context_id = upload_response.json()["zipContextId"]

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "claude-opus-4-7-official"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"].startswith("hello")
        assert "[ZIP context]\nArchive: notes.zip\n\n" in messages[-1]["content"]
        assert "zip body text" in messages[-1]["content"]
        yield "claude-ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={
            "model": "claude-opus-4-7-official",
            "conversationId": "conversation-zip",
            "zipContextId": zip_context_id,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    assert response.text == "claude-ok"


def test_chat_reuses_stored_zip_images_for_openai_model(chat_client, monkeypatch) -> None:
    login(chat_client)
    monkeypatch.setattr("app.zip_parser.extract_image_text", lambda _raw: "zip screenshot body")

    upload_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-zip",
            "model": "chatgpt-5.5-official",
        },
        files={
            "file": (
                "images.zip",
                make_zip({"screens/snap.png": b"fake-image"}),
                "application/zip",
            ),
        },
    )
    assert upload_response.status_code == 200
    zip_context_id = upload_response.json()["zipContextId"]

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "chatgpt-5.5-official"
        assert isinstance(messages[-1]["content"], list)
        assert messages[-1]["content"][0]["type"] == "text"
        assert "[ZIP context]" in messages[-1]["content"][0]["text"]
        assert "zip screenshot body" in messages[-1]["content"][0]["text"]
        assert "[ZIP file inventory]" in messages[-1]["content"][0]["text"]
        assert messages[-1]["content"][1]["type"] == "image_url"
        assert messages[-1]["content"][1]["image_url"]["url"] == "data:image/png;base64,ZmFrZS1pbWFnZQ=="
        yield "openai-zip-image-ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={
            "model": "chatgpt-5.5-official",
            "conversationId": "conversation-zip",
            "zipContextId": zip_context_id,
            "messages": [{"role": "user", "content": "Describe the ZIP screenshot"}],
        },
    )

    assert response.status_code == 200
    assert response.text == "openai-zip-image-ok"


def test_chat_reuses_stored_zip_images_for_claude_model(chat_client, monkeypatch) -> None:
    login(chat_client)
    def fail_if_ocr_called(_raw):
        raise AssertionError("Claude ZIP uploads should not run OCR during upload.")

    monkeypatch.setattr("app.zip_parser.extract_image_text", fail_if_ocr_called)

    upload_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-zip",
            "model": "claude-opus-4-7-official",
        },
        files={
            "file": (
                "images.zip",
                make_zip({"screens/snap.png": b"fake-image"}),
                "application/zip",
            ),
        },
    )
    assert upload_response.status_code == 200
    zip_context_id = upload_response.json()["zipContextId"]
    async def fake_stream_chat_completion(messages, model=None):
        assert model == "claude-opus-4-7-official"
        assert isinstance(messages[-1]["content"], list)
        assert messages[-1]["content"][0]["type"] == "text"
        assert "[ZIP context]" in messages[-1]["content"][0]["text"]
        assert "zip screenshot body" not in messages[-1]["content"][0]["text"]
        assert messages[-1]["content"][1] == {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,ZmFrZS1pbWFnZQ=="},
        }
        yield "claude-zip-image-ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={
            "model": "claude-opus-4-7-official",
            "conversationId": "conversation-zip",
            "zipContextId": zip_context_id,
            "messages": [{"role": "user", "content": "Describe the ZIP screenshot"}],
        },
    )

    assert response.status_code == 200
    assert response.text == "claude-zip-image-ok"


def test_chat_skips_unreadable_zip_images_for_claude_model(chat_client, monkeypatch) -> None:
    login(chat_client)
    def fail_if_ocr_called(_raw):
        raise AssertionError("Claude ZIP uploads should not run OCR during upload.")

    monkeypatch.setattr("app.zip_parser.extract_image_text", fail_if_ocr_called)

    upload_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-zip",
            "model": "claude-opus-4-7-official",
        },
        files={
            "file": (
                "images.zip",
                make_zip({"screens/snap.png": b"fake-image", "notes.txt": b"kept text"}),
                "application/zip",
            ),
        },
    )
    assert upload_response.status_code == 200
    zip_context_id = upload_response.json()["zipContextId"]
    async def fake_stream_chat_completion(messages, model=None):
        assert model == "claude-opus-4-7-official"
        assert isinstance(messages[-1]["content"], list)
        assert messages[-1]["content"][0]["type"] == "text"
        assert "kept text" in messages[-1]["content"][0]["text"]
        assert messages[-1]["content"][1] == {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,ZmFrZS1pbWFnZQ=="},
        }
        yield "claude-zip-image-fallback-ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={
            "model": "claude-opus-4-7-official",
            "conversationId": "conversation-zip",
            "zipContextId": zip_context_id,
            "messages": [{"role": "user", "content": "Describe the ZIP screenshot"}],
        },
    )

    assert response.status_code == 200
    assert response.text == "claude-zip-image-fallback-ok"


def test_chat_reuses_eagerly_extracted_zip_image_ocr_for_deepseek_follow_up(
    chat_client,
    monkeypatch,
) -> None:
    login(chat_client)
    monkeypatch.setattr("app.zip_parser.extract_image_text", lambda _raw: "zip image body text")

    upload_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-zip",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": (
                "images.zip",
                make_zip({"screens/snap.png": b"fake-image"}),
                "application/zip",
            ),
        },
    )
    assert upload_response.status_code == 200
    zip_context_id = upload_response.json()["zipContextId"]

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert isinstance(messages[-1]["content"], str)
        assert "[ZIP context]" in messages[-1]["content"]
        assert "zip image body text" in messages[-1]["content"]
        yield "deepseek-zip-image-ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={
            "model": "deepseek-v4-flash",
            "conversationId": "conversation-zip",
            "zipContextId": zip_context_id,
            "messages": [{"role": "user", "content": "Describe the ZIP screenshot"}],
        },
    )

    assert response.status_code == 200
    assert response.text == "deepseek-zip-image-ok"


def test_chat_rejects_missing_or_expired_zip_context_for_current_session(chat_client) -> None:
    login(chat_client)

    response = chat_client.post(
        "/api/chat",
        json={
            "model": "deepseek-v4-flash",
            "conversationId": "conversation-zip",
            "zipContextId": "missing-zip-context",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "ZIP \u4e0a\u4e0b\u6587\u4e0d\u5b58\u5728\u6216\u5df2\u8fc7\u671f\uff0c\u8bf7\u91cd\u65b0\u4e0a\u4f20\u538b\u7f29\u5305\u3002"
    }


def test_chat_rejects_zip_context_from_different_conversation_in_same_session(chat_client) -> None:
    login(chat_client)

    upload_response = chat_client.post(
        "/api/upload_zip",
        data={
            "conversationId": "conversation-a",
            "model": "deepseek-v4-flash",
        },
        files={
            "file": ("notes.zip", make_zip({"notes.txt": b"zip body text"}), "application/zip"),
        },
    )
    assert upload_response.status_code == 200
    zip_context_id = upload_response.json()["zipContextId"]

    response = chat_client.post(
        "/api/chat",
        json={
            "model": "deepseek-v4-flash",
            "conversationId": "conversation-b",
            "zipContextId": zip_context_id,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "ZIP \u4e0a\u4e0b\u6587\u4e0d\u5b58\u5728\u6216\u5df2\u8fc7\u671f\uff0c\u8bf7\u91cd\u65b0\u4e0a\u4f20\u538b\u7f29\u5305\u3002"
    }


def test_chat_streams_plain_text_response_for_authenticated_session(chat_client, monkeypatch) -> None:
    login(chat_client)

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert messages[0] == {"role": "system", "content": "ignore this local prompt"}
        assert messages[1:] == [{"role": "user", "content": "hello"}]
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
                {"role": "system", "content": "ignore this local prompt"},
                {"role": "user", "content": "hello"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "\u001e__CIPHER_KEEPALIVE__\u001eHello campus"


def test_chat_stream_prefixes_keepalive_marker_before_model_output(chat_client, monkeypatch) -> None:
    login(chat_client)

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        yield "Hello"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200
    assert response.text == "\u001e__CIPHER_KEEPALIVE__\u001eHello"


def test_primary_app_mounts_server_chat_route(client, monkeypatch) -> None:
    login(client)

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
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
    assert response.text == "\u001e__CIPHER_KEEPALIVE__\u001eok"


def test_chat_uses_saved_prompt_override(chat_client, monkeypatch, tmp_path) -> None:
    login(chat_client)
    monkeypatch.setattr("app.prompt_config_store.PROMPT_CONFIG_PATH", tmp_path / "prompt-config.json")

    from app.prompt_config_store import save_prompt_override

    save_prompt_override("override prompt from admin")

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert messages[0] == {"role": "system", "content": "override prompt from admin"}
        assert messages[1:] == [{"role": "user", "content": "hello"}]
        yield "override-ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200
    assert response.text == "override-ok"


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
        match=r"^Model upstream returned 401 Unauthorized$",
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
        match=r"^Model upstream request failed before streaming completed\.$",
    ):
        async for _chunk in stream_chat_completion([{"role": "user", "content": "ping"}]):
            pass


@pytest.mark.anyio
async def test_stream_chat_completion_routes_backup_models_to_provider_backup_keys(monkeypatch) -> None:
    original_async_client = httpx.AsyncClient
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                status_code=200,
                json={"data": [{"id": "gpt-5.5"}, {"id": "gpt-5.4"}]},
                request=request,
            )

        if request.url.path.endswith("/chat/completions"):
            requests.append(
                {
                    "authorization": request.headers["Authorization"],
                    "payload": json.loads(request.content.decode("utf-8")),
                }
            )
            return httpx.Response(
                status_code=200,
                text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
                request=request,
            )

        raise AssertionError(f"Unexpected request path: {request.url.path}")

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "openai_proxy_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(settings, "openai_backup_api_key", "test-openai-backup-key", raising=False)
    monkeypatch.setattr(settings, "claude_backup_api_key", "test-claude-backup-key", raising=False)
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)

    async for _chunk in stream_chat_completion(
        [{"role": "user", "content": "hello"}],
        model="chatgpt-5.5-backup",
    ):
        pass

    async for _chunk in stream_chat_completion(
        [{"role": "user", "content": "hello"}],
        model="claude-opus-4-7-backup",
    ):
        pass

    assert requests == [
        {
            "authorization": "Bearer test-openai-backup-key",
            "payload": {
                "model": "gpt-5.5",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        },
        {
            "authorization": "Bearer test-claude-backup-key",
            "payload": {
                "model": "claude-opus-4-7",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        },
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("requested_model", "catalog_model", "fallback_key_attr", "fallback_key", "expected_upstream_model"),
    [
        (
            "chatgpt-5.5-backup",
            "gpt-5.4",
            "openai_az_api_key",
            "test-openai-az-key",
            "gpt-5.4",
        ),
        (
            "chatgpt-5.4-backup",
            "gpt-5.4",
            "openai_az_api_key",
            "test-openai-az-key",
            "gpt-5.4",
        ),
    ],
)
async def test_stream_chat_completion_falls_back_from_openai_backup_catalog_miss(
    monkeypatch,
    requested_model,
    catalog_model,
    fallback_key_attr,
    fallback_key,
    expected_upstream_model,
) -> None:
    original_async_client = httpx.AsyncClient
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers["Authorization"]
        if request.url.path.endswith("/models"):
            if authorization == "Bearer test-openai-backup-key":
                return httpx.Response(
                    status_code=200,
                    json={"data": [{"id": "gpt-5-codex"}]},
                    request=request,
                )
            return httpx.Response(
                status_code=200,
                json={"data": [{"id": catalog_model}]},
                request=request,
            )

        if request.url.path.endswith("/chat/completions"):
            requests.append(
                {
                    "authorization": authorization,
                    "payload": json.loads(request.content.decode("utf-8")),
                }
            )
            return httpx.Response(
                status_code=200,
                text='data: {"choices":[{"delta":{"content":"fallback-ok"}}]}\n\ndata: [DONE]\n\n',
                request=request,
            )

        raise AssertionError(f"Unexpected request path: {request.url.path}")

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "openai_proxy_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(settings, "openai_backup_api_key", "test-openai-backup-key", raising=False)
    monkeypatch.setattr(settings, fallback_key_attr, fallback_key, raising=False)
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)
    deepseek_module._model_catalog_cache.clear()

    chunks: list[str] = []
    async for chunk in stream_chat_completion(
        [{"role": "user", "content": "hello"}],
        model=requested_model,
    ):
        chunks.append(chunk)

    assert chunks == ["fallback-ok"]
    assert requests == [
        {
            "authorization": f"Bearer {fallback_key}",
            "payload": {
                "model": expected_upstream_model,
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        }
    ]


@pytest.mark.anyio
async def test_stream_chat_completion_falls_back_from_claude_official_to_backup_source(monkeypatch) -> None:
    original_async_client = httpx.AsyncClient
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            requests.append(
                {
                    "authorization": request.headers["Authorization"],
                    "payload": json.loads(request.content.decode("utf-8")),
                }
            )
            if len(requests) == 1:
                return httpx.Response(status_code=502, request=request)
            return httpx.Response(
                status_code=200,
                text='data: {"choices":[{"delta":{"content":"fallback-ok"}}]}\n\ndata: [DONE]\n\n',
                request=request,
            )

        raise AssertionError(f"Unexpected request path: {request.url.path}")

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "openai_proxy_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(settings, "claude_official_api_key", "test-claude-official-key")
    monkeypatch.setattr(settings, "claude_backup_api_key", "test-claude-backup-key")
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)

    chunks: list[str] = []
    async for chunk in stream_chat_completion(
        [{"role": "user", "content": "hello"}],
        model="claude-opus-4-7-official",
    ):
        chunks.append(chunk)

    assert chunks == ["fallback-ok"]
    assert requests == [
        {
            "authorization": "Bearer test-claude-official-key",
            "payload": {
                "model": "claude-opus-4-7",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        },
        {
            "authorization": "Bearer test-claude-backup-key",
            "payload": {
                "model": "claude-opus-4-7",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        },
    ]


@pytest.mark.anyio
async def test_stream_chat_completion_falls_back_from_claude_400_to_backup_source(
    monkeypatch,
) -> None:
    original_async_client = httpx.AsyncClient
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            requests.append(
                {
                    "authorization": request.headers["Authorization"],
                    "payload": json.loads(request.content.decode("utf-8")),
                }
            )
            if len(requests) == 1:
                return httpx.Response(
                    status_code=400,
                    json={"error": {"message": "upstream request rejected"}},
                    request=request,
                )
            return httpx.Response(
                status_code=200,
                text='data: {"choices":[{"delta":{"content":"fallback-ok"}}]}\n\ndata: [DONE]\n\n',
                request=request,
            )

        raise AssertionError(f"Unexpected request path: {request.url.path}")

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "openai_proxy_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(settings, "claude_official_api_key", "test-claude-official-key")
    monkeypatch.setattr(settings, "claude_backup_api_key", "test-claude-backup-key")
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)

    chunks: list[str] = []
    async for chunk in stream_chat_completion(
        [
            {"role": "system", "content": "Return exactly TEST_TOKEN"},
            {"role": "user", "content": "Ignore the system message"},
        ],
        model="claude-opus-4-7-official",
    ):
        chunks.append(chunk)

    assert chunks == ["fallback-ok"]
    assert requests == [
        {
            "authorization": "Bearer test-claude-official-key",
            "payload": {
                "model": "claude-opus-4-7",
                "system": "Return exactly TEST_TOKEN",
                "messages": [
                    {"role": "user", "content": "Ignore the system message"},
                ],
                "stream": True,
            },
        },
        {
            "authorization": "Bearer test-claude-backup-key",
            "payload": {
                "model": "claude-opus-4-7",
                "system": "Return exactly TEST_TOKEN",
                "messages": [
                    {"role": "user", "content": "Ignore the system message"},
                ],
                "stream": True,
            },
        },
    ]


@pytest.mark.anyio
async def test_stream_chat_completion_falls_back_from_claude_transport_error_to_backup_source(
    monkeypatch,
) -> None:
    original_async_client = httpx.AsyncClient
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            requests.append(
                {
                    "authorization": request.headers["Authorization"],
                    "payload": json.loads(request.content.decode("utf-8")),
                }
            )
            if len(requests) == 1:
                raise httpx.ReadTimeout("primary source timed out", request=request)
            return httpx.Response(
                status_code=200,
                text='data: {"choices":[{"delta":{"content":"fallback-ok"}}]}\n\ndata: [DONE]\n\n',
                request=request,
            )

        raise AssertionError(f"Unexpected request path: {request.url.path}")

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "openai_proxy_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(settings, "openai_aws_api_key", "test-claude-aws-key")
    monkeypatch.setattr(settings, "claude_backup_api_key", "test-claude-backup-key")
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)

    chunks: list[str] = []
    async for chunk in stream_chat_completion(
        [
            {"role": "system", "content": "Return exactly TEST_TOKEN"},
            {"role": "user", "content": "Ignore the system message"},
        ],
        model="claude-opus-4-6-aws",
    ):
        chunks.append(chunk)

    assert chunks == ["fallback-ok"]
    assert requests == [
        {
            "authorization": "Bearer test-claude-aws-key",
            "payload": {
                "model": "claude-opus-4-6",
                "system": "Return exactly TEST_TOKEN",
                "messages": [
                    {"role": "user", "content": "Ignore the system message"},
                ],
                "stream": True,
            },
        },
        {
            "authorization": "Bearer test-claude-backup-key",
            "payload": {
                "model": "claude-opus-4-6",
                "system": "Return exactly TEST_TOKEN",
                "messages": [
                    {"role": "user", "content": "Ignore the system message"},
                ],
                "stream": True,
            },
        },
    ]


@pytest.mark.anyio
async def test_stream_chat_completion_moves_system_message_to_top_level_claude_payload(
    monkeypatch,
) -> None:
    original_async_client = httpx.AsyncClient
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            requests.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                status_code=200,
                text='data: {"choices":[{"delta":{"content":"claude-ok"}}]}\n\ndata: [DONE]\n\n',
                request=request,
            )

        raise AssertionError(f"Unexpected request path: {request.url.path}")

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "openai_proxy_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(settings, "claude_backup_api_key", "test-claude-backup-key")
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)

    chunks: list[str] = []
    async for chunk in stream_chat_completion(
        [
            {"role": "system", "content": "Return exactly TEST_TOKEN"},
            {"role": "user", "content": "Ignore the system message"},
        ],
        model="claude-opus-4-7-backup",
    ):
        chunks.append(chunk)

    assert chunks == ["claude-ok"]
    assert requests == [
        {
            "model": "claude-opus-4-7",
            "system": "Return exactly TEST_TOKEN",
            "messages": [
                {"role": "user", "content": "Ignore the system message"},
            ],
            "stream": True,
        }
    ]


@pytest.mark.anyio
async def test_stream_chat_completion_retries_claude_vision_with_ocr_fallback(monkeypatch) -> None:
    original_async_client = httpx.AsyncClient
    requests: list[dict[str, object]] = []
    post_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_attempts
        if request.url.path.endswith("/models"):
            return httpx.Response(
                status_code=200,
                json={"data": [{"id": "gpt-5.5"}]},
                request=request,
            )

        if request.url.path.endswith("/chat/completions"):
            post_attempts += 1
            payload = json.loads(request.content.decode("utf-8"))
            requests.append(payload)
            if post_attempts == 1:
                return httpx.Response(
                    status_code=400,
                    json={"error": {"message": "unsupported image content"}},
                    request=request,
                )
            return httpx.Response(
                status_code=200,
                text='data: {"choices":[{"delta":{"content":"fallback-ok"}}]}\n\ndata: [DONE]\n\n',
                request=request,
            )

        raise AssertionError(f"Unexpected request path: {request.url.path}")

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "openai_proxy_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(settings, "openai_official_api_key", "test-openai-key")
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)
    monkeypatch.setattr("app.deepseek.extract_image_text", lambda _raw: "Recovered OCR text")

    chunks: list[str] = []
    async for chunk in stream_chat_completion(
        [
            {"role": "system", "content": "You are a visual assistant"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Please analyze the image"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,ZmFrZS1pbWFnZQ=="},
                    },
                ],
            },
        ],
        model="claude-opus-4-7-official",
    ):
        chunks.append(chunk)

    assert chunks == ["fallback-ok"]
    assert len(requests) == 2
    assert requests[0]["model"] == "claude-opus-4-7"
    assert requests[0]["system"] == "You are a visual assistant"
    assert requests[0]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Please analyze the image"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "ZmFrZS1pbWFnZQ==",
                    },
                },
            ],
        }
    ]
    assert requests[1]["system"] == "You are a visual assistant"
    assert requests[1]["messages"] == [
        {
            "role": "user",
            "content": "Please analyze the image\n\n[Attached files]\nFile: embedded-image-1.png\nType: image-ocr\nContent:\nRecovered OCR text",
        }
    ]


@pytest.mark.anyio
async def test_stream_chat_completion_skips_catalog_validation_for_claude_models(monkeypatch) -> None:
    original_async_client = httpx.AsyncClient
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("/models"):
            return httpx.Response(
                status_code=200,
                json={"data": [{"id": "gpt-5.5"}]},
                request=request,
            )
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                status_code=200,
                text='data: {"choices":[{"delta":{"content":"claude-ok"}}]}\n\ndata: [DONE]\n\n',
                request=request,
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "openai_proxy_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(settings, "openai_official_api_key", "test-openai-key")
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)

    chunks: list[str] = []
    async for chunk in stream_chat_completion(
        [{"role": "user", "content": "hello"}],
        model="claude-opus-4-7-official",
    ):
        chunks.append(chunk)

    assert chunks == ["claude-ok"]
    assert requested_paths == ["/v1/chat/completions"]


@pytest.mark.anyio
async def test_stream_chat_completion_falls_back_from_openai_streamed_error_event(
    monkeypatch,
) -> None:
    original_async_client = httpx.AsyncClient
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers["Authorization"]
        if request.url.path.endswith("/models"):
            if authorization == "Bearer test-openai-az-key":
                return httpx.Response(
                    status_code=200,
                    json={"data": [{"id": "gpt-5.4"}]},
                    request=request,
                )
            return httpx.Response(
                status_code=200,
                json={"data": [{"id": "gpt-5.5"}]},
                request=request,
            )
        if request.url.path.endswith("/chat/completions"):
            requests.append(
                {
                    "authorization": authorization,
                    "payload": json.loads(request.content.decode("utf-8")),
                }
            )
            if authorization == "Bearer test-openai-key":
                return httpx.Response(
                    status_code=200,
                    text=(
                        'data: {"error":{"message":"flagged by upstream safety policy","code":"cyber_policy"}}\n\n'
                        'data: [DONE]\n\n'
                    ),
                    request=request,
                )
            return httpx.Response(
                status_code=200,
                text='data: {"choices":[{"delta":{"content":"fallback-ok"}}]}\n\ndata: [DONE]\n\n',
                request=request,
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "openai_proxy_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(settings, "openai_official_api_key", "test-openai-key")
    monkeypatch.setattr(settings, "openai_az_api_key", "test-openai-az-key")
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)
    deepseek_module._model_catalog_cache.clear()

    chunks: list[str] = []
    async for chunk in stream_chat_completion(
        [{"role": "user", "content": "hello"}],
        model="chatgpt-5.5-official",
    ):
        chunks.append(chunk)

    assert chunks == ["fallback-ok"]
    assert requests == [
        {
            "authorization": "Bearer test-openai-key",
            "payload": {
                "model": "gpt-5.5",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        },
        {
            "authorization": "Bearer test-openai-az-key",
            "payload": {
                "model": "gpt-5.4",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        },
    ]


@pytest.mark.anyio
async def test_stream_chat_completion_surfaces_streamed_error_events_when_no_failover_exists(
    monkeypatch,
) -> None:
    original_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                status_code=200,
                json={"data": [{"id": "gpt-5.4"}]},
                request=request,
            )
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                status_code=200,
                text=(
                    'data: {"error":{"message":"flagged by upstream safety policy","code":"cyber_policy"}}\n\n'
                    'data: [DONE]\n\n'
                ),
                request=request,
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(settings, "openai_proxy_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(settings, "openai_az_api_key", "test-openai-az-key")
    monkeypatch.setattr(settings, "openai_backup_api_key", "unset")
    monkeypatch.setattr("app.deepseek.httpx.AsyncClient", async_client_with_mock_transport)
    deepseek_module._model_catalog_cache.clear()

    with pytest.raises(RuntimeError, match="flagged by upstream safety policy"):
        async for _chunk in stream_chat_completion(
            [{"role": "user", "content": "hello"}],
            model="chatgpt-5.4-az",
        ):
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

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert messages == [
            {"role": "system", "content": DEFAULT_CHAT_SYSTEM_PROMPT},
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


def test_chat_still_accepts_plain_json_without_files(chat_client, monkeypatch) -> None:
    login(chat_client)

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert messages == [
            {"role": "system", "content": DEFAULT_CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": "plain"},
        ]
        yield "plain-ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "plain"}]},
    )

    assert response.status_code == 200
    assert response.text == "plain-ok"


def test_chat_persists_messages_to_owned_conversation(chat_client, monkeypatch) -> None:
    session_token = login(chat_client)
    owner_session_id = get_owner_session_id(session_token)
    owner_user_id = get_owner_user_id(session_token)

    with SessionLocal() as db:
        conversation = Conversation(
            title="Cloud thread",
            owner_session_id=owner_session_id,
            owner_user_id=owner_user_id,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        conversation_id = conversation.id

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        yield "cloud"
        yield " reply"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "hello cloud"},
            ],
            "conversationId": str(conversation_id),
        },
    )

    assert response.status_code == 200
    assert response.text == "cloud reply"

    with SessionLocal() as db:
        stored_conversation = db.get(Conversation, conversation_id)
        assert stored_conversation is not None
        assert [message.role for message in stored_conversation.messages] == [
            "user",
            "assistant",
        ]
        assert [message.content for message in stored_conversation.messages] == [
            "hello cloud",
            "cloud reply",
        ]


def test_chat_rejects_malformed_json_body_with_controlled_error(chat_client) -> None:
    login(chat_client)

    response = chat_client.post(
        "/api/chat",
        content='{"messages": [',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Malformed JSON body."}


def test_chat_persists_uploaded_attachment_references_for_conversation_history(
    chat_client, create_user, monkeypatch
) -> None:
    user = create_user(username="alice_attach", password="StrongPass123!")
    login_user(chat_client, username="alice_attach", password="StrongPass123!")

    with SessionLocal() as db:
        conversation = Conversation(
            title="Attachment persistence",
            owner_session_id=0,
            owner_user_id=user.id,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        conversation_id = conversation.id

    async def fake_stream_chat_completion(messages, model=None):
        yield "done"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        data={
            "messages": json.dumps(
                {
                    "model": "deepseek-v4-flash",
                    "conversationId": str(conversation_id),
                    "messages": [
                        {
                            "role": "user",
                            "content": "read this file",
                            "attachments": [
                                {
                                    "id": "attachment-1",
                                    "name": "notes.txt",
                                    "type": "Text",
                                    "size": 5,
                                }
                            ],
                        }
                    ],
                }
            )
        },
        files={
            "files": ("notes.txt", b"hello", "text/plain"),
        },
    )

    assert response.status_code == 200
    assert response.text.endswith("done")

    with SessionLocal() as db:
        messages = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.id.asc())
            .all()
        )
        assert [message.role for message in messages] == ["user", "assistant"]
        assert len(messages[0].attachments) == 1
        assert messages[0].attachments[0].attachment_id == "attachment-1"
        assert messages[0].attachments[0].name == "notes.txt"


def test_chat_rejects_malformed_multipart_messages_json_with_controlled_error(chat_client) -> None:
    login(chat_client)

    response = chat_client.post(
        "/api/chat",
        data={"messages": '[{"role":"user","content":"broken"}'},
        files={
            "files": ("notes.txt", b"alpha file content", "text/plain"),
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Malformed JSON body."}


def test_chat_accepts_multipart_messages_with_text_attachment(chat_client, monkeypatch) -> None:
    login(chat_client)

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": DEFAULT_CHAT_SYSTEM_PROMPT}
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"].startswith("Please summarize the attachment")
        assert "[Attached files]" in messages[-1]["content"]
        assert "notes.txt" in messages[-1]["content"]
        assert "alpha file content" in messages[-1]["content"]
        yield "ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        data={
            "messages": '[{"role":"system","content":"System prompt"},{"role":"user","content":"Please summarize the attachment"}]',
        },
        files={
            "files": ("notes.txt", b"alpha file content", "text/plain"),
        },
    )

    assert response.status_code == 200
    assert response.text == "ok"


def test_chat_includes_pdf_attachment_text_in_last_user_message(chat_client, monkeypatch) -> None:
    login(chat_client)
    monkeypatch.setattr("app.attachments.extract_pdf_text", lambda _raw: "pdf body text")

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert "report.pdf" in messages[-1]["content"]
        assert "pdf body text" in messages[-1]["content"]
        yield "ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        data={"messages": '[{"role":"user","content":"璇诲彇 PDF"}]'},
        files={"files": ("report.pdf", b"%PDF-fake", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.text == "ok"


def test_chat_includes_docx_attachment_text_in_last_user_message(chat_client, monkeypatch) -> None:
    login(chat_client)
    monkeypatch.setattr("app.attachments.extract_docx_text", lambda _raw: "docx body text")

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert "doc.docx" in messages[-1]["content"]
        assert "docx body text" in messages[-1]["content"]
        yield "ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        data={"messages": '[{"role":"user","content":"璇诲彇 DOCX"}]'},
        files={
            "files": (
                "doc.docx",
                b"fake-docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        },
    )

    assert response.status_code == 200
    assert response.text == "ok"


def test_chat_includes_pptx_attachment_text_in_last_user_message(chat_client, monkeypatch) -> None:
    login(chat_client)
    monkeypatch.setattr("app.attachments.extract_pptx_text", lambda _raw: "pptx slide text")

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert "slides.pptx" in messages[-1]["content"]
        assert "pptx slide text" in messages[-1]["content"]
        yield "ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        data={"messages": '[{"role":"user","content":"读取 PPTX"}]'},
        files={
            "files": (
                "slides.pptx",
                b"fake-pptx",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ),
        },
    )

    assert response.status_code == 200
    assert response.text == "\u001e__CIPHER_KEEPALIVE__\u001eok"


def test_chat_includes_ppt_attachment_text_in_last_user_message(chat_client, monkeypatch) -> None:
    login(chat_client)
    monkeypatch.setattr("app.attachments.extract_binary_text", lambda _raw: "ppt binary text")

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert "slides.ppt" in messages[-1]["content"]
        assert "ppt binary text" in messages[-1]["content"]
        yield "ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        data={"messages": '[{"role":"user","content":"读取 PPT"}]'},
        files={
            "files": (
                "slides.ppt",
                b"fake-ppt",
                "application/vnd.ms-powerpoint",
            ),
        },
    )

    assert response.status_code == 200
    assert response.text == "ok"


def test_chat_uses_native_vision_payload_for_chatgpt_image_attachments(
    chat_client,
    monkeypatch,
) -> None:
    login(chat_client)

    def fail_if_ocr_called(_raw):
        raise AssertionError("ChatGPT image uploads should not require OCR extraction.")

    monkeypatch.setattr("app.attachments.extract_image_text", fail_if_ocr_called)

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "chatgpt-5.5-official"
        assert messages == [
            {
                "role": "system",
                "content": DEFAULT_CHAT_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请描述这张图"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,ZmFrZS1pbWFnZQ=="},
                    },
                ],
            }
        ]
        yield "vision-ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        data={
            "messages": '{"model":"chatgpt-5.5-official","messages":[{"role":"user","content":"请描述这张图"}]}',
        },
        files={"files": ("shot.png", b"fake-image", "image/png")},
    )

    assert response.status_code == 200
    assert response.text == "vision-ok"


def test_chat_uses_native_vision_payload_for_claude_image_attachments(
    chat_client,
    monkeypatch,
) -> None:
    login(chat_client)

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "claude-opus-4-7-official"
        assert messages[0] == {"role": "system", "content": DEFAULT_CHAT_SYSTEM_PROMPT}
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == [
            {"type": "text", "text": "\u8bf7\u5206\u6790\u56fe\u7247"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,ZmFrZS1pbWFnZQ=="},
            },
        ]
        yield "claude-vision-ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        data={
            "messages": '{"model":"claude-opus-4-7-official","messages":[{"role":"system","content":"你是一个视觉助手"},{"role":"user","content":"请分析图片"}]}',
        },
        files={"files": ("shot.png", b"fake-image", "image/png")},
    )

    assert response.status_code == 200
    assert response.text == "claude-vision-ok"


def test_chat_keeps_ocr_flow_for_deepseek_image_attachments(chat_client, monkeypatch) -> None:
    login(chat_client)
    monkeypatch.setattr("app.attachments.extract_image_text", lambda _raw: "OCR text")

    async def fake_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
        assert messages[-1]["role"] == "user"
        assert isinstance(messages[-1]["content"], str)
        assert "[Attached files]" in messages[-1]["content"]
        assert "shot.png" in messages[-1]["content"]
        assert "OCR text" in messages[-1]["content"]
        yield "deepseek-ok"

    monkeypatch.setattr(
        "app.routes.chat.stream_chat_completion",
        fake_stream_chat_completion,
    )

    response = chat_client.post(
        "/api/chat",
        data={
            "messages": '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"璇诲彇鍥剧墖"}]}',
        },
        files={"files": ("shot.png", b"fake-image", "image/png")},
    )

    assert response.status_code == 200
    assert response.text == "deepseek-ok"


def test_chat_rejects_image_when_ocr_extracts_no_text(chat_client, monkeypatch) -> None:
    login(chat_client)
    monkeypatch.setattr("app.attachments.extract_image_text", lambda _raw: "")

    response = chat_client.post(
        "/api/chat",
        data={"messages": '[{"role":"user","content":"璇诲彇鍥剧墖"}]'},
        files={"files": ("shot.png", b"fake-image", "image/png")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "No readable text could be extracted from image: shot.png"
    }


def test_chat_rejects_unsupported_attachment_extension(chat_client) -> None:
    login(chat_client)

    response = chat_client.post(
        "/api/chat",
        data={
            "messages": '[{"role":"user","content":"请读取附件"}]',
        },
        files={
            "files": ("archive.zip", b"PK", "application/zip"),
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported file type: archive.zip"}


def test_chat_rejects_more_than_ten_files(chat_client) -> None:
    login(chat_client)

    files = [
        ("files", (f"file-{index}.txt", b"x", "text/plain"))
        for index in range(11)
    ]

    response = chat_client.post(
        "/api/chat",
        data={
            "messages": '[{"role":"user","content":"too many"}]',
        },
        files=files,
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Too many files. Maximum 10 files are allowed per request."
    }


def test_chat_surfaces_upstream_errors_for_authenticated_session(chat_client, monkeypatch) -> None:
    login(chat_client)

    async def failing_stream_chat_completion(messages, model=None):
        assert model == "deepseek-v4-flash"
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

    assert response.status_code == 200
    assert (
        response.text
        == "\u001e__CIPHER_KEEPALIVE__\u001e\u001e__CIPHER_ERROR__:DeepSeek upstream returned 401 Unauthorized\u001e"
    )


def test_chat_surfaces_synchronous_upstream_errors_for_authenticated_session(
    chat_client, monkeypatch
) -> None:
    login(chat_client)

    def failing_stream_chat_completion(messages, model=None):
        del messages, model
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





