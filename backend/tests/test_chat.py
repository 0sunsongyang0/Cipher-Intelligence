import sqlite3

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.database as database_module
import app.deepseek as deepseek_module
from app.auth import COOKIE_NAME
from app.database import SessionLocal
from app.models import Conversation
from app.routes import chat as chat_module


ASSISTANT_RESPONSE = "\u4f60\u597d\uff0c\u8fd9\u91cc\u662f\u5154\u5154\u70b8\u5f39\u7684\u5927\u6a21\u578b\u52a9\u624b\u3002"
PARTIAL_ASSISTANT_RESPONSE = "\u4f60\u597d\uff0c"
USER_MESSAGE = "\u4f60\u662f\u8c01\uff1f"


def login(client) -> str:
    response = client.post("/api/auth/login", json={"password": "change-me"})
    assert response.status_code == 200
    return response.cookies[COOKIE_NAME]


def create_conversation(client, title: str = "Chat conversation") -> int:
    response = client.post("/api/conversations", json={"title": title})
    assert response.status_code == 201
    return response.json()["id"]


def test_init_db_migrates_existing_conversations_table_with_owner_session_id(
    tmp_path, monkeypatch
) -> None:
    legacy_db_path = tmp_path / "legacy.db"

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
            row[1]: row for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
        }
        assert "owner_session_id" in columns
        assert columns["owner_session_id"][3] == 1
        assert connection.execute(
            "SELECT owner_session_id FROM conversations WHERE id = 1"
        ).fetchone()[0] == 0


def test_parse_chunk_content_handles_deepseek_data_lines() -> None:
    assert hasattr(deepseek_module, "parse_chunk_content")

    parse_chunk_content = deepseek_module.parse_chunk_content

    assert parse_chunk_content("event: ping") is None
    assert parse_chunk_content("data: [DONE]") is None
    assert parse_chunk_content('data: {"choices":[{"delta":{}}]}') is None
    assert (
        parse_chunk_content('data: {"choices":[{"delta":{"content":"\u4f60\u597d"}}]}')
        == "\u4f60\u597d"
    )


def test_chat_streams_response_and_persists_message_history(client, monkeypatch) -> None:
    async def fake_stream_chat_completion(_messages):
        for chunk in ["\u4f60\u597d\uff0c", "\u8fd9\u91cc\u662f\u5154\u5154\u70b8\u5f39\u7684\u5927\u6a21\u578b\u52a9\u624b\u3002"]:
            yield chunk

    monkeypatch.setattr(chat_module, "stream_chat_completion", fake_stream_chat_completion)

    login(client)
    conversation_id = create_conversation(client)

    chat_response = client.post(
        "/api/chat",
        json={"conversation_id": conversation_id, "content": USER_MESSAGE},
    )

    assert chat_response.status_code == 200
    assert chat_response.text == ASSISTANT_RESPONSE

    messages_response = client.get(f"/api/conversations/{conversation_id}/messages")

    assert messages_response.status_code == 200
    assert messages_response.json()["items"] == [
        {
            "id": 1,
            "conversation_id": conversation_id,
            "role": "user",
            "content": USER_MESSAGE,
            "created_at": messages_response.json()["items"][0]["created_at"],
        },
        {
            "id": 2,
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": ASSISTANT_RESPONSE,
            "created_at": messages_response.json()["items"][1]["created_at"],
        },
    ]

    with SessionLocal() as db:
        conversation = db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        ).scalar_one()
        assert conversation.owner_session_id is not None


def test_conversation_access_is_scoped_to_owning_session(client, monkeypatch) -> None:
    async def fake_stream_chat_completion(_messages):
        yield ASSISTANT_RESPONSE

    monkeypatch.setattr(chat_module, "stream_chat_completion", fake_stream_chat_completion)

    owner_token = login(client)
    conversation_id = create_conversation(client, title="Owner conversation")

    client.cookies.clear()
    login(client)

    list_response = client.get("/api/conversations")
    assert list_response.status_code == 200
    assert list_response.json()["items"] == []

    messages_response = client.get(f"/api/conversations/{conversation_id}/messages")
    assert messages_response.status_code == 404

    chat_response = client.post(
        "/api/chat",
        json={"conversation_id": conversation_id, "content": USER_MESSAGE},
    )
    assert chat_response.status_code == 404

    delete_response = client.delete(f"/api/conversations/{conversation_id}")
    assert delete_response.status_code == 404

    client.cookies.set(COOKIE_NAME, owner_token)
    owner_messages_response = client.post(
        "/api/chat",
        json={"conversation_id": conversation_id, "content": USER_MESSAGE},
    )
    assert owner_messages_response.status_code == 200


def test_chat_persists_partial_assistant_content_when_stream_fails(client, monkeypatch) -> None:
    async def failing_stream_chat_completion(_messages):
        yield PARTIAL_ASSISTANT_RESPONSE
        raise RuntimeError("upstream stream failed")

    monkeypatch.setattr(chat_module, "stream_chat_completion", failing_stream_chat_completion)

    login(client)
    conversation_id = create_conversation(client, title="Failure conversation")

    with pytest.raises(RuntimeError, match="upstream stream failed"):
        with client.stream(
            "POST",
            "/api/chat",
            json={"conversation_id": conversation_id, "content": USER_MESSAGE},
        ) as response:
            assert response.status_code == 200
            for _ in response.iter_text():
                pass

    messages_response = client.get(f"/api/conversations/{conversation_id}/messages")

    assert messages_response.status_code == 200
    assert messages_response.json()["items"] == [
        {
            "id": 1,
            "conversation_id": conversation_id,
            "role": "user",
            "content": USER_MESSAGE,
            "created_at": messages_response.json()["items"][0]["created_at"],
        },
        {
            "id": 2,
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": PARTIAL_ASSISTANT_RESPONSE,
            "created_at": messages_response.json()["items"][1]["created_at"],
        },
    ]