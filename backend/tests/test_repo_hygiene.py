from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[2]
SECRET_SCAN_SCRIPT = REPO_ROOT / "tools" / "secret_scan.py"


def load_secret_scan_module():
    spec = importlib.util.spec_from_file_location("secret_scan", SECRET_SCAN_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gitignore_covers_local_env_backups_and_artifacts():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "!.env.example" in gitignore
    for expected in [
        ".env.*",
        "**/.env.*",
        "backend/.env.before-*",
        "frontend/dist/",
        "frontend/dist-*/",
        "frontend/dist.*/",
        "output/",
        "tmp/",
        "*.log",
        "*.db",
        "*.sqlite",
        ".cache/",
    ]:
        assert expected in gitignore


def test_secret_scan_config_targets_real_secrets_without_placeholder_noise():
    config = tomllib.loads((REPO_ROOT / ".secret-scan.toml").read_text(encoding="utf-8"))

    assert ".git/**" in config["scanner"]["ignore_globs"]
    assert "frontend/node_modules/**" in config["scanner"]["ignore_globs"]
    assert "SECRET" in config["scanner"]["secret_name_markers"]
    assert "replace-with-" in config["scanner"]["placeholder_prefixes"]
    assert {rule["name"] for rule in config["rules"]} == {
        "private-key-block",
        "credential-url",
        "json-secret-value",
    }


def test_secret_scan_flags_real_secrets_but_ignores_placeholders(tmp_path: Path):
    module = load_secret_scan_module()
    config = module.load_config()

    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / ".env.before-demo").write_text(
        "\n".join(
            [
                "APP_ACCESS_PASSWORD=replace-with-campus-password",
                "SESSION_SECRET=real-secret-value-1234567890",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / ".env.example").write_text(
        "APP_ACCESS_PASSWORD=replace-with-campus-password\n",
        encoding="utf-8",
    )
    (tmp_path / "notes.txt").write_text(
        "https://" + "alice" + ":" + "topsecret" + "@example.com\n",
        encoding="utf-8",
    )

    findings = module.scan_working_tree(tmp_path, config)
    reported = {f"{finding.path}:{finding.line}:{finding.rule}" for finding in findings}

    assert "backend/.env.before-demo:2:env-assignment" in reported
    assert "notes.txt:1:credential-url" in reported
    assert not any(finding.path == ".env.example" for finding in findings)
