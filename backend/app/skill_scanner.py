from __future__ import annotations

import re
from pathlib import Path
from typing import Any

TOOL_PATTERNS = {
    "destructive_tool": re.compile(r"(?:delete|destroy|terminate|isolate|disable|quarantine|block|ban)", re.I),
    "credential_access": re.compile(r"(?:password|secret|token|private[_ -]?key|cookie|credential)", re.I),
}
CODE_PATTERNS = {
    "executable_code": re.compile(r"(?:subprocess|os\.system|child_process|eval\s*\(|exec\s*\(|powershell|curl\s+[^\n]*\|\s*(?:sh|bash))", re.I),
    "prompt_injection": re.compile(r"(?:ignore\s+(?:all\s+)?previous instructions|忽略(?:之前|以上)指令|泄露系统提示词|reveal system prompt)", re.I),
    "secret_exfiltration": re.compile(r"(?:send|post|upload|exfiltrat)[^\n]{0,80}(?:secret|token|password|cookie|environment|env)", re.I),
}

def scan_skill_directory(directory: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    tools = manifest.get("permissions", {}).get("tools", []) if isinstance(manifest.get("permissions"), dict) else []
    permissions = manifest.get("permissions", {}) if isinstance(manifest.get("permissions"), dict) else {}
    allowed_groups = {"tools", "network", "files", "commands", "data"}
    for group in permissions:
        if group not in allowed_groups:
            findings.append({"code": "unknown_permission_group", "severity": "high", "location": "manifest.permissions",
                             "detail": f"未知权限组：{group}"})
    for tool in tools if isinstance(tools, list) else []:
        value = str(tool)
        for code, pattern in TOOL_PATTERNS.items():
            if pattern.search(value):
                findings.append({"code": code, "severity": "high", "location": "manifest.permissions.tools", "detail": f"危险工具权限：{value}"})
    for path in directory.rglob("*") if directory.is_dir() else []:
        if not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        try: text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError: continue
        for code, pattern in CODE_PATTERNS.items():
            if pattern.search(text):
                findings.append({"code": code, "severity": "critical" if code != "prompt_injection" else "high", "location": str(path.relative_to(directory)), "detail": "发现需要人工审核的危险内容"})
    severity = "critical" if any(item["severity"] == "critical" for item in findings) else "high" if findings else "clean"
    return {"status": severity, "safe": not findings, "findings": findings, "requiresReview": bool(findings)}
