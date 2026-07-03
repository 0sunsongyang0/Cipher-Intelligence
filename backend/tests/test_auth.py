def login(client, password: str = "change-me"):
    return client.post(
        "/api/auth/login",
        json={"password": password},
        headers={"X-Forwarded-For": "test-auth"},
    )


def test_login_sets_campus_session_cookie(client) -> None:
    response = login(client)

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    assert "campus_session" in response.cookies


def test_unauthenticated_conversations_request_returns_401(client) -> None:
    response = client.get("/api/conversations")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_session_status_reflects_login_and_logout(client) -> None:
    login_response = login(client)
    assert login_response.status_code == 200

    session_response = client.get("/api/auth/session")
    assert session_response.status_code == 200
    assert session_response.json() == {"authenticated": True}

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json() == {"authenticated": False}

    session_response = client.get("/api/auth/session")
    assert session_response.status_code == 200
    assert session_response.json() == {"authenticated": False}


def test_login_returns_429_after_five_failed_attempts(client) -> None:
    for _ in range(5):
        response = login(client, password="wrong-password")
        assert response.status_code == 401

    blocked_response = login(client, password="wrong-password")

    assert blocked_response.status_code == 429
