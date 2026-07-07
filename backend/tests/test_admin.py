import importlib
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp

import pytest
from fastapi.testclient import TestClient

from app.config import settings


@pytest.fixture()
def tmp_path():
    base_dir = Path(".pytest-tmp")
    base_dir.mkdir(exist_ok=True)
    temp_dir = Path(mkdtemp(dir=base_dir))

    try:
        yield temp_dir
    finally:
        rmtree(temp_dir, ignore_errors=True)


@pytest.fixture()
def chat_client(client, monkeypatch, tmp_path):
    del client
    frontend_module = importlib.import_module("app.routes.frontend")
    main_module = importlib.import_module("app.main")
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text(
        '<!doctype html><div id="root"></div><script type="module" src="/assets/index.js"></script>',
        encoding="utf-8",
    )
    (assets_dir / "index.js").write_text("console.log('admin test shell');", encoding="utf-8")

    monkeypatch.setattr(frontend_module, "FRONTEND_INDEX_PATH", dist_dir / "index.html")
    monkeypatch.setattr(main_module, "FRONTEND_ASSETS_DIR", assets_dir)

    with TestClient(main_module.create_app()) as test_client:
        yield test_client


def login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"password": settings.app_access_password})
    assert response.status_code == 200


def test_admin_spa_denies_remote_authenticated_requests(chat_client: TestClient) -> None:
    login(chat_client)

    response = chat_client.get("/admin", headers={"X-Forwarded-For": "10.33.233.152"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin is available only from this machine."}


def test_admin_spa_allows_loopback_authenticated_requests(chat_client: TestClient) -> None:
    login(chat_client)

    response = chat_client.get("/admin", headers={"host": "127.0.0.1:8000"})

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_admin_api_denies_remote_requests_even_with_session(chat_client: TestClient) -> None:
    login(chat_client)

    response = chat_client.get("/api/admin/overview", headers={"X-Forwarded-For": "104.28.0.1"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin is available only from this machine."}
