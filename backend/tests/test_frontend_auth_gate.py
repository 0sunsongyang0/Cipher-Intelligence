from pathlib import Path
import importlib


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


def test_fastapi_docs_routes_are_not_public_without_auth(client) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = client.get(path, follow_redirects=False)

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


def test_exact_api_path_is_not_swallowed_by_frontend_spa_fallback(client) -> None:
    response = client.get("/api", follow_redirects=False)

    assert response.status_code == 404


def test_known_api_path_with_wrong_method_preserves_fastapi_405(client) -> None:
    response = client.get("/api/auth/login", follow_redirects=False)

    assert response.status_code == 405


def test_non_get_api_paths_are_not_swallowed_by_frontend_spa_fallback(client) -> None:
    response = client.post("/api/not-a-real-endpoint", follow_redirects=False)

    assert response.status_code == 404


def test_app_creation_skips_assets_mount_when_built_assets_are_absent(monkeypatch) -> None:
    main_module = importlib.import_module("app.main")
    monkeypatch.setattr(main_module, "FRONTEND_ASSETS_DIR", Path("frontend/dist/missing-assets"))

    app = main_module.create_app()

    assert not any(getattr(route, "path", None) == "/assets" for route in app.routes)
