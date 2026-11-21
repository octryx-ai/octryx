"""The repository's own environment file: the record points at a file in the run's branch, the file declares the
story's test commands, everything is scoped to its app folder."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import uuid
from types import SimpleNamespace

import pytest

from app.models import CodeRepository, Project
from app.services.workflow_runs.workspace import spec

LAUNCHER_MODULE = pathlib.Path(__file__).parents[2] / "clients" / "octryx-claude" / "octryx_claude" / "environment_file.py"
CLAUDE_FILE = "coffee/web/claude/.octryx/environment.json"
CODEX_FILE = "coffee/web/codex/.octryx/environment.json"
VALID = {"setup": ["python3 -m venv .venv", ".venv/bin/pip install -r requirements.txt pytest pytest-playwright"],
         "check": [".venv/bin/python -c 'import pytest, playwright'"],
         "test": ".venv/bin/python -m pytest -v tests/unit", "system_test": ".venv/bin/python -m pytest -v tests/system",
         "path": [".venv/bin"], "browser": "chrome"}


def _write(root: pathlib.Path, file: str, content) -> None:
    target = root / file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content if isinstance(content, str) else json.dumps(content))


def test_the_pointer_is_a_relative_json_path_and_its_app_folder_holds_the_octryx_folder():
    assert spec.validate_environment_file(CLAUDE_FILE) == (CLAUDE_FILE, [])
    assert spec.validate_environment_file(None) == (None, []) and spec.validate_environment_file("") == (None, [])
    for bad in ("/etc/environment.json", "../x/.octryx/environment.json", "a/../../b.json", "app/env.yaml",
                "a" * 200 + ".json", 7, "a\\b.json"):
        assert spec.validate_environment_file(bad)[1], bad
    assert spec.app_folder(CLAUDE_FILE) == "coffee/web/claude"
    assert spec.app_folder(".octryx/environment.json") == "."
    assert spec.app_folder("app/environment.json") == "app"


def test_the_file_is_read_and_validated_every_time(tmp_path):
    assert spec.read_environment_file(tmp_path, CLAUDE_FILE)["state"] == "missing"
    _write(tmp_path, CLAUDE_FILE, VALID)
    read = spec.read_environment_file(tmp_path, CLAUDE_FILE)
    assert read["state"] == "ok" and read["environment"]["test"] == VALID["test"] and len(read["sha256"]) == 64
    assert read["app_folder"] == "coffee/web/claude"
    _write(tmp_path, CLAUDE_FILE, {**VALID, "setup": ["sudo apt-get install chromium"]})
    refused = spec.read_environment_file(tmp_path, CLAUDE_FILE)
    assert refused["state"] == "invalid" and "refused" in refused["errors"][0]
    _write(tmp_path, CLAUDE_FILE, "{not json")
    assert spec.read_environment_file(tmp_path, CLAUDE_FILE)["errors"][0].startswith("not valid JSON")
    _write(tmp_path, CLAUDE_FILE, {"system_test": "pytest tests/system"})
    assert "required" in spec.read_environment_file(tmp_path, CLAUDE_FILE)["errors"][0]


def test_a_link_out_of_the_repository_is_not_read(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(VALID))
    repo = tmp_path / "repo"
    (repo / "app" / ".octryx").mkdir(parents=True)
    (repo / "app" / ".octryx" / "environment.json").symlink_to(outside)
    assert spec.read_environment_file(repo, "app/.octryx/environment.json")["state"] == "invalid"


def test_the_runtime_gets_only_the_pointer():
    pointer = {"source": spec.SOURCE_ENVIRONMENT_FILE, "environment_file": CLAUDE_FILE,
               "app_folder": "coffee/web/claude", **VALID}
    runtime = spec.runtime_environment(pointer)
    assert runtime["environment_file"] == CLAUDE_FILE and runtime["app_folder"] == "coffee/web/claude"
    assert runtime["setup"] == [] and runtime["test"] == "" and runtime["probes"] == []


async def _records(db):
    projects = [Project(name=f"coffee-{uuid.uuid4().hex[:6]}", config={}) for _ in range(2)]
    db.add_all(projects)
    await db.flush()
    for project, file in zip(projects, (CLAUDE_FILE, CODEX_FILE)):
        db.add(CodeRepository(project_id=project.id, name="octryx-ai/bench", repo_root="/r", provider="github",
                              config_json={"coding_setup": {"environment_file": file,
                                                            "environment": {"test": "pytest -q"}}}))
    await db.flush()
    return projects


@pytest.mark.asyncio
async def test_each_workspace_reads_only_its_own_folder(db, tmp_path):
    claude, codex = await _records(db)
    _write(tmp_path, CLAUDE_FILE, {"test": "sudo make test"})  # broken on purpose: the Codex run never sees it
    _write(tmp_path, CODEX_FILE, {**VALID, "test": "npm test"})

    def run(project):
        return SimpleNamespace(project_id=project.id, repository="github:octryx-ai/bench",
                               context={"local_path": str(tmp_path)})

    codex_env = await spec.environment_for_run(db, run(codex))
    assert codex_env["environment_file"] == CODEX_FILE and codex_env["app_folder"] == "coffee/web/codex"
    assert codex_env["file_state"] == "ok" and codex_env["test"] == "npm test" and "file_errors" not in codex_env
    claude_env = await spec.environment_for_run(db, run(claude))
    assert claude_env["environment_file"] == CLAUDE_FILE and claude_env["file_state"] == "invalid"
    assert "test" not in claude_env  # the record's ``environment`` does not stand in for an invalid file


@pytest.mark.asyncio
async def test_a_record_without_the_pointer_keeps_its_declaration(db, tmp_path):
    project = Project(name=f"plain-{uuid.uuid4().hex[:6]}", config={})
    db.add(project)
    await db.flush()
    db.add(CodeRepository(project_id=project.id, name="octryx-ai/plain", repo_root="/r", provider="github",
                          config_json={"coding_setup": {"environment": {"test": "pytest -q"}}}))
    await db.flush()
    _write(tmp_path, ".octryx/environment.json", VALID)  # in the folder, but nobody pointed at it
    run = SimpleNamespace(project_id=project.id, repository="github:octryx-ai/plain",
                          context={"local_path": str(tmp_path)})
    environment = await spec.environment_for_run(db, run)
    assert environment["source"] == spec.SOURCE_DECLARED and environment["test"] == "pytest -q"


def test_the_launcher_validates_like_the_platform():
    """The device cannot import the backend: its copy of the rules must give the same answers."""
    loaded = importlib.util.spec_from_file_location("launcher_environment_file", LAUNCHER_MODULE)
    launcher = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(launcher)
    samples = [VALID, {"test": "pytest"}, {"test": "npm i -g x"}, {"test": "pytest", "path": ["../x"]},
               {"test": "pytest", "browser": "firefox"}, {"test": "pytest", "extra": 1}, {"setup": ["pip install --user x"]},
               {"test": "pytest", "setup": ["brew install node"]}, "text", {}, {"test": "x" * 1001}]
    for sample in samples:
        assert launcher.validate_environment(sample) == spec.validate_environment(sample), sample
    for path in (CLAUDE_FILE, ".octryx/environment.json", "app/environment.json"):
        assert launcher.app_folder(path) == spec.app_folder(path)


def test_the_building_agent_is_told_where_to_declare_its_tests():
    from app.services.workflow_runs.octryx.contract import environment_file_rule

    pointer = {"environment_file": CLAUDE_FILE, "app_folder": "coffee/web/claude"}
    rule = environment_file_rule("change", pointer)
    assert rule["file"] == CLAUDE_FILE
    assert rule["rule"].startswith(f"Declare this story's test commands in {CLAUDE_FILE}")
    assert "runs exactly those in coffee/web/claude/" in rule["rule"] and '"system_test"' in rule["rule"]
    assert environment_file_rule("read", pointer) is None and environment_file_rule("change", {"test": "x"}) is None


def test_the_preparation_never_pauses_on_the_environment_file():
    """The pipeline judges the file (and sends a missing or invalid one back to the agent); the folder's
    preparation reports it and goes on."""
    from app.services.workflow_runs.workspace.preparation import decide

    for file_state in ("missing", "invalid", "setup_failed", "ok"):
        report = {"branch": {"state": "already"},
                  "environment": {"state": "environment_file", "environment_file": {"state": file_state}}}
        assert decide(report).ok, file_state


def test_the_runtime_environment_of_an_environment_file_says_where_the_commands_are():
    """Finding 3 (top-10 #10): the empty test/lint of an environment-file app read as "no tests" to the agent."""
    from app.services.workflow_runs.workspace.spec import SOURCE_ENVIRONMENT_FILE, runtime_environment

    found = runtime_environment({"source": SOURCE_ENVIRONMENT_FILE, "environment_file": "app/.octryx/environment.json",
                                 "app_folder": "app"})
    assert found["test"] == "" and found["lint"] == ""  # the runtime still reads the file itself
    assert found["commands"].startswith("read from app/.octryx/environment.json on the device")
