from sqlalchemy import select

from app.auth import hash_password
from app.config import settings
from app.database import SessionLocal
from app.models import Conversation, Message
from app.models import User


def login(client, *, username: str, password: str) -> None:
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if user is None:
            db.add(User(username=username, password_hash=hash_password(password)))
            db.commit()
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def test_conversations_require_logged_in_user_session(client) -> None:
    response = client.post("/api/auth/login", json={"password": settings.app_access_password})
    assert response.status_code == 200

    create_response = client.post("/api/conversations", json={"title": "Legacy conversation"})
    list_response = client.get("/api/conversations")

    assert create_response.status_code == 401
    assert create_response.json() == {"detail": "User authentication required"}
    assert list_response.status_code == 401
    assert list_response.json() == {"detail": "User authentication required"}


def test_conversations_collection_is_available_for_authenticated_users(client, create_user) -> None:
    create_user(username="alice", password="StrongPass123!")
    login(client, username="alice", password="StrongPass123!")

    create_response = client.post("/api/conversations", json={"title": "New conversation 09:00"})
    list_response = client.get("/api/conversations")

    assert create_response.status_code == 201
    assert create_response.json()["title"] == "New conversation 09:00"
    assert list_response.status_code == 200
    assert [item["title"] for item in list_response.json()["items"]] == ["New conversation 09:00"]


def test_user_conversation_history_is_isolated_between_accounts(
    client, create_user, create_conversation_for_user
) -> None:
    alice = create_user(username="alice", password="StrongPass123!")
    create_user(username="bob", password="StrongPass456!")
    alice_conversation = create_conversation_for_user(
        user=alice,
        title="Alice thread",
        messages=[("user", "hello from alice")],
    )

    login(client, username="bob", password="StrongPass456!")

    response = client.get(f"/api/conversations/{alice_conversation.id}/messages")

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


def test_conversation_item_routes_only_expose_owned_user_data(
    client, create_user, create_conversation_for_user
) -> None:
    alice = create_user(username="alice", password="StrongPass123!")
    conversation = create_conversation_for_user(
        user=alice,
        title="Alice thread",
        messages=[("user", "hello"), ("assistant", "hi")],
    )

    login(client, username="alice", password="StrongPass123!")

    messages_response = client.get(f"/api/conversations/{conversation.id}/messages")
    delete_response = client.delete(f"/api/conversations/{conversation.id}")

    assert messages_response.status_code == 200
    assert [item["content"] for item in messages_response.json()["items"]] == ["hello", "hi"]
    assert delete_response.status_code == 204

    with SessionLocal() as db:
        assert db.get(Conversation, conversation.id) is None
        assert db.query(Message).filter(Message.conversation_id == conversation.id).count() == 0
