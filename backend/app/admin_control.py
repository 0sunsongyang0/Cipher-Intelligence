from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
from time import monotonic, sleep
from typing import TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_TUNNEL_SCRIPT = REPO_ROOT / "run-cloudflared-cipher-chat.ps1"
START_BACKEND_SCRIPT = REPO_ROOT / "start-campus-lan.ps1"
STOP_BACKEND_SCRIPT = REPO_ROOT / "stop-campus-lan.ps1"
CHAT_BACKEND_PORT = 8000
CHAT_HEALTH_URL = f"http://127.0.0.1:{CHAT_BACKEND_PORT}/api/health"
CHAT_WINDOWS_SERVICE = "CipherChatWeb"
ADMIN_WINDOWS_SERVICE = "CipherAdminConsole"
TUNNEL_WINDOWS_SERVICE = "CipherCloudflared"
BUILTIN_TUNNEL_WINDOWS_SERVICE = "Cloudflared"
ADMIN_AUTOSTART_TASK = "CipherChatCloudflared"
CHAT_STARTUP_LAUNCHER = "CipherChatWeb.cmd"
ADMIN_STARTUP_LAUNCHER = "CipherAdminConsole.cmd"
TUNNEL_STARTUP_LAUNCHER = "CipherChatCloudflared.cmd"
TUNNEL_ID = "[private-tunnel-id]"


class ProcessStateInput(TypedDict):
    running: bool
    pid: int | None


class AdminActionResult(TypedDict):
    ok: bool
    action: str
    performed: bool
    message: str


def build_pending_action_result(action: str) -> AdminActionResult:
    return {
        "ok": True,
        "action": action,
        "performed": False,
        "message": "Admin control dispatch is not implemented yet.",
    }


def _powershell_prefix() -> list[str]:
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]


def _hidden_creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
        getattr(subprocess, "DETACHED_PROCESS", 0)
    )


