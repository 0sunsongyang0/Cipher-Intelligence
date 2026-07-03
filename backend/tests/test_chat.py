import importlib
import sys
from types import ModuleType


ASSISTANT_RESPONSE = "\u4f60\u597d\uff0c\u8fd9\u91cc\u662f\u5154\u5154\u70b8\u5f39\u7684\u5927\u6a21\u578b\u52a9\u624b\u3002"
USER_MESSAGE = "\u4f60\u662f\u8c01\uff1f"


def login(client) -> None:
    response = client.post("/api/auth/login", json={"password": "change-me"})
    assert response.status_code == 200


def ensure_chat_module() -> ModuleType:
    try:
        return importlib.import_module("app.routes.chat")
    except ModuleNotFoundError:
        chat_module = ModuleType("app.routes.chat")
        sys.modules["app.routes.chat"] = chat_module
        return chat_module


def test_chat_streams_response_and_persists_message_history(client, monkeypatch) -> None:
    async def fake_stream_chat_completion(_messages):
        for chunk in ["\u4f60\u597d\uff0c", "\u8fd9\u91cc\u662f\u5154\u5154\u70b8\u5f39\u7684\u5927\u6a21\u578b\u52a9\u624b\u3002"]:
            yield chunk

    chat_module = ensure_chat_module()
    monkeypatch.setattr(
        chat_module,
        "stream_chat_completion",
        fake_stream_chat_completion,
        raising=False,
    )

    login(client)

    create_response = client.post("/api/conversations", json={"title": "Chat conversation"})
    assert create_response.status_code == 201
    conversation_id = create_response.json()["id"]

    chat_response = client.post(
        "/api/chat",
        json={"conversation_id": conversation_id, "message": USER_MESSAGE},
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