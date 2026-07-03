import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database_module


def login(client) -> str:
    response = client.post("/api/auth/login", json={"password": "change-me"})
    assert response.status_code == 200


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

        indexes = {
            row[1]: row for row in connection.execute("PRAGMA index_list(conversations)").fetchall()
        }
        assert "ix_conversations_owner_session_id" in indexes


def test_init_db_repairs_missing_owner_session_id_index_when_column_already_exists(
    tmp_path, monkeypatch
) -> None:
    intermediate_db_path = tmp_path / "intermediate.db"

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
            (1, "Intermediate conversation", "2026-07-03T00:00:00+00:00", "2026-07-03T00:00:00+00:00", 0),
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
            row[1]: row for row in connection.execute("PRAGMA index_list(conversations)").fetchall()
        }
        assert "ix_conversations_owner_session_id" in indexes
        assert connection.execute(
            "SELECT owner_session_id FROM conversations WHERE id = 1"
        ).fetchone()[0] == 0


def test_server_chat_route_is_not_mounted_in_primary_app(client) -> None:
    login(client)

    response = client.post("/api/chat", json={"conversation_id": 1, "content": "hello"})

    assert response.status_code in {404, 410}
    if response.status_code == 404:
        assert response.json() == {"detail": "Not Found"}


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
