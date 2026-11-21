"""The environment file: its commands in its app folder, unit-only classes, refused or missing files and setup."""

from __future__ import annotations

from types import SimpleNamespace

from octryx_claude import pipeline

CLAUDE_FILE = "coffee/web/claude/.octryx/environment.json"


CODEX_FILE = "coffee/web/codex/.octryx/environment.json"


def _env_file(root, file, content):
    import json

    target = root / file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content if isinstance(content, str) else json.dumps(content))


def _file_view(file=CLAUDE_FILE, folder="coffee/web/claude"):
    return {"node_id": "pipeline", "entry": 3, "commands": [], "path": [],
            "environment_file": {"file": file, "app_folder": folder}}


def _report_of(tmp_path, monkeypatch, view):
    posts = []

    def call(_state, _context, method, path, **kwargs):
        posts.append((path, kwargs.get("body")))
        return SimpleNamespace(outcome="ok", body={"state": "stored"}, state="stored")

    monkeypatch.setattr(pipeline, "call_control_plane", call)
    monkeypatch.setattr(pipeline, "remember", lambda *_a: {})
    context = SimpleNamespace(session_key="00000000-0000-0000-0000-000000000002")
    assert pipeline.pending({"pipeline": view}) is view  # a pointer without commands is a pending pipeline
    pipeline.run_for_session(None, context, {"pipeline": view}, str(tmp_path), http=None)
    return [body for path, body in posts if path == "/sessions/pipeline"][0]


def test_the_environment_file_runs_exactly_its_commands_in_its_app_folder(tmp_path, monkeypatch):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _env_file(tmp_path, CLAUDE_FILE, {
        "setup": ["mkdir -p tools && printf '#!/bin/sh\\necho tool-ran\\n' > tools/mytool && chmod +x tools/mytool"],
        "test": "pwd > ran-unit.txt && mytool", "system_test": "pwd > ran-system.txt", "path": ["tools"]})
    _env_file(tmp_path, CODEX_FILE, {"test": "pwd > codex-ran.txt"})
    report = _report_of(tmp_path, monkeypatch, _file_view())
    app = (tmp_path / "coffee/web/claude").resolve()
    assert [item["command"] for item in report["results"]] == ["pwd > ran-unit.txt && mytool", "pwd > ran-system.txt"]
    assert [item["exit_code"] for item in report["results"]] == [0, 0] and "tool-ran" in report["results"][0][
        "output_tail"]  # ``path`` is relative to the app folder
    assert (app / "ran-unit.txt").read_text().strip() == str(app) and (app / "ran-system.txt").is_file()
    assert not (tmp_path / "coffee/web/codex/codex-ran.txt").exists()  # the other Workspace's folder is never run
    account = report["environment_file"]
    assert (account["file"], account["app_folder"], account["state"]) == (CLAUDE_FILE, "coffee/web/claude", "ok")
    assert len(account["sha256"]) == 64 and account["commands"] == [item["command"] for item in report["results"]]
    assert account["setup"][0]["exit_code"] == 0  # no ``check``: the setup ran first
    exclude = (tmp_path / ".git/info/exclude").read_text()
    assert "/coffee/web/claude/tools/" in exclude and "/coffee/web/claude/test-reports/" in exclude


def test_a_class_without_the_system_test_runs_only_the_unit_tests(tmp_path, monkeypatch):
    """Size class S without a UI label (``pipeline_scope``): the system test, 177 s of a 469 s Flutter
    bug, stays out; the unit tests run."""
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _env_file(tmp_path, CLAUDE_FILE, {"test": "touch ran-unit.txt", "system_test": "touch ran-system.txt"})
    report = _report_of(tmp_path, monkeypatch, {**_file_view(), "system_test": False})
    app = tmp_path / "coffee/web/claude"
    assert [item["command"] for item in report["results"]] == ["touch ran-unit.txt"]
    assert (app / "ran-unit.txt").is_file() and not (app / "ran-system.txt").exists()
    timings = report["timings"]  # where the pipeline's time went, measured per step
    assert {"tree", "setup", "commands", "red_on_base", "total"} <= set(timings)
    assert timings["total"] >= timings["commands"] >= 0


def test_an_invalid_or_refused_file_runs_nothing_and_says_why(tmp_path, monkeypatch):
    _env_file(tmp_path, CLAUDE_FILE, {"setup": ["sudo apt-get install -y chromium"], "test": "touch ran.txt"})
    report = _report_of(tmp_path, monkeypatch, _file_view())
    assert report["results"] == [] and report["environment_file"]["state"] == "invalid"
    assert "refused" in report["environment_file"]["errors"][0]
    assert not (tmp_path / "coffee/web/claude/ran.txt").exists()
    assert "not a valid environment file" in pipeline.file_summary(report["environment_file"])


def test_a_missing_file_reports_missing_and_the_summary_says_to_create_it(tmp_path, monkeypatch):
    report = _report_of(tmp_path, monkeypatch, _file_view())
    assert report["results"] == [] and report["environment_file"]["state"] == "missing"
    summary = pipeline.file_summary(report["environment_file"])
    assert summary.startswith(f"{CLAUDE_FILE} does not exist") and "runs exactly those in coffee/web/claude/" in summary


def test_a_failing_setup_runs_no_test_and_a_passing_check_skips_the_setup(tmp_path, monkeypatch):
    _env_file(tmp_path, CLAUDE_FILE, {"setup": ["echo broken; exit 2"], "test": "touch ran.txt"})
    report = _report_of(tmp_path, monkeypatch, _file_view())
    assert report["results"] == [] and report["environment_file"]["state"] == "setup_failed"
    assert report["environment_file"]["setup"][0]["exit_code"] == 2
    _env_file(tmp_path, CLAUDE_FILE, {"setup": ["exit 2"], "check": ["true"], "test": "touch ran.txt"})
    report = _report_of(tmp_path, monkeypatch, _file_view())
    assert report["environment_file"]["state"] == "ok" and report["environment_file"]["setup"] == []
    assert (tmp_path / "coffee/web/claude/ran.txt").is_file()
