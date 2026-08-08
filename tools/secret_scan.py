from __future__ import annotations

import argparse
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable
import tomllib


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / ".secret-scan.toml"


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class Finding:
    scope: str
    path: str
    line: int
    rule: str


@dataclass(frozen=True)
class ScannerConfig:
    ignore_globs: tuple[str, ...]
    max_bytes: int
    placeholder_prefixes: tuple[str, ...]
    secret_name_markers: tuple[str, ...]
    rules: tuple[Rule, ...]


def load_config(config_path: Path = DEFAULT_CONFIG) -> ScannerConfig:
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    scanner = raw.get("scanner", {})
    ignore_globs = tuple(scanner.get("ignore_globs", []))
    max_bytes = int(scanner.get("max_bytes", 1_048_576))
    placeholder_prefixes = tuple(scanner.get("placeholder_prefixes", []))
    secret_name_markers = tuple(scanner.get("secret_name_markers", []))
    rules = tuple(
        Rule(name=item["name"], pattern=re.compile(item["pattern"]))
        for item in raw.get("rules", [])
    )
    return ScannerConfig(
        ignore_globs=ignore_globs,
        max_bytes=max_bytes,
        placeholder_prefixes=placeholder_prefixes,
        secret_name_markers=secret_name_markers,
        rules=rules,
    )


def normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_ignored(path: str, ignore_globs: Iterable[str]) -> bool:
    normalized = normalize_path(path)
    return any(fnmatch(normalized, pattern) for pattern in ignore_globs)


def is_probably_text(data: bytes) -> bool:
    if b"\0" in data:
        return False
    if not data:
        return True
    sample = data[:4096]
    printable = sum(
        byte in b"\n\r\t\f\b" or 32 <= byte <= 126 for byte in sample
    )
    return printable / len(sample) >= 0.75


def looks_placeholder(value: str, prefixes: Iterable[str]) -> bool:
    lowered = value.strip().strip('"').strip("'").casefold()
    if not lowered:
        return True
    return any(lowered.startswith(prefix.casefold()) for prefix in prefixes)


def is_env_like_path(path: str) -> bool:
    lowered = normalize_path(path).casefold()
    return lowered.endswith(
        (
            ".env",
            ".env.example",
            ".env.local",
            ".env.development",
            ".env.production",
            ".sh",
            ".bash",
            ".zsh",
            ".ps1",
            ".bat",
            ".cmd",
            ".json",
            ".toml",
            ".ini",
            ".cfg",
            ".conf",
            ".service",
            ".yml",
            ".yaml",
        )
    ) or "/.env." in lowered or lowered.startswith(".env.")


def scan_text(
    text: str,
    *,
    scope: str,
    path: str,
    rules: Iterable[Rule],
    placeholder_prefixes: Iterable[str],
    secret_name_markers: Iterable[str],
) -> list[Finding]:
    findings: list[Finding] = []
    env_line = re.compile(r"^\s*(?:export\s+)?(?P<name>[A-Z0-9_]+)\s*=\s*(?P<value>.+?)\s*$")
    marker_set = tuple(marker.casefold() for marker in secret_name_markers)

    for line_number, line in enumerate(text.splitlines(), start=1):
        env_match = env_line.match(line) if is_env_like_path(path) else None
        if env_match:
            name = env_match.group("name")
            value = env_match.group("value").split("#", 1)[0].strip()
            lowered_name = name.casefold()
            if any(marker in lowered_name for marker in marker_set):
                if value and not looks_placeholder(value, placeholder_prefixes):
                    findings.append(
                        Finding(scope=scope, path=path, line=line_number, rule="env-assignment")
                    )

        for rule in rules:
            if rule.pattern.search(line):
                findings.append(
                    Finding(scope=scope, path=path, line=line_number, rule=rule.name)
                )

    return findings


def scan_file(
    root: Path,
    path: Path,
    config: ScannerConfig,
    *,
    scope: str,
) -> list[Finding]:
    rel = normalize_path(str(path.relative_to(root)))
    if is_ignored(rel, config.ignore_globs):
        return []
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if len(data) > config.max_bytes or not is_probably_text(data):
        return []
    text = data.decode("utf-8", errors="replace")
    return scan_text(
        text,
        scope=scope,
        path=rel,
        rules=config.rules,
        placeholder_prefixes=config.placeholder_prefixes,
        secret_name_markers=config.secret_name_markers,
    )


def scan_working_tree(root: Path, config: ScannerConfig) -> list[Finding]:
    findings: list[Finding] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if ".git" in path.parts:
            continue
        findings.extend(scan_file(root, path, config, scope="working-tree"))
    return findings


def run_git(root: Path, *args: str, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        input=input_text,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def scan_history(root: Path, config: ScannerConfig) -> list[Finding]:
    findings: list[Finding] = []
    history = run_git(root, "rev-list", "--all", "--objects")
    blobs: dict[str, str] = {}
    for line in history.splitlines():
        oid, _, rel = line.partition(" ")
        if not rel:
            continue
        rel = normalize_path(rel)
        if is_ignored(rel, config.ignore_globs):
            continue
        blobs.setdefault(oid, rel)

    if not blobs:
        return findings

    oids = list(blobs)
    batch_check = run_git(root, "cat-file", "--batch-check", input_text="\n".join(oids) + "\n")
    eligible_oids: list[str] = []
    for line in batch_check.splitlines():
        oid, obj_type, size_text = line.split()
        if obj_type != "blob":
            continue
        if int(size_text) > config.max_bytes:
            continue
        eligible_oids.append(oid)

    if not eligible_oids:
        return findings

    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    try:
        proc.stdin.write(("\n".join(eligible_oids) + "\n").encode("utf-8"))
        proc.stdin.close()
        for oid in eligible_oids:
            header = proc.stdout.readline().decode("utf-8").strip()
            if not header:
                break
            header_oid, obj_type, size_text = header.split()
            size = int(size_text)
            data = proc.stdout.read(size)
            proc.stdout.read(1)
            if obj_type != "blob" or not is_probably_text(data):
                continue
            rel = blobs.get(header_oid)
            if rel is None:
                continue
            text = data.decode("utf-8", errors="replace")
            findings.extend(
                scan_text(
                    text,
                    scope="history",
                    path=rel,
                    rules=config.rules,
                    placeholder_prefixes=config.placeholder_prefixes,
                    secret_name_markers=config.secret_name_markers,
                )
            )
    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
        proc.wait()

    return findings


def format_finding(finding: Finding) -> str:
    return f"{finding.scope}:{finding.path}:{finding.line}:{finding.rule}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan the repository for likely secrets.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to the TOML config.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root to scan.")
    parser.add_argument("--history", action="store_true", help="Scan reachable git history as well.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    root = args.root.resolve()
    findings = scan_working_tree(root, config)
    if args.history:
        findings.extend(scan_history(root, config))

    if findings:
        for finding in findings:
            print(format_finding(finding))
        return 1

    print("No likely secrets found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
