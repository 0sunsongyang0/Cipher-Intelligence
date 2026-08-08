from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def load_workflow(name: str) -> dict:
    with (WORKFLOWS_DIR / name).open(encoding="utf-8") as workflow_file:
        return yaml.load(workflow_file, Loader=yaml.BaseLoader)


def test_frontend_ci_runs_all_required_checks():
    workflow = load_workflow("ci.yml")
    job = workflow["jobs"]["frontend"]
    steps = job["steps"]
    commands = [step["run"] for step in steps if "run" in step]

    assert workflow["concurrency"]["cancel-in-progress"] == "true"
    assert job["timeout-minutes"] == "20"
    assert any(step.get("with", {}).get("cache") == "npm" for step in steps)
    assert commands == [
        "npm ci",
        "npm test",
        "npm exec tsc -- --project tsconfig.json && npm exec tsc -- --project tsconfig.node.json",
        "npm run build",
    ]


def test_backend_ci_is_isolated_and_uses_test_credentials():
    workflow = load_workflow("ci.yml")
    job = workflow["jobs"]["backend"]
    steps = job["steps"]
    commands = "\n".join(step["run"] for step in steps if "run" in step)

    assert workflow["concurrency"]["cancel-in-progress"] == "true"
    assert job["timeout-minutes"] == "30"
    assert job["env"]["APP_ENV"] == "test"
    assert job["env"]["DATABASE_URL"].startswith("sqlite:///")
    assert all("${{ secrets." not in value for value in job["env"].values())
    assert any(step.get("with", {}).get("python-version") == "3.12" for step in steps)
    assert any(step.get("with", {}).get("cache") == "pip" for step in steps)
    assert "python -m venv .venv" in commands
    assert "pip install -r requirements.txt" in commands
    assert "python -m ruff check app tests" in commands
    assert "python -m pytest -n auto -q" in commands


def test_merge_gate_requires_both_ci_jobs():
    workflow = load_workflow("ci.yml")
    gate = workflow["jobs"]["merge-gate"]

    assert workflow["permissions"] == {"contents": "read"}
    assert gate["if"] == "always()"
    assert gate["needs"] == ["frontend", "backend"]
    assert gate["timeout-minutes"] == "5"
    assert "FRONTEND_RESULT" in gate["steps"][0]["run"]
    assert "BACKEND_RESULT" in gate["steps"][0]["run"]
