def login(client) -> None:
    response = client.post("/api/auth/login", json={"password": "change-me"})
    assert response.status_code == 200


def test_conversations_collection_is_not_available_from_primary_app(client) -> None:
    login(client)

    create_response = client.post("/api/conversations", json={"title": "New conversation 09:00"})
    list_response = client.get("/api/conversations")

    assert create_response.status_code == 404
    assert create_response.json() == {"detail": "Not Found"}
    assert list_response.status_code == 404
    assert list_response.json() == {"detail": "Not Found"}


def test_conversation_item_routes_are_not_available_from_primary_app(client) -> None:
    login(client)

    messages_response = client.get("/api/conversations/1/messages")
    delete_response = client.delete("/api/conversations/1")

    assert messages_response.status_code == 404
    assert messages_response.json() == {"detail": "Not Found"}
    assert delete_response.status_code == 404
    assert delete_response.json() == {"detail": "Not Found"}
