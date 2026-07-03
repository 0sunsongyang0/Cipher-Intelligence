def test_create_and_list_conversations(client) -> None:
    create_response = client.post("/api/conversations", json={"title": "新对话 09:00"})
    assert create_response.status_code == 201

    list_response = client.get("/api/conversations")
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["title"] == "新对话 09:00"


def test_delete_conversation(client) -> None:
    create_response = client.post("/api/conversations", json={"title": "可删除会话"})
    conversation_id = create_response.json()["id"]

    delete_response = client.delete(f"/api/conversations/{conversation_id}")
    assert delete_response.status_code == 204

    list_response = client.get("/api/conversations")
    assert list_response.json()["items"] == []
