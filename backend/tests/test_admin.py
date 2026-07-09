import importlib
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import DEFAULT_CHAT_SYSTEM_PROMPT, settings
from app.database import engine
from app.database import SessionLocal
from app.models import InviteCode
from app.rate_limit import reset_failed_attempts

TEST_DATABASE_PATH = Path("backend/data/test.db")


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
def admin_client(monkeypatch, tmp_path):
    engine.dispose()
    TEST_DATABASE_PATH.unlink(missing_ok=True)
    reset_failed_attempts()
    admin_frontend_module = importlib.import_module("app.routes.admin_frontend")
    admin_main_module = importlib.import_module("app.admin_main")
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "admin.html").write_text(
        '<!doctype html><div id="root"></div><script type="module" src="/assets/admin.js"></script>',
        encoding="utf-8",
    )
    (assets_dir / "admin.js").write_text("console.log('admin shell');", encoding="utf-8")

    monkeypatch.setattr(admin_frontend_module, "ADMIN_FRONTEND_INDEX_PATH", dist_dir / "admin.html")
    monkeypatch.setattr(admin_frontend_module, "FRONTEND_ASSETS_DIR", assets_dir)
    monkeypatch.setattr(admin_main_module, "FRONTEND_ASSETS_DIR", assets_dir)

    with TestClient(admin_main_module.create_app()) as client:
        yield client
    reset_failed_attempts()
    engine.dispose()
    TEST_DATABASE_PATH.unlink(missing_ok=True)


def login_as_user(client: TestClient, *, username: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def login_as_legacy_session(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"password": settings.app_access_password})
    assert response.status_code == 200


def test_admin_shell_requires_authentication(admin_client: TestClient) -> None:
    response = admin_client.get("/")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_admin_shell_rejects_legacy_anonymous_session(admin_client: TestClient) -> None:
    login_as_legacy_session(admin_client)

    response = admin_client.get("/")

    assert response.status_code == 401
    assert response.json() == {"detail": "User authentication required"}


def test_admin_shell_rejects_non_admin_user(admin_client: TestClient, create_user) -> None:
    create_user(username="member", password="member-pass-1")
    login_as_user(admin_client, username="member", password="member-pass-1")

    response = admin_client.get("/")

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}


def test_admin_shell_serves_dedicated_frontend_for_admin_user(
    admin_client: TestClient, create_user
) -> None:
    create_user(username="admin", password="admin-pass-1", is_admin=True)
    login_as_user(admin_client, username="admin", password="admin-pass-1")

    response = admin_client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_admin_overview_requires_authentication(admin_client: TestClient) -> None:
    response = admin_client.get("/api/admin/overview")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_admin_overview_rejects_legacy_anonymous_session(admin_client: TestClient) -> None:
    login_as_legacy_session(admin_client)

    response = admin_client.get("/api/admin/overview")

    assert response.status_code == 401
    assert response.json() == {"detail": "User authentication required"}


def test_admin_overview_rejects_non_admin_user(admin_client: TestClient, create_user) -> None:
    create_user(username="member", password="member-pass-1")
    login_as_user(admin_client, username="member", password="member-pass-1")

    response = admin_client.get("/api/admin/overview")

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}


def test_admin_overview_returns_service_model_and_file_sections(
    admin_client: TestClient, monkeypatch, create_user
) -> None:
    create_user(username="admin", password="admin-pass-1", is_admin=True)
    login_as_user(admin_client, username="admin", password="admin-pass-1")
    monkeypatch.setattr(
        "app.routes.admin.get_admin_overview_payload",
        lambda: {
            "services": {
                "backend": {
                    "running": True,
                    "pid": 1001,
                    "label": "running",
                    "detail": "Backend service is running.",
                },
                "tunnel": {
                    "running": False,
                    "pid": None,
                    "label": "stopped",
                    "detail": "Cloudflare tunnel is stopped.",
                },
                "autostartEnabled": True,
            },
            "access": {
                "localUrl": "http://127.0.0.1:8000/chat",
                "publicUrl": "https://[private-host]/chat",
            },
            "models": {"providers": [{"provider": "DeepSeek", "healthy": 2, "total": 2}]},
            "files": {"uploadLimit": 10, "zipEnabled": True, "zipContextCount": 3},
        },
    )

    response = admin_client.get("/api/admin/overview")

    assert response.status_code == 200
    assert response.json()["services"]["backend"]["pid"] == 1001
    assert response.json()["files"]["zipContextCount"] == 3


