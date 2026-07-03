from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


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


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
