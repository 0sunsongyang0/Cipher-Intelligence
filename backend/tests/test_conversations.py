def login(client) -> None:
    response = client.post(
        "/api/auth/login",
        json={"password": "change-me"},
        headers={"X-Forwarded-For": "test-conversations"},
    )
    assert response.status_code == 200


def test_create_and_list_conversations(client) -> None:
    login(client)

    create_response = client.post("/api/conversations", json={"title": "New conversation 09:00"})
    assert create_response.status_code == 201

    list_response = client.get("/api/conversations")
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["title"] == "New conversation 09:00"


def test_delete_conversation(client) -> None:
    login(client)

    create_response = client.post("/api/conversations", json={"title": "Deletable conversation"})
    conversation_id = create_response.json()["id"]

    delete_response = client.delete(f"/api/conversations/{conversation_id}")
    assert delete_response.status_code == 204

    list_response = client.get("/api/conversations")
    assert list_response.json()["items"] == []
