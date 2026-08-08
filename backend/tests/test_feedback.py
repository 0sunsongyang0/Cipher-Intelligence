from sqlalchemy import select

from app.database import SessionLocal
from app.models import Message, MessageFeedback


def login(client, *, username: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def assistant_message_id(conversation_id: int) -> int:
    with SessionLocal() as db:
        return db.execute(
            select(Message.id).where(
                Message.conversation_id == conversation_id,
                Message.role == "assistant",
            )
        ).scalar_one()


def test_feedback_can_be_created_updated_and_removed(
    client, create_user, create_conversation_for_user
) -> None:
    user = create_user(username="feedback-user", password="StrongPass123!")
    conversation = create_conversation_for_user(
        user=user,
        title="Feedback",
        messages=[("assistant", "Investigate this result")],
    )
    message_id = assistant_message_id(conversation.id)
    login(client, username=user.username, password="StrongPass123!")

    created = client.put(
        f"/api/messages/{message_id}/feedback",
        json={"rating": "down", "reason": "factual_error", "note": "Wrong IOC"},
    )
    assert created.status_code == 200
    assert created.json() == {
        "messageId": message_id,
        "rating": "down",
        "reason": "factual_error",
    }

    updated = client.put(f"/api/messages/{message_id}/feedback", json={"rating": "up"})
    assert updated.status_code == 200
    assert updated.json() == {"messageId": message_id, "rating": "up", "reason": None}

    removed = client.put(f"/api/messages/{message_id}/feedback", json={"rating": None})
    assert removed.status_code == 200
    with SessionLocal() as db:
        assert db.execute(select(MessageFeedback)).scalar_one_or_none() is None


def test_downvote_requires_reason(client, create_user, create_conversation_for_user) -> None:
    user = create_user(username="reason-user", password="StrongPass123!")
    conversation = create_conversation_for_user(
        user=user, title="Reason", messages=[("assistant", "Answer")]
    )
    login(client, username=user.username, password="StrongPass123!")

    response = client.put(
        f"/api/messages/{assistant_message_id(conversation.id)}/feedback",
        json={"rating": "down"},
    )
    assert response.status_code == 422


def test_feedback_rejects_messages_owned_by_another_user(
    client, create_user, create_conversation_for_user
) -> None:
    owner = create_user(username="feedback-owner", password="StrongPass123!")
    other = create_user(username="feedback-other", password="StrongPass123!")
    conversation = create_conversation_for_user(
        user=owner, title="Private", messages=[("assistant", "Private answer")]
    )
    login(client, username=other.username, password="StrongPass123!")

    response = client.put(
        f"/api/messages/{assistant_message_id(conversation.id)}/feedback",
        json={"rating": "up"},
    )
    assert response.status_code == 404
