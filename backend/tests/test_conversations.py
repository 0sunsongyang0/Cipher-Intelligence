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


def test_conversation_can_be_renamed_pinned_and_archived(client, create_user) -> None:
    create_user(username="alice", password="StrongPass123!")
    login(client, username="alice", password="StrongPass123!")
    created = client.post("/api/conversations", json={"title": "Initial title"}).json()

    renamed = client.patch(
        f"/api/conversations/{created['id']}",
        json={"title": "  Incident 42  ", "isPinned": True},
    )
    archived = client.patch(
        f"/api/conversations/{created['id']}",
        json={"isArchived": True},
    )
    case_updated = client.patch(
        f"/api/conversations/{created['id']}",
        json={
            "caseStatus": "investigating",
            "severity": "high",
            "assignee": "SOC \u4e00\u7ebf",
            "tags": ["\u6076\u610f\u8f6f\u4ef6", "\u9ad8\u4f18\u5148\u7ea7"],
            "caseSummary": "\u5df2\u786e\u8ba4\u6837\u672c\u5b58\u5728\u6301\u4e45\u5316\u884c\u4e3a\u3002",
        },
    )

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Incident 42"
    assert renamed.json()["is_pinned"] is True
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True
    assert archived.json()["is_pinned"] is False
    assert case_updated.status_code == 200
    assert case_updated.json()["case_status"] == "investigating"
    assert case_updated.json()["severity"] == "high"
    assert case_updated.json()["assignee"] == "SOC \u4e00\u7ebf"
    assert case_updated.json()["tags"] == ["\u6076\u610f\u8f6f\u4ef6", "\u9ad8\u4f18\u5148\u7ea7"]
    assert case_updated.json()["case_summary"] == "\u5df2\u786e\u8ba4\u6837\u672c\u5b58\u5728\u6301\u4e45\u5316\u884c\u4e3a\u3002"


def test_conversation_update_is_scoped_to_owner(client, create_user, create_conversation_for_user) -> None:
    alice = create_user(username="alice", password="StrongPass123!")
    create_user(username="bob", password="StrongPass456!")
    conversation = create_conversation_for_user(user=alice, title="Alice only")
    login(client, username="bob", password="StrongPass456!")

    response = client.patch(
        f"/api/conversations/{conversation.id}",
        json={"title": "Stolen"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


def test_import_conversation_persists_legacy_local_history(client, create_user) -> None:
    create_user(username="alice", password="StrongPass123!")
    login(client, username="alice", password="StrongPass123!")

    response = client.post(
        "/api/conversations/import",
        json={
            "title": "Legacy local thread",
            "messages": [
                {"role": "user", "content": "Old local hello"},
                {"role": "assistant", "content": "Old local hi"},
            ],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Legacy local thread"
    assert payload["importedMessages"] == 2

    with SessionLocal() as db:
        stored = db.get(Conversation, payload["id"])
        assert stored is not None
        assert stored.owner_user_id is not None
        assert [message.role for message in stored.messages] == ["user", "assistant"]
        assert [message.content for message in stored.messages] == [
            "Old local hello",
            "Old local hi",
        ]


def test_conversation_message_history_includes_persisted_attachment_references(
    client, create_user
) -> None:
    create_user(username="alice", password="StrongPass123!")
    login(client, username="alice", password="StrongPass123!")

    import_response = client.post(
        "/api/conversations/import",
        json={
            "title": "Attachment thread",
            "messages": [
                {
                    "role": "user",
                    "content": "请看这个文件",
                    "attachments": [
                        {
                            "id": "attachment-1",
                            "name": "notes.txt",
                            "type": "TXT",
                            "size": 5,
                            "meta": "引用文件",
                        }
                    ],
                },
                {"role": "assistant", "content": "好的"},
            ],
        },
    )

    assert import_response.status_code == 201
    conversation_id = import_response.json()["id"]

    messages_response = client.get(f"/api/conversations/{conversation_id}/messages")

    assert messages_response.status_code == 200
    assert messages_response.json()["items"][0]["attachments"] == [
        {
            "id": "attachment-1",
            "name": "notes.txt",
            "type": "TXT",
            "size": 5,
            "meta": "引用文件",
        }
    ]