@pytest.mark.parametrize(
    ("path", "action"),
    [
        ("/api/admin/services/backend/start", "start-backend"),
        ("/api/admin/services/backend/stop", "stop-backend"),
        ("/api/admin/services/tunnel/start", "start-tunnel"),
        ("/api/admin/services/tunnel/stop", "stop-tunnel"),
    ],
)
def test_admin_service_routes_call_fixed_control_actions(
    admin_client: TestClient, monkeypatch, create_user, path: str, action: str
) -> None:
    create_user(username="admin", password="admin-pass-1", is_admin=True)
    login_as_user(admin_client, username="admin", password="admin-pass-1")
    actions: list[str] = []
    monkeypatch.setattr(
        "app.routes.admin.run_admin_control_action",
        lambda next_action: actions.append(next_action)
        or {
            "ok": True,
            "action": next_action,
            "performed": True,
            "message": f"{next_action} complete",
        },
    )

    response = admin_client.post(path)

    assert response.status_code == 200
    assert actions == [action]
    assert response.json()["action"] == action


def test_admin_files_endpoint_reports_current_upload_limit(admin_client: TestClient, create_user) -> None:
    create_user(username="admin", password="admin-pass-1", is_admin=True)
    login_as_user(admin_client, username="admin", password="admin-pass-1")

    response = admin_client.get("/api/admin/files")

    assert response.status_code == 200
    assert response.json()["uploadLimit"] == 10


def test_admin_cache_clear_route_returns_success(
    admin_client: TestClient, monkeypatch, create_user
) -> None:
    create_user(username="admin", password="admin-pass-1", is_admin=True)
    login_as_user(admin_client, username="admin", password="admin-pass-1")
    monkeypatch.setattr("app.routes.admin.clear_admin_zip_cache", lambda: 4)

    response = admin_client.post("/api/admin/files/cache/clear")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "cleared": 4}


def test_admin_prompt_endpoint_returns_default_prompt_when_no_override_file_exists(
    admin_client: TestClient,
    monkeypatch,
    tmp_path,
    create_user,
) -> None:
    create_user(username="admin", password="admin-pass-1", is_admin=True)
    login_as_user(admin_client, username="admin", password="admin-pass-1")
    monkeypatch.setattr("app.prompt_config_store.PROMPT_CONFIG_PATH", tmp_path / "prompt-config.json")

    response = admin_client.get("/api/admin/prompt")

    assert response.status_code == 200
    assert response.json() == {
        "prompt": DEFAULT_CHAT_SYSTEM_PROMPT,
        "source": "default",
        "updatedAt": None,
        "status": "ready",
        "message": None,
    }


