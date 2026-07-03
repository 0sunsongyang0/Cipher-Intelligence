from pathlib import Path


def login(client) -> None:
    response = client.post("/api/auth/login", json={"password": "change-me"})
    assert response.status_code == 200


def test_root_serves_spa_shell_without_auth(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root"></div>' in response.text


def test_frontend_assets_are_served_without_auth(client) -> None:
    index_html = Path("frontend/dist/index.html").read_text(encoding="utf-8")
    asset_path = index_html.split('src="', maxsplit=1)[1].split('"', maxsplit=1)[0]

    response = client.get(asset_path)

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_chat_route_redirects_to_root_without_auth(client) -> None:
    response = client.get("/chat", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/"


def test_chat_route_serves_spa_shell_for_authenticated_sessions(client) -> None:
    login(client)

    response = client.get("/chat")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root"></div>' in response.text


def test_nested_frontend_route_redirects_to_root_without_auth(client) -> None:
    response = client.get("/models/local-runtime", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/"


def test_nested_frontend_route_serves_spa_shell_for_authenticated_sessions(client) -> None:
    login(client)

    response = client.get("/models/local-runtime")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root"></div>' in response.text


def test_api_paths_are_not_swallowed_by_frontend_spa_fallback(client) -> None:
    response = client.get("/api/not-a-real-endpoint", follow_redirects=False)

    assert response.status_code == 404
