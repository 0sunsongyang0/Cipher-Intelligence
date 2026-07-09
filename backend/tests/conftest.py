import gc
import os
from pathlib import Path
import sys
import time

import pytest
from fastapi.testclient import TestClient
TEST_DATABASE_URL = "sqlite:///./backend/data/test.db"
TEST_DATABASE_PATH = Path("backend/data/test.db")

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password
from app.database import engine
from app.database import SessionLocal
from app.main import app
from app.models import Conversation, InviteCode, Message, User
from app.rate_limit import reset_failed_attempts


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


@pytest.fixture(autouse=True)
def isolate_prompt_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("app.prompt_config_store.PROMPT_CONFIG_PATH", tmp_path / "prompt-config.json")


@pytest.fixture()
def client():
    engine.dispose()
    _unlink_with_retry(TEST_DATABASE_PATH)
    reset_failed_attempts()

    with TestClient(app) as test_client:
        yield test_client

    reset_failed_attempts()
    engine.dispose()
    _unlink_with_retry(TEST_DATABASE_PATH)


@pytest.fixture()
def create_user():
    def _create_user(
        *,
        username: str,
        password: str,
        is_admin: bool = False,
        is_active: bool = True,
    ) -> User:
        with SessionLocal() as db:
            user = User(
                username=username,
                password_hash=hash_password(password),
                is_admin=is_admin,
                is_active=is_active,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            db.expunge(user)
            return user

    return _create_user


@pytest.fixture()
def create_conversation_for_user():
    def _create_conversation_for_user(
        *,
        user: User,
        title: str,
        messages: list[tuple[str, str]] | None = None,
    ) -> Conversation:
        with SessionLocal() as db:
            conversation = Conversation(
                title=title,
                owner_session_id=0,
                owner_user_id=user.id,
            )
            db.add(conversation)
            db.flush()

            for role, content in messages or []:
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        role=role,
                        content=content,
                    )
                )

            db.commit()
            db.refresh(conversation)
            db.expunge(conversation)
            return conversation

    return _create_conversation_for_user


@pytest.fixture()
def create_invite_code():
    def _create_invite_code(
        *,
        code: str,
        label: str = "",
        is_active: bool = True,
        max_uses: int | None = None,
        used_count: int = 0,
    ) -> InviteCode:
        with SessionLocal() as db:
            invite_code = InviteCode(
                code=code,
                label=label,
                is_active=is_active,
                max_uses=max_uses,
                used_count=used_count,
            )
            db.add(invite_code)
            db.commit()
            db.refresh(invite_code)
            db.expunge(invite_code)
            return invite_code

    return _create_invite_code