def test_admin_prompt_save_returns_override_metadata(
    admin_client: TestClient,
    monkeypatch,
    tmp_path,
    create_user,
) -> None:
    create_user(username="admin", password="admin-pass-1", is_admin=True)
    login_as_user(admin_client, username="admin", password="admin-pass-1")
    monkeypatch.setattr("app.prompt_config_store.PROMPT_CONFIG_PATH", tmp_path / "prompt-config.json")

    response = admin_client.post("/api/admin/prompt", json={"prompt": "override prompt"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["prompt"] == "override prompt"
    assert response.json()["source"] == "override"
    assert response.json()["updatedAt"] is not None
    assert response.json()["status"] == "ready"


def test_admin_prompt_reset_restores_default_prompt(
    admin_client: TestClient,
    monkeypatch,
    tmp_path,
    create_user,
) -> None:
    create_user(username="admin", password="admin-pass-1", is_admin=True)
    login_as_user(admin_client, username="admin", password="admin-pass-1")
    monkeypatch.setattr("app.prompt_config_store.PROMPT_CONFIG_PATH", tmp_path / "prompt-config.json")

    save_response = admin_client.post("/api/admin/prompt", json={"prompt": "custom prompt"})
    assert save_response.status_code == 200

    reset_response = admin_client.post("/api/admin/prompt/reset")

    assert reset_response.status_code == 200
    assert reset_response.json() == {
        "ok": True,
        "prompt": DEFAULT_CHAT_SYSTEM_PROMPT,
        "source": "default",
        "updatedAt": None,
        "status": "ready",
        "message": "系统提示词已恢复为内置默认值。",
    }


def test_admin_prompt_endpoint_falls_back_when_override_file_is_malformed(
    admin_client: TestClient,
    monkeypatch,
    tmp_path,
    create_user,
) -> None:
    create_user(username="admin", password="admin-pass-1", is_admin=True)
    login_as_user(admin_client, username="admin", password="admin-pass-1")
    prompt_config_path = tmp_path / "prompt-config.json"
    prompt_config_path.write_text("{not-valid-json", encoding="utf-8")
    monkeypatch.setattr("app.prompt_config_store.PROMPT_CONFIG_PATH", prompt_config_path)

    response = admin_client.get("/api/admin/prompt")

    assert response.status_code == 200
    assert response.json() == {
        "prompt": DEFAULT_CHAT_SYSTEM_PROMPT,
        "source": "default",
        "updatedAt": None,
        "status": "fallback",
        "message": "系统提示词配置文件无效，已回退到内置默认值。",
    }


def test_admin_invites_flow_lists_creates_toggles_and_deletes_invites(
    admin_client: TestClient,
    create_user,
    create_invite_code,
) -> None:
    create_user(username="admin", password="admin-pass-1", is_admin=True)
    existing_invite = create_invite_code(
        code="existing-invite",
        label="Existing",
        is_active=True,
        max_uses=2,
    )
    login_as_user(admin_client, username="admin", password="admin-pass-1")

    list_response = admin_client.get("/api/admin/invites")

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["id"] == existing_invite.id
    assert list_response.json()["items"][0]["code"] == "existing-invite"
    assert list_response.json()["items"][0]["label"] == "Existing"
    assert list_response.json()["items"][0]["isActive"] is True
    assert list_response.json()["items"][0]["maxUses"] == 2
    assert list_response.json()["items"][0]["usedCount"] == 0

    create_response = admin_client.post(
        "/api/admin/invites",
        json={"code": "new-invite", "label": "Fresh", "maxUses": 5},
    )

    assert create_response.status_code == 201
    created_invite = create_response.json()
    assert created_invite["code"] == "new-invite"
    assert created_invite["label"] == "Fresh"
    assert created_invite["isActive"] is True
    assert created_invite["maxUses"] == 5
    assert created_invite["usedCount"] == 0

    toggle_response = admin_client.post(f"/api/admin/invites/{created_invite['id']}/toggle")

    assert toggle_response.status_code == 200
    assert toggle_response.json()["id"] == created_invite["id"]
    assert toggle_response.json()["isActive"] is False

    delete_response = admin_client.delete(f"/api/admin/invites/{created_invite['id']}")

    assert delete_response.status_code == 204
    assert delete_response.content == b""

    with SessionLocal() as db:
        deleted_invite = db.execute(
            select(InviteCode).where(InviteCode.id == created_invite["id"])
        ).scalar_one_or_none()

    assert deleted_invite is None


def test_admin_invites_reject_legacy_anonymous_session(admin_client: TestClient) -> None:
    login_as_legacy_session(admin_client)

    list_response = admin_client.get("/api/admin/invites")
    create_response = admin_client.post("/api/admin/invites", json={"code": "new-invite"})
    toggle_response = admin_client.post("/api/admin/invites/1/toggle")
    delete_response = admin_client.delete("/api/admin/invites/1")

    assert list_response.status_code == 401
    assert create_response.status_code == 401
    assert toggle_response.status_code == 401
    assert delete_response.status_code == 401
    assert list_response.json() == {"detail": "User authentication required"}
    assert create_response.json() == {"detail": "User authentication required"}
    assert toggle_response.json() == {"detail": "User authentication required"}
    assert delete_response.json() == {"detail": "User authentication required"}


def test_admin_invites_reject_non_admin_user(admin_client: TestClient, create_user) -> None:
    create_user(username="member", password="member-pass-1")
    login_as_user(admin_client, username="member", password="member-pass-1")

    list_response = admin_client.get("/api/admin/invites")
    create_response = admin_client.post("/api/admin/invites", json={"code": "new-invite"})
    toggle_response = admin_client.post("/api/admin/invites/1/toggle")
    delete_response = admin_client.delete("/api/admin/invites/1")

    assert list_response.status_code == 403
    assert create_response.status_code == 403
    assert toggle_response.status_code == 403
    assert delete_response.status_code == 403
    assert list_response.json() == {"detail": "Admin access required"}
    assert create_response.json() == {"detail": "Admin access required"}
    assert toggle_response.json() == {"detail": "Admin access required"}
    assert delete_response.json() == {"detail": "Admin access required"}


def test_build_control_snapshot_marks_backend_running() -> None:
    from app.admin_control import ProcessStateInput, build_control_snapshot

    backend_process: ProcessStateInput = {"running": True, "pid": 37152}
    tunnel_process: ProcessStateInput = {"running": False, "pid": None}
    snapshot = build_control_snapshot(
        backend_process=backend_process,
        tunnel_process=tunnel_process,
        autostart_enabled=True,
    )

    assert snapshot.backend.running is True
    assert snapshot.backend.pid == 37152
    assert snapshot.backend.label == "running"
    assert snapshot.backend.detail == "Backend service is running."
    assert snapshot.tunnel.running is False
    assert snapshot.tunnel.pid is None
    assert snapshot.tunnel.label == "stopped"
    assert snapshot.tunnel.detail == "Cloudflare tunnel is stopped."
    assert snapshot.autostart_enabled is True


def test_service_state_from_running_builds_consistent_status_metadata() -> None:
    from app.admin_control import ServiceState

    state = ServiceState.from_running(
        running=False,
        pid=None,
        running_detail="Backend service is running.",
        stopped_detail="Backend service is stopped.",
    )

    assert state.running is False
    assert state.pid is None
    assert state.label == "stopped"
    assert state.detail == "Backend service is stopped."


def test_inspect_autostart_enabled_accepts_startup_folder_fallback(monkeypatch, tmp_path) -> None:
    from app.admin_control import AdminControlManager

    startup_dir = tmp_path / "Startup"
    startup_dir.mkdir()
    (startup_dir / "CipherChatWeb.cmd").write_text("@echo off\n", encoding="utf-8")
    (startup_dir / "CipherAdminConsole.cmd").write_text("@echo off\n", encoding="utf-8")
    (startup_dir / "CipherChatCloudflared.cmd").write_text("@echo off\n", encoding="utf-8")

    monkeypatch.setattr(
        "app.admin_control._run_powershell_json",
        lambda script: {"enabled": False, "source": "missing-task"},
    )
    monkeypatch.setattr("app.admin_control.get_startup_dir", lambda: startup_dir)

    manager = AdminControlManager()

    assert manager.inspect_autostart_enabled() is True


def test_inspect_autostart_enabled_accepts_mixed_mode_service_and_startup(monkeypatch, tmp_path) -> None:
    from app.admin_control import AdminControlManager

    startup_dir = tmp_path / "Startup"
    startup_dir.mkdir()
    (startup_dir / "CipherChatWeb.cmd").write_text("@echo off\n", encoding="utf-8")
    (startup_dir / "CipherAdminConsole.cmd").write_text("@echo off\n", encoding="utf-8")

    monkeypatch.setattr(
        "app.admin_control._windows_service_autostarts",
        lambda service_name: service_name == "Cloudflared",
    )
    monkeypatch.setattr(
        "app.admin_control._run_powershell_json",
        lambda script: {"enabled": False, "source": "missing-task"},
    )
    monkeypatch.setattr("app.admin_control.get_startup_dir", lambda: startup_dir)

    manager = AdminControlManager()

    assert manager.inspect_autostart_enabled() is True


def test_inspect_autostart_enabled_prefers_windows_services(monkeypatch) -> None:
    from app.admin_control import AdminControlManager

    monkeypatch.setattr(
        "app.admin_control._windows_service_autostarts",
        lambda service_name: True,
    )

    manager = AdminControlManager()

    assert manager.inspect_autostart_enabled() is True


def test_inspect_autostart_enabled_returns_false_without_any_autostart(monkeypatch, tmp_path) -> None:
    from app.admin_control import AdminControlManager

    startup_dir = tmp_path / "Startup"
    startup_dir.mkdir()

    monkeypatch.setattr(
        "app.admin_control._run_powershell_json",
        lambda script: {"enabled": False, "source": "missing-task"},
    )
    monkeypatch.setattr("app.admin_control.get_startup_dir", lambda: startup_dir)

    manager = AdminControlManager()

    assert manager.inspect_autostart_enabled() is False


def test_start_backend_uses_windows_service_when_installed(monkeypatch) -> None:
    from app.admin_control import AdminControlManager

    started_services: list[str] = []

    monkeypatch.setattr(
        "app.admin_control._windows_service_installed",
        lambda service_name: service_name == "CipherChatWeb",
    )
    monkeypatch.setattr("app.admin_control._start_windows_service", lambda service_name: started_services.append(service_name))
    monkeypatch.setattr("app.admin_control._wait_for_condition", lambda predicate, **kwargs: True)
    monkeypatch.setattr("app.admin_control._is_backend_healthy", lambda: False)
    monkeypatch.setattr(AdminControlManager, "inspect_backend_process", lambda self: {"running": False, "pid": None})

    result = AdminControlManager().run_action("start-backend")

    assert started_services == ["CipherChatWeb"]
    assert result["ok"] is True
    assert result["message"] == "Backend service started."


def test_start_tunnel_uses_windows_service_when_installed(monkeypatch) -> None:
    from app.admin_control import AdminControlManager

    started_services: list[str] = []

    monkeypatch.setattr(
        "app.admin_control._windows_service_installed",
        lambda service_name: service_name == "CipherCloudflared",
    )
    monkeypatch.setattr("app.admin_control._start_windows_service", lambda service_name: started_services.append(service_name))
    monkeypatch.setattr("app.admin_control._wait_for_condition", lambda predicate, **kwargs: True)
    monkeypatch.setattr(AdminControlManager, "inspect_tunnel_process", lambda self: {"running": False, "pid": None})

    result = AdminControlManager().run_action("start-tunnel")

    assert started_services == ["CipherCloudflared"]
    assert result["ok"] is True
    assert result["message"] == "Cloudflare tunnel started."


def test_start_tunnel_falls_back_to_builtin_cloudflared_service(monkeypatch) -> None:
    from app.admin_control import AdminControlManager

    started_services: list[str] = []

    monkeypatch.setattr(
        "app.admin_control._windows_service_installed",
        lambda service_name: service_name == "Cloudflared",
    )
    monkeypatch.setattr("app.admin_control._start_windows_service", lambda service_name: started_services.append(service_name))
    monkeypatch.setattr("app.admin_control._wait_for_condition", lambda predicate, **kwargs: True)
    monkeypatch.setattr(AdminControlManager, "inspect_tunnel_process", lambda self: {"running": False, "pid": None})

    result = AdminControlManager().run_action("start-tunnel")

    assert started_services == ["Cloudflared"]
    assert result["ok"] is True
    assert result["message"] == "Cloudflare tunnel started."


def test_control_actions_reject_unknown_action() -> None:
    from app.admin_control import AdminControlManager

    manager = AdminControlManager()

    with pytest.raises(ValueError, match=r"^Unsupported admin control action: restart-all$"):
        manager.run_action("restart-all")
