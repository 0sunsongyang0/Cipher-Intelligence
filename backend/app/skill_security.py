from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException

PERMISSION_GROUPS = ("network", "files", "commands", "data")
DEFAULT_POLICY = {"timeoutSeconds": 30, "memoryMb": 256, "cpuSeconds": 10, "maxOutputBytes": 262_144,
                  "retry": {"maxAttempts": 2, "backoffMs": 200}}


def normalize_permissions(manifest: dict[str, Any]) -> dict[str, list[str]]:
    raw = manifest.get("permissions", {})
    if not isinstance(raw, dict):
        raw = {}
    result = {group: [str(value) for value in raw.get(group, [])] for group in PERMISSION_GROUPS}
    for tool in raw.get("tools", []) if isinstance(raw.get("tools"), list) else []:
        value = str(tool)
        group = "network" if any(token in value for token in ("http", "network", "lookup", "threat_intel")) else "commands" if any(token in value for token in ("execute", "command", "shell")) else "data"
        result[group].append(value)
    return {key: list(dict.fromkeys(values)) for key, values in result.items()}


def flattened_permissions(manifest: dict[str, Any]) -> list[str]:
    grouped = normalize_permissions(manifest)
    return [f"{group}:{value}" for group in PERMISSION_GROUPS for value in grouped[group]]


def execution_policy(manifest: dict[str, Any]) -> dict[str, Any]:
    raw = manifest.get("limits", {}) if isinstance(manifest.get("limits"), dict) else {}
    retry = raw.get("retry", {}) if isinstance(raw.get("retry"), dict) else {}
    return {
        "timeoutSeconds": max(1, min(300, int(raw.get("timeoutSeconds", DEFAULT_POLICY["timeoutSeconds"])))),
        "memoryMb": max(32, min(2048, int(raw.get("memoryMb", DEFAULT_POLICY["memoryMb"]))),),
        "cpuSeconds": max(1, min(120, int(raw.get("cpuSeconds", DEFAULT_POLICY["cpuSeconds"]))),),
        "maxOutputBytes": max(1024, min(2_097_152, int(raw.get("maxOutputBytes", DEFAULT_POLICY["maxOutputBytes"]))),),
        "retry": {"maxAttempts": max(1, min(5, int(retry.get("maxAttempts", 2)))),
                  "backoffMs": max(0, min(5000, int(retry.get("backoffMs", 200))))},
    }


def package_digest(directory: Path, manifest: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    canonical = {key: value for key, value in manifest.items() if key not in {"signature", "_scan"}}
    digest.update(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    for path in sorted(directory.rglob("*")) if directory.is_dir() else []:
        if path.is_file() and path.name != "skill.yaml":
            digest.update(str(path.relative_to(directory)).encode()); digest.update(path.read_bytes())
    return digest.hexdigest()


def sign_digest(digest: str) -> str:
    secret = os.getenv("CIPHER_SKILL_SIGNING_KEY") or os.getenv("SESSION_SECRET") or "cipher-builtin-development-key"
    secret = secret.encode()
    return hmac.new(secret, digest.encode(), hashlib.sha256).hexdigest()


def verify_signature(digest: str, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(sign_digest(digest), signature)


def require_permission_approval(required: list[str], approved: list[str]) -> None:
    if set(required) != set(approved):
        raise HTTPException(status_code=403, detail={"message": "Skill 权限未完整确认", "required": required})


def assert_data_scope(payload: Any, user_id: int, organization_ids: set[int]) -> None:
    if isinstance(payload, list):
        for value in payload: assert_data_scope(value, user_id, organization_ids)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            normalized = key.casefold().replace("_", "")
            if normalized in {"userid", "owneruserid"} and value is not None and int(value) != user_id:
                raise HTTPException(status_code=403, detail="Skill 不得读取其他用户数据")
            if normalized in {"organizationid", "orgid"} and value is not None and int(value) not in organization_ids:
                raise HTTPException(status_code=403, detail="Skill 不得读取其他组织数据")
            assert_data_scope(value, user_id, organization_ids)
