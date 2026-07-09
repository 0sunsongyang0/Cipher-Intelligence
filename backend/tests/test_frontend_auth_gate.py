from pathlib import Path
import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.config import settings
from app.database import SessionLocal
from app.models import User


@pytest.fixture()
def frontend_client(client, monkeypatch, tmp_path):
    del client
    frontend_module = importlib.import_module("app.routes.frontend")
    main_module = importlib.import_module("app.main")
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    file_icons_dir = dist_dir / "file-icons" / "32px"
    assets_dir.mkdir(parents=True)
    file_icons_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text(
        '<!doctype html><div id="root"></div><script type="module" src="/assets/index.js"></script>',
        encoding="utf-8",
    )
    (assets_dir / "index.js").write_text("console.log('webllm test shell');", encoding="utf-8")
    (file_icons_dir / "zip.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc```\x00\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    monkeypatch.setattr(frontend_module, "FRONTEND_INDEX_PATH", dist_dir / "index.html")
    monkeypatch.setattr(main_module, "FRONTEND_ASSETS_DIR", assets_dir)
    monkeypatch.setattr(main_module, "FRONTEND_FILE_ICONS_DIR", dist_dir / "file-icons")

    with TestClient(main_module.create_app()) as test_client:
        yield test_client


def login(client, *, username: str, password: str) -> None:
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if user is None:
            db.add(User(username=username, password_hash=hash_password(password)))
            db.commit()
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def test_root_serves_spa_shell_without_auth(frontend_client) -> None:
    response = frontend_client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert '<div id="root"></div>' in response.text


def test_frontend_assets_are_served_without_auth(frontend_client) -> None:
    response = frontend_client.get("/assets/index.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_file_icons_are_served_as_images_without_auth(frontend_client) -> None:
    response = frontend_client.get("/file-icons/32px/zip.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert b'<div id="root"></div>' not in response.content


def test_chat_route_redirects_to_root_without_auth(frontend_client) -> None:
    response = frontend_client.get("/chat", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/"


def test_chat_route_rejects_legacy_anonymous_sessions(frontend_client) -> None:
    response = frontend_client.post(
        "/api/auth/login",
        json={"password": settings.app_access_password},
    )
    assert response.status_code == 200

    chat_response = frontend_client.get("/chat", follow_redirects=False)

    assert chat_response.status_code in {302, 307}
    assert chat_response.headers["location"] == "/"


def test_chat_route_serves_spa_shell_for_authenticated_users(
    frontend_client, create_user
) -> None:
    create_user(username="alice", password="StrongPass123!")
    login(frontend_client, username="alice", password="StrongPass123!")

    response = frontend_client.get("/chat")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert '<div id="root"></div>' in response.text


def test_nested_frontend_route_redirects_to_root_without_auth(frontend_client) -> None:
    response = frontend_client.get("/models/local-runtime", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/"


def test_fastapi_docs_routes_are_not_public_without_auth(frontend_client) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = frontend_client.get(path, follow_redirects=False)

        assert response.status_code in {302, 307}
        assert response.headers["location"] == "/"


def test_nested_frontend_route_serves_spa_shell_for_authenticated_users(
    frontend_client, create_user
) -> None:
    create_user(username="alice", password="StrongPass123!")
    login(frontend_client, username="alice", password="StrongPass123!")

    response = frontend_client.get("/models/local-runtime")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root"></div>' in response.text


def test_api_paths_are_not_swallowed_by_frontend_spa_fallback(frontend_client) -> None:
    response = frontend_client.get("/api/not-a-real-endpoint", follow_redirects=False)

    assert response.status_code == 404


def test_exact_api_path_is_not_swallowed_by_frontend_spa_fallback(frontend_client) -> None:
    response = frontend_client.get("/api", follow_redirects=False)

    assert response.status_code == 404


def test_known_api_path_with_wrong_method_preserves_fastapi_405(frontend_client) -> None:
    response = frontend_client.get("/api/auth/login", follow_redirects=False)

    assert response.status_code == 405


def test_non_get_api_paths_are_not_swallowed_by_frontend_spa_fallback(frontend_client) -> None:
    response = frontend_client.post("/api/not-a-real-endpoint", follow_redirects=False)

    assert response.status_code == 404


def test_app_creation_skips_assets_mount_when_built_assets_are_absent(monkeypatch) -> None:
    main_module = importlib.import_module("app.main")
    monkeypatch.setattr(main_module, "FRONTEND_ASSETS_DIR", Path("frontend/dist/missing-assets"))
    monkeypatch.setattr(
        main_module,
        "FRONTEND_FILE_ICONS_DIR",
        Path("frontend/dist/missing-file-icons"),
    )

    app = main_module.create_app()

    assert not any(getattr(route, "path", None) == "/assets" for route in app.routes)
    assert not any(getattr(route, "path", None) == "/file-icons" for route in app.routes)


def test_missing_frontend_index_returns_clear_service_error(client, monkeypatch, tmp_path) -> None:
    del client
    frontend_module = importlib.import_module("app.routes.frontend")
    main_module = importlib.import_module("app.main")
    missing_index = tmp_path / "missing-dist" / "index.html"

    monkeypatch.setattr(frontend_module, "FRONTEND_INDEX_PATH", missing_index)
    monkeypatch.setattr(main_module, "FRONTEND_ASSETS_DIR", tmp_path / "missing-dist" / "assets")
    monkeypatch.setattr(
        main_module,
        "FRONTEND_FILE_ICONS_DIR",
        tmp_path / "missing-dist" / "file-icons",
    )

    with TestClient(main_module.create_app()) as test_client:
        response = test_client.get("/")

    assert response.status_code == 503
    assert response.json() == {"detail": "Frontend build is not available."}
