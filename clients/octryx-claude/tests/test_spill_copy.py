import os
import uuid

from octryx_claude import hook_outputs, spill_copy
from octryx_claude.state import seat_config_dir

SESSION = str(uuid.UUID(int=11))  # Claude Code's session id, made up
KEY = str(uuid.UUID(int=12))  # the launcher's session key, made up


def _spill(state, session=SESSION, name="mcp-octryx-workflow_run_status-1.txt"):
    folder = seat_config_dir(state.root) / "projects" / "-repo" / session / "tool-results"
    folder.mkdir(parents=True)
    path = folder / name
    path.write_text('{"workflow_run": {"phase": {}}}')
    return path


def _call(tool, tool_input):
    return {"tool_name": tool, "tool_input": tool_input, "session_id": SESSION}


def test_the_sessions_own_spilled_output_is_read_from_a_copy_outside_the_state_directory(state):
    path = _spill(state)
    read = spill_copy.redirect(state, KEY, _call("Read", {"file_path": str(path), "limit": 50}))
    copy = read["file_path"]
    assert read["limit"] == 50 and not copy.startswith(str(state.root)) and copy.endswith(path.name)
    assert open(copy).read() == path.read_text() and oct(os.stat(copy).st_mode & 0o777) == "0o600"
    bash = spill_copy.redirect(state, KEY, _call("Bash", {"command": f"jq -c '.workflow_run.phase' {path} | head"}))
    assert bash["command"] == f"jq -c '.workflow_run.phase' {copy} | head"


def test_anything_else_under_the_state_directory_meets_the_protection_unchanged(state):
    other = _spill(state, session=str(uuid.UUID(int=13)))  # another session's output
    assert spill_copy.redirect(state, KEY, _call("Read", {"file_path": str(other)})) is None
    secret = state.root / "codex-seat"
    secret.mkdir()
    (secret / "auth.json").write_text("{}")
    path = _spill(state)
    sneaky = f"{path.parent}/../../../../../codex-seat/auth.json"
    assert spill_copy.redirect(state, KEY, _call("Read", {"file_path": sneaky})) is None
    link = path.parent / "link.txt"
    link.symlink_to(secret / "auth.json")
    assert spill_copy.redirect(state, KEY, _call("Read", {"file_path": str(link)})) is None
    mixed = spill_copy.redirect(state, KEY, _call("Bash", {"command": f"cat {path}; cat {secret}/auth.json"}))
    assert str(secret / "auth.json") in mixed["command"]  # only the spill is swapped; the platform still refuses


def test_the_decision_about_the_copy_carries_its_path_and_a_denial_stays_a_denial():
    redirected = {"file_path": "/tmp/octryx-tool-results/k/x.txt"}
    allowed = hook_outputs._redirected_output(None, redirected)
    assert allowed["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert allowed["hookSpecificOutput"]["updatedInput"] == redirected
    denied = hook_outputs._deny("no")
    assert hook_outputs._redirected_output(denied, redirected) == hook_outputs._deny("no")


def test_a_seat_config_dir_outside_the_state_directory_is_the_sessions_own_too(state, tmp_path, monkeypatch):
    shared = tmp_path / "elsewhere" / "claude-config-seat"
    folder = shared / "projects" / "-repo" / SESSION / "tool-results"
    folder.mkdir(parents=True)
    path = folder / "mcp-octryx-knowledge-workflow_run_status-1.txt"
    path.write_text('{"workflow_run": {}}')
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert spill_copy.redirect(state, KEY, _call("Read", {"file_path": str(path)})) is None  # before: not recognised
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(shared))
    read = spill_copy.redirect(state, KEY, _call("Read", {"file_path": str(path)}))
    assert read is not None and not read["file_path"].startswith(str(shared))
    bash = spill_copy.redirect(state, KEY, _call("Bash", {"command": f'jq -c ".workflow_run" "{path}"'}))
    assert bash is not None and str(path) not in bash["command"] and read["file_path"] in bash["command"]
    other = shared / "credentials.json"
    other.write_text("{}")
    assert spill_copy.redirect(state, KEY, _call("Read", {"file_path": str(other)})) is None  # the rest stays protected


def test_the_sessions_own_layout_is_recognised_whatever_the_hooks_environment_says(state, tmp_path, monkeypatch):
    shared = tmp_path / "home" / ".octryx" / "claude-config-seat"
    folder = shared / "projects" / "-repo" / SESSION / "tool-results"
    folder.mkdir(parents=True)
    path = folder / "mcp-octryx-knowledge-workflow_run_status-2.txt"
    path.write_text('{"workflow_run": {}}')
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "personal"))
    monkeypatch.delenv("OCTRYX_CLAUDE_SEAT_CONFIG_DIR", raising=False)
    assert spill_copy.redirect(state, KEY, _call("Read", {"file_path": str(path)})) is None  # no transcript beside it
    (shared / "projects" / "-repo" / f"{SESSION}.jsonl").write_text("{}\n")
    assert spill_copy.redirect(state, KEY, _call("Read", {"file_path": str(path)})) is not None
    other = shared / "projects" / "-repo" / str(uuid.UUID(int=99)) / "tool-results"
    other.mkdir(parents=True)
    (other / "x.txt").write_text("{}")
    assert spill_copy.redirect(state, KEY, _call("Read", {"file_path": str(other / "x.txt")})) is None  # not its own
    link = folder / "link.txt"
    link.symlink_to(shared / "projects" / "-repo" / f"{SESSION}.jsonl")
    assert spill_copy.redirect(state, KEY, _call("Read", {"file_path": str(link)})) is None