def _run_powershell_json(script: str) -> dict[str, object]:
    completed = subprocess.run(
        [*_powershell_prefix(), "-Command", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=True,
    )
    payload = completed.stdout.strip() or "{}"
    return json.loads(payload)


def _launch_detached_powershell(arguments: list[str]) -> None:
    subprocess.Popen(
        [*_powershell_prefix(), *arguments],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_hidden_creation_flags(),
    )


def _wait_for_condition(predicate, *, timeout_seconds: float, interval_seconds: float = 0.5) -> bool:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if predicate():
            return True
        sleep(interval_seconds)
    return predicate()


def _is_backend_healthy() -> bool:
    try:
        with urlopen(CHAT_HEALTH_URL, timeout=3) as response:
            return response.status == 200
    except (HTTPError, URLError, TimeoutError, OSError):
        return False


def _windows_service_status(service_name: str) -> dict[str, object]:
    payload = _run_powershell_json(
        f"""
$service = Get-CimInstance Win32_Service -Filter "Name = '{service_name}'" -ErrorAction SilentlyContinue
if ($null -eq $service) {{
    @{{ installed = $false }} | ConvertTo-Json -Compress
    exit 0
}}

@{{
    installed = $true
    name = $service.Name
    state = $service.State
    startMode = $service.StartMode
    processId = if ($service.ProcessId -gt 0) {{ [int]$service.ProcessId }} else {{ $null }}
}} | ConvertTo-Json -Compress
"""
    )
    return payload


def _windows_service_installed(service_name: str) -> bool:
    return bool(_windows_service_status(service_name).get("installed"))


def _windows_service_autostarts(service_name: str) -> bool:
    payload = _windows_service_status(service_name)
    if not payload.get("installed"):
        return False

    return str(payload.get("startMode", "")).lower() == "auto"


def _first_installed_windows_service(*service_names: str) -> str | None:
    for service_name in service_names:
        if _windows_service_installed(service_name):
            return service_name
    return None


def _get_tunnel_windows_service_name() -> str | None:
    return _first_installed_windows_service(
        TUNNEL_WINDOWS_SERVICE,
        BUILTIN_TUNNEL_WINDOWS_SERVICE,
    )


def _start_windows_service(service_name: str) -> None:
    subprocess.run(
        [*_powershell_prefix(), "-Command", f"Start-Service -Name '{service_name}'"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=True,
    )


def _stop_windows_service(service_name: str) -> None:
    subprocess.run(
        [*_powershell_prefix(), "-Command", f"Stop-Service -Name '{service_name}' -Force"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=True,
    )


def get_startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"

    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def get_tunnel_startup_launcher_path() -> Path:
    return get_startup_dir() / TUNNEL_STARTUP_LAUNCHER


def get_chat_startup_launcher_path() -> Path:
    return get_startup_dir() / CHAT_STARTUP_LAUNCHER


def get_admin_startup_launcher_path() -> Path:
    return get_startup_dir() / ADMIN_STARTUP_LAUNCHER


@dataclass
class ServiceState:
    running: bool
    pid: int | None
    label: str
    detail: str

    @classmethod
    def from_running(
        cls,
        *,
        running: bool,
        pid: int | None,
        running_detail: str,
        stopped_detail: str,
    ) -> "ServiceState":
        return cls(
            running=running,
            pid=pid if running else None,
            label="running" if running else "stopped",
            detail=running_detail if running else stopped_detail,
        )


@dataclass
class ControlSnapshot:
    backend: ServiceState
    tunnel: ServiceState
    autostart_enabled: bool


def build_control_snapshot(
    *,
    backend_process: ProcessStateInput,
    tunnel_process: ProcessStateInput,
    autostart_enabled: bool,
) -> ControlSnapshot:
    return ControlSnapshot(
        backend=ServiceState.from_running(
            running=backend_process["running"],
            pid=backend_process["pid"],
            running_detail="Backend service is running.",
            stopped_detail="Backend service is stopped.",
        ),
        tunnel=ServiceState.from_running(
            running=tunnel_process["running"],
            pid=tunnel_process["pid"],
            running_detail="Cloudflare tunnel is running.",
            stopped_detail="Cloudflare tunnel is stopped.",
        ),
        autostart_enabled=autostart_enabled,
    )


class AdminControlManager:
    _ALLOWED_ACTIONS = {"start-backend", "stop-backend", "start-tunnel", "stop-tunnel", "get-status"}

    def inspect_backend_process(self) -> ProcessStateInput:
        payload = _run_powershell_json(
            f"""
$listener = Get-NetTCPConnection -LocalPort {CHAT_BACKEND_PORT} -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1

if ($null -eq $listener) {{
    @{{ running = $false; pid = $null }} | ConvertTo-Json -Compress
    exit 0
}}

$process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
if ($null -eq $process -or $process.ProcessName -notmatch "^(python|pythonw|uvicorn)$") {{
    @{{ running = $false; pid = $null }} | ConvertTo-Json -Compress
    exit 0
}}

@{{ running = $true; pid = [int]$process.Id }} | ConvertTo-Json -Compress
"""
        )
        return {
            "running": bool(payload.get("running")),
            "pid": int(payload["pid"]) if payload.get("pid") is not None else None,
        }

    def inspect_tunnel_process(self) -> ProcessStateInput:
        payload = _run_powershell_json(
            f"""
$process = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue |
    Where-Object {{ $_.CommandLine -match '{TUNNEL_ID}' }} |
    Select-Object -First 1

if ($null -eq $process) {{
    @{{ running = $false; pid = $null }} | ConvertTo-Json -Compress
    exit 0
}}

@{{ running = $true; pid = [int]$process.ProcessId }} | ConvertTo-Json -Compress
"""
        )
        return {
            "running": bool(payload.get("running")),
            "pid": int(payload["pid"]) if payload.get("pid") is not None else None,
        }

    def inspect_autostart_enabled(self) -> bool:
        chat_service_autostart = _windows_service_autostarts(CHAT_WINDOWS_SERVICE)
        admin_service_autostart = _windows_service_autostarts(ADMIN_WINDOWS_SERVICE)
        tunnel_service_autostart = any(
            _windows_service_autostarts(service_name)
            for service_name in (
                TUNNEL_WINDOWS_SERVICE,
                BUILTIN_TUNNEL_WINDOWS_SERVICE,
            )
        )

        if chat_service_autostart and admin_service_autostart and tunnel_service_autostart:
            return True

        payload = _run_powershell_json(
            f"""
$task = Get-ScheduledTask -TaskName '{ADMIN_AUTOSTART_TASK}' -ErrorAction SilentlyContinue
if ($null -eq $task) {{
    @{{ enabled = $false; source = 'missing-task' }} | ConvertTo-Json -Compress
    exit 0
}}

@{{ enabled = [bool]$task.Settings.Enabled; source = 'scheduled-task' }} | ConvertTo-Json -Compress
"""
        )
        if payload.get("source") == "scheduled-task":
            return (
                bool(payload.get("enabled"))
                and get_chat_startup_launcher_path().is_file()
                and get_admin_startup_launcher_path().is_file()
            )

        return (
            tunnel_service_autostart
            and get_chat_startup_launcher_path().is_file()
            and get_admin_startup_launcher_path().is_file()
        ) or (
            get_tunnel_startup_launcher_path().is_file()
            and get_chat_startup_launcher_path().is_file()
            and get_admin_startup_launcher_path().is_file()
        )

    def get_snapshot(self) -> ControlSnapshot:
        return build_control_snapshot(
            backend_process=self.inspect_backend_process(),
            tunnel_process=self.inspect_tunnel_process(),
            autostart_enabled=self.inspect_autostart_enabled(),
        )

    def snapshot_payload(self) -> dict[str, object]:
        snapshot = self.get_snapshot()
        return {
            "backend": asdict(snapshot.backend),
            "tunnel": asdict(snapshot.tunnel),
            "autostartEnabled": snapshot.autostart_enabled,
        }

    def _start_backend(self) -> AdminActionResult:
        if self.inspect_backend_process()["running"]:
            return {
                "ok": True,
                "action": "start-backend",
                "performed": False,
                "message": "Backend service is already running.",
            }

        if _windows_service_installed(CHAT_WINDOWS_SERVICE):
            _start_windows_service(CHAT_WINDOWS_SERVICE)
        else:
            _launch_detached_powershell(
                [
                    "-File",
                    str(START_BACKEND_SCRIPT),
                    "-Port",
                    str(CHAT_BACKEND_PORT),
                    "-SkipBuild",
                    "-NoFirewall",
                    "-NoAdminRelaunch",
                ]
            )
        started = _wait_for_condition(_is_backend_healthy, timeout_seconds=15)
        return {
            "ok": started,
            "action": "start-backend",
            "performed": started,
            "message": "Backend service started." if started else "Backend service did not become healthy in time.",
        }

    def _stop_backend(self) -> AdminActionResult:
        if _windows_service_installed(CHAT_WINDOWS_SERVICE):
            _stop_windows_service(CHAT_WINDOWS_SERVICE)
        else:
            subprocess.run(
                [*_powershell_prefix(), "-File", str(STOP_BACKEND_SCRIPT), "-Port", str(CHAT_BACKEND_PORT)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=True,
            )
        stopped = _wait_for_condition(lambda: not _is_backend_healthy(), timeout_seconds=10)
        return {
            "ok": stopped,
            "action": "stop-backend",
            "performed": stopped,
            "message": "Backend service stopped." if stopped else "Backend service still appears to be running.",
        }

    def _start_tunnel(self) -> AdminActionResult:
        if self.inspect_tunnel_process()["running"]:
            return {
                "ok": True,
                "action": "start-tunnel",
                "performed": False,
                "message": "Cloudflare tunnel is already running.",
            }

        tunnel_service_name = _get_tunnel_windows_service_name()
        if tunnel_service_name is not None:
            _start_windows_service(tunnel_service_name)
        else:
            _launch_detached_powershell(
                [
                    "-File",
                    str(RUN_TUNNEL_SCRIPT),
                    "-HealthPort",
                    str(CHAT_BACKEND_PORT),
                ]
            )
        started = _wait_for_condition(
            lambda: self.inspect_tunnel_process()["running"],
            timeout_seconds=15,
        )
        return {
            "ok": started,
            "action": "start-tunnel",
            "performed": started,
            "message": "Cloudflare tunnel started." if started else "Cloudflare tunnel did not start in time.",
        }

    def _stop_tunnel(self) -> AdminActionResult:
        tunnel_service_name = _get_tunnel_windows_service_name()
        if tunnel_service_name is not None:
            _stop_windows_service(tunnel_service_name)
        else:
            _run_powershell_json(
                f"""
$processes = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue |
    Where-Object {{ $_.CommandLine -match '{TUNNEL_ID}' }}

foreach ($process in $processes) {{
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}}

@{{ stopped = $true }} | ConvertTo-Json -Compress
"""
            )
        stopped = _wait_for_condition(
            lambda: not self.inspect_tunnel_process()["running"],
            timeout_seconds=10,
        )
        return {
            "ok": stopped,
            "action": "stop-tunnel",
            "performed": stopped,
            "message": "Cloudflare tunnel stopped." if stopped else "Cloudflare tunnel still appears to be running.",
        }

    def run_action(self, action: str) -> AdminActionResult:
        if action not in self._ALLOWED_ACTIONS:
            raise ValueError(f"Unsupported admin control action: {action}")

        if action == "get-status":
            return {
                "ok": True,
                "action": action,
                "performed": False,
                "message": "Current admin control state loaded.",
            }
        if action == "start-backend":
            return self._start_backend()
        if action == "stop-backend":
            return self._stop_backend()
        if action == "start-tunnel":
            return self._start_tunnel()
        return self._stop_tunnel()
