from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any

from app.cape_client import CapeClient
from app.config import settings


TERMINAL_TASK_STATUSES = {
    "reported",
    "failed_analysis",
    "failed_processing",
    "failed_reporting",
    "recovered",
}


@dataclass(frozen=True)
class CapeSubmission:
    task_id: int
    status: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class CapeTaskSnapshot:
    task_id: int
    status: str
    completed: bool
    score: float | None
    target_filename: str | None
    machine: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class CapeAnalysisSummary:
    task_id: int
    status: str
    score: float | None
    submitted_filename: str | None
    sha256: str | None
    iocs: dict[str, list[str]]
    tactics: list[dict[str, str]]
    dropped_files: list[dict[str, str]]
    processes: list[dict[str, Any]]
    network_connections: list[dict[str, Any]]
    signatures: list[dict[str, Any]]
    raw: dict[str, Any]


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _coerce_task_id_from_text(value: Any) -> int | None:
    if isinstance(value, str):
        match = re.search(r"(?:task id\s+|status/)(\d+)", value, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    if isinstance(value, list):
        for item in value:
            task_id = _coerce_task_id_from_text(item)
            if task_id is not None:
                return task_id
    return None


def _extract_cape_error(payload: dict[str, Any]) -> str | None:
    error_value = payload.get("error_value")
    if isinstance(error_value, str) and error_value.strip():
        return error_value.strip()

    for key in ("errors", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            messages = [str(item).strip() for item in value if str(item).strip()]
            if messages:
                return "; ".join(messages)

    return None


def _raise_if_cape_error(payload: dict[str, Any]) -> None:
    if payload.get("error") is True:
        cape_error = _extract_cape_error(payload)
        raise ValueError(cape_error or "CAPE returned an error response.")


def _coerce_task_id(payload: dict[str, Any]) -> int:
    _raise_if_cape_error(payload)

    task_id = payload.get("task_id")
    task_id = _coerce_int(task_id)
    if task_id is not None:
        return task_id

    data = payload.get("data")
    if isinstance(data, dict):
        task_id = _coerce_int(data.get("task_id"))
        if task_id is not None:
            return task_id

        nested_task_ids = data.get("task_ids")
        if isinstance(nested_task_ids, list) and nested_task_ids:
            task_id = _coerce_int(nested_task_ids[0])
            if task_id is not None:
                return task_id

        task_id = _coerce_task_id_from_text(data.get("message"))
        if task_id is not None:
            return task_id

    task_ids = payload.get("task_ids")
    if isinstance(task_ids, list) and task_ids:
        task_id = _coerce_int(task_ids[0])
        if task_id is not None:
            return task_id

    task_id = _coerce_task_id_from_text(payload.get("url"))
    if task_id is not None:
        return task_id

    cape_error = _extract_cape_error(payload)
    if cape_error:
        raise ValueError(cape_error)

    raise ValueError("CAPE response did not include a task id.")


def _extract_task_container(payload: dict[str, Any]) -> dict[str, Any]:
    task = payload.get("task")
    if isinstance(task, dict):
        return task
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _find_task_by_sha256(payload: dict[str, Any], sha256: str) -> tuple[int, str] | None:
    tasks = payload.get("data")
    if not isinstance(tasks, list):
        return None

    normalized_sha256 = sha256.lower()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        sample = task.get("sample") if isinstance(task.get("sample"), dict) else {}
        if str(sample.get("sha256", "")).strip().lower() != normalized_sha256:
            continue
        task_id = _coerce_int(task.get("id"))
        if task_id is None:
            continue
        return task_id, _normalize_status(task.get("status") or "submitted")

    return None


def _normalize_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized or "unknown"


def _extract_iocs(report: dict[str, Any]) -> dict[str, list[str]]:
    network = report.get("network") if isinstance(report.get("network"), dict) else {}
    domains = network.get("domains") if isinstance(network.get("domains"), list) else []
    hosts = network.get("hosts") if isinstance(network.get("hosts"), list) else []
    http_items = network.get("http") if isinstance(network.get("http"), list) else []

    return {
        "domains": sorted(
            {
                str(item.get("domain")).strip()
                for item in domains
                if isinstance(item, dict) and str(item.get("domain", "")).strip()
            }
        ),
        "ips": sorted(
            {
                str(item.get("ip")).strip()
                for item in hosts
                if isinstance(item, dict) and str(item.get("ip", "")).strip()
            }
        ),
        "urls": sorted(
            {
                str(item.get("uri")).strip()
                for item in http_items
                if isinstance(item, dict) and str(item.get("uri", "")).strip()
            }
        ),
    }


def _extract_tactics(report: dict[str, Any]) -> list[dict[str, str]]:
    signatures = report.get("signatures") if isinstance(report.get("signatures"), list) else []
    techniques: list[dict[str, str]] = []

    for signature in signatures:
        if not isinstance(signature, dict):
            continue
        ttps = signature.get("ttps")
        if not isinstance(ttps, list):
            continue
        for item in ttps:
            if not isinstance(item, dict):
                continue
            technique = str(item.get("ttp", "")).strip()
            if not technique:
                continue
            techniques.append(
                {
                    "technique": technique,
                    "signature": str(signature.get("name", "")).strip(),
                    "description": str(item.get("signature", "") or signature.get("description", "")).strip(),
                }
            )

    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in techniques:
        key = (item["technique"], item["signature"], item["description"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _extract_dropped_files(report: dict[str, Any]) -> list[dict[str, str]]:
    dropped = report.get("dropped") if isinstance(report.get("dropped"), list) else []
    results: list[dict[str, str]] = []

    for item in dropped:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "name": str(item.get("name", "")).strip(),
                "path": str(item.get("filepath", "")).strip(),
                "type": str(item.get("type", "")).strip(),
                "sha256": str(item.get("sha256", "")).strip(),
            }
        )
    return results


def _extract_processes(report: dict[str, Any]) -> list[dict[str, Any]]:
    behavior = report.get("behavior") if isinstance(report.get("behavior"), dict) else {}
    raw = behavior.get("processes") if isinstance(behavior.get("processes"), list) else behavior.get("processtree")
    pending = list(raw) if isinstance(raw, list) else []
    results: list[dict[str, Any]] = []
    while pending:
        item = pending.pop(0)
        if not isinstance(item, dict):
            continue
        process = {
            "pid": item.get("process_id") or item.get("pid"),
            "parentPid": item.get("parent_id") or item.get("ppid"),
            "name": item.get("process_name") or item.get("name"),
            "commandLine": item.get("command_line") or item.get("commandline"),
            "startedAt": item.get("first_seen") or item.get("start_time"),
        }
        if process["pid"] is not None or process["name"]:
            results.append({key: value for key, value in process.items() if value not in (None, "")})
        children = item.get("children")
        if isinstance(children, list):
            pending.extend(children)
    return results


def _extract_network_connections(report: dict[str, Any]) -> list[dict[str, Any]]:
    network = report.get("network") if isinstance(report.get("network"), dict) else {}
    results: list[dict[str, Any]] = []
    for key, protocol in (("http", "http"), ("https", "https")):
        for item in network.get(key, []) if isinstance(network.get(key), list) else []:
            if isinstance(item, dict):
                results.append({"url": item.get("uri") or item.get("url"), "domain": item.get("host"), "method": item.get("method"), "pid": item.get("pid"), "occurredAt": item.get("timestamp"), "protocol": protocol})
    for key in ("tcp", "udp"):
        for item in network.get(key, []) if isinstance(network.get(key), list) else []:
            if isinstance(item, dict):
                results.append({"ip": item.get("dst") or item.get("ip"), "port": item.get("dport") or item.get("port"), "pid": item.get("pid"), "occurredAt": item.get("timestamp"), "protocol": key})
    return [{key: value for key, value in item.items() if value not in (None, "")} for item in results if item.get("url") or item.get("domain") or item.get("ip")]


class CapeService:
    def __init__(self, client: CapeClient | None = None) -> None:
        self._client = client or CapeClient()

    async def submit_file(
        self,
        *,
        filename: str,
        content: bytes,
        machine: str | None = None,
        platform: str | None = None,
        tags: list[str] | None = None,
        route: str | None = None,
        is_pcap: bool = False,
    ) -> CapeSubmission:
        payload = await self._client.submit_file(
            filename=filename,
            content=content,
            machine=machine,
            platform=platform,
            tags=tags,
            route=route,
            is_pcap=is_pcap,
        )
        try:
            task_id = _coerce_task_id(payload)
        except ValueError as exc:
            if "error adding task to database" not in str(exc).lower():
                raise

            existing_task = await self._find_existing_task_for_content(content)
            if existing_task is None:
                raise

            task_id, existing_status = existing_task
            return CapeSubmission(
                task_id=task_id,
                status=existing_status,
                raw={"submit": payload, "reusedExistingTask": True},
            )

        return CapeSubmission(
            task_id=task_id,
            status=_normalize_status(payload.get("status") or "submitted"),
            raw=payload,
        )

    async def _find_existing_task_for_content(self, content: bytes) -> tuple[int, str] | None:
        sha256 = hashlib.sha256(content).hexdigest()
        payload = await self._client.list_tasks(limit=50, offset=0)
        return _find_task_by_sha256(payload, sha256)

    async def get_task_snapshot(self, task_id: int) -> CapeTaskSnapshot:
        payload = await self._client.get_task_status(task_id)
        if isinstance(payload.get("data"), str):
            status = _normalize_status(payload.get("data"))
            view_payload = await self._client.get_task_view(task_id)
            view_task = _extract_task_container(view_payload)
            sample = view_task.get("sample") if isinstance(view_task.get("sample"), dict) else {}
            machine = view_task.get("machine") if isinstance(view_task.get("machine"), dict) else {}
            return CapeTaskSnapshot(
                task_id=task_id,
                status=status,
                completed=status in TERMINAL_TASK_STATUSES,
                score=float(view_task["score"]) if isinstance(view_task.get("score"), (int, float)) else None,
                target_filename=str(sample.get("file_name", "")).strip() or None,
                machine=str(machine.get("name", "")).strip() or None,
                raw={"status": payload, "view": view_payload},
            )

        task = _extract_task_container(payload)
        status = _normalize_status(task.get("status"))
        sample = task.get("sample") if isinstance(task.get("sample"), dict) else {}
        machine = task.get("machine") if isinstance(task.get("machine"), dict) else {}
        return CapeTaskSnapshot(
            task_id=task_id,
            status=status,
            completed=status in TERMINAL_TASK_STATUSES,
            score=float(task["score"]) if isinstance(task.get("score"), (int, float)) else None,
            target_filename=str(sample.get("file_name", "")).strip() or None,
            machine=str(machine.get("name", "")).strip() or None,
            raw=payload,
        )

    async def get_analysis_summary(self, task_id: int) -> CapeAnalysisSummary:
        report = await self._client.get_task_report(task_id)
        _raise_if_cape_error(report)
        target = report.get("target") if isinstance(report.get("target"), dict) else {}
        file_info = target.get("file") if isinstance(target.get("file"), dict) else {}

        return CapeAnalysisSummary(
            task_id=task_id,
            status=_normalize_status(report.get("info", {}).get("status") if isinstance(report.get("info"), dict) else None),
            score=float(report["info"]["score"]) if isinstance(report.get("info"), dict) and isinstance(report["info"].get("score"), (int, float)) else None,
            submitted_filename=str(file_info.get("name", "")).strip() or None,
            sha256=str(file_info.get("sha256", "")).strip() or None,
            iocs=_extract_iocs(report),
            tactics=_extract_tactics(report),
            dropped_files=_extract_dropped_files(report),
            processes=_extract_processes(report),
            network_connections=_extract_network_connections(report),
            signatures=[
                item for item in report.get("signatures", [])
                if isinstance(item, dict)
            ] if isinstance(report.get("signatures"), list) else [],
            raw=report,
        )

    def get_poll_interval_seconds(self) -> float:
        return settings.cape_poll_interval_seconds
