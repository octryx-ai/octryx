"""octryx's context manager: what a compaction keeps, put back afterwards; switchable off."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from octryx_claude import context_manager as cm
from octryx_claude import launch_settings
from octryx_claude.state import LocalState

SHIM = Path("/usr/local/bin/octryx-claude")


def _line(**entry) -> str:
    return json.dumps(entry)


def _transcript(tmp_path: Path) -> Path:
    lines = [
        _line(type="user", message={"role": "user", "content": "Goal: a tiny calculator module calc.py"}),
        _line(type="assistant", message={"content": [
            {"type": "tool_use", "id": "w1", "name": "Write",
             "input": {"file_path": "/repo/calc.py", "content": "x"}},
            {"type": "tool_use", "id": "b1", "name": "Bash",
             "input": {"command": "cd /repo && JWT=x python -m pytest -q"}},
            {"type": "tool_use", "id": "b2", "name": "Bash",
             "input": {"command": "python3 - <<'EOF'\np='a|jest|b'\nEOF"}},
            {"type": "tool_use", "id": "t1", "name": "TodoWrite", "input": {"todos": [
                {"content": "add mul()", "status": "pending"}, {"content": "add()", "status": "completed"}]}}]}),
        _line(type="user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "b1",
                                                                  "is_error": True, "content": "1 failed"}]}),
        _line(type="user", isMeta=True,
              message={"role": "user", "content": "<system-reminder>noise</system-reminder>"}),
        _line(type="user", isMeta=True, origin={"kind": "peer", "name": "octryx-mobile",
                                                 "body": "[owner via Octryx Mobile, from the phone] integers only"},
              message={"role": "user", "content": "Another Claude session sent a message: ..."}),
        _line(type="user", message={"role": "user", "content": "<command-name>/model</command-name>"}),
        _line(type="assistant", message={"content": [
            {"type": "tool_use", "id": "e1", "name": "Edit", "input": {"file_path": "/repo/calc.py"}},
            {"type": "tool_use", "id": "e2", "name": "Edit", "input": {"file_path": "/repo/test_calc.py"}}]}),
        "not json",
    ]
    path = LocalState(tmp_path / "state").claude_config_dir / "projects" / "p" / "t.jsonl"  # octryx's own dir
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    return path


def test_extracts_goal_requests_files_tests_and_todos(tmp_path):
    facts = cm.extract(_transcript(tmp_path).read_text().splitlines())
    assert facts["goal"] == "Goal: a tiny calculator module calc.py"
    assert facts["requests"][0] == "(from octryx-mobile) [owner via Octryx Mobile, from the phone] integers only"
    assert all("system-reminder" not in item and "/model" not in item for item in facts["requests"])
    assert facts["files"] == ["/repo/calc.py", "/repo/test_calc.py"]
    assert facts["tests"] == [{"command": "cd /repo && JWT=x python -m pytest -q", "passed": False}]
    assert facts["todos"] == ["add mul()"]


@pytest.mark.parametrize(("command", "is_test"), [
    ("npm test", True), ("cd x && JWT=y python -m pytest -q", True), ("/v/bin/python -m pytest", True),
    ("./gradlew test", True), ("mvn -q verify", True), ("mvn clean install", False), ("gradle build", False),
    ("grep -n 'def make' x.py | head", False), ("python3 - <<'EOF'\np='a|jest|b'\nEOF", False),
])
def test_only_commands_that_start_with_a_test_runner_count(command, is_test):
    assert cm.is_test_command(command) is is_test


def test_pre_compact_writes_instructions_and_session_start_puts_them_back(tmp_path):
    state = LocalState(tmp_path / "state")
    hook = {"transcript_path": str(_transcript(tmp_path)), "session_id": "s-1"}
    text = cm.pre_compact(state, hook, rank=False)
    assert text.startswith("octryx context manager: in the summary, keep")
    assert "/repo/calc.py" in text and "FAILED" in text and "add mul()" in text and len(text) <= cm.MAX_INSTRUCTIONS
    restored = cm.session_start(state, {"source": "compact", "session_id": "s-1"})
    context = restored["hookSpecificOutput"]["additionalContext"]
    assert restored["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert context.startswith("Restored by octryx after the compaction") and "integers only" in context
    assert cm.session_start(state, {"source": "startup", "session_id": "s-1"}) is None
    assert cm.session_start(state, {"source": "compact", "session_id": "../../etc"}) is None


def test_switched_off_it_answers_nothing(tmp_path, monkeypatch):
    state = LocalState(tmp_path / "state").ensure()
    hook = {"transcript_path": str(_transcript(tmp_path)), "session_id": "s-1"}
    state.write_config({"context_manager": False})
    assert cm.pre_compact(state, hook, rank=False) == ""
    assert cm.session_start(state, {"source": "compact", "session_id": "s-1"}) is None
    state.write_config({})
    monkeypatch.setenv("OCTRYX_CONTEXT_MANAGER", "0")
    assert cm.pre_compact(state, hook, rank=False) == ""
    monkeypatch.delenv("OCTRYX_CONTEXT_MANAGER")
    assert cm.pre_compact(state, hook, rank=False) != ""
    assert cm.pre_compact(state, {"transcript_path": "/nope", "session_id": "s"}, rank=False) == ""
    elsewhere = tmp_path / "elsewhere.jsonl"  # a transcript outside octryx's config dirs is never read
    elsewhere.write_text(_transcript(tmp_path).read_text())
    assert cm.pre_compact(state, {"transcript_path": str(elsewhere), "session_id": "s"}, rank=False) == ""


def test_every_governed_session_registers_both_hooks():
    settings = launch_settings.build_settings(shim=SHIM, state_root=Path("/s"), env={}, policy={"state": "allowed"},
                                     base_url="https://octryx.example.test")
    pre = settings["hooks"]["PreCompact"][0]
    start = settings["hooks"]["SessionStart"][0]
    assert pre["hooks"][0]["command"].endswith("hook pre-compact")
    assert start["matcher"] == "compact" and start["hooks"][0]["command"].endswith("hook session-start")
