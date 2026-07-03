from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

LEGACY_OWNER_SESSION_ID = 0


def _ensure_sqlite_directory(database_url: str) -> None:
    sqlite_prefix = "sqlite:///"
    if not database_url.startswith(sqlite_prefix):
        return

    database_path = database_url.removeprefix(sqlite_prefix)
    if database_path == ":memory:":
        return

    Path(database_path).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_directory(settings.database_url)


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _migrate_sqlite_conversations_owner_session_id() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as connection:
        conversations_exists = (
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'conversations'"
            ).fetchone()
            is not None
        )
        if not conversations_exists:
            return

        rows = connection.exec_driver_sql("PRAGMA table_info(conversations)").fetchall()
        if any(row[1] == "owner_session_id" for row in rows):
            return

        connection.exec_driver_sql(
            f"ALTER TABLE conversations ADD COLUMN owner_session_id INTEGER NOT NULL DEFAULT {LEGACY_OWNER_SESSION_ID}"
        )


def init_db() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_conversations_owner_session_id()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()