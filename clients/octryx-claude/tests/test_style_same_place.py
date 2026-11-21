"""The agent runs the platform's style check the same way and in the same place (5a059ed7:
ruff from the repository root wanted I001 that the agent's ruff in the app folder did not; f34f0640: `dart format`
could not run inside the sandbox, printed only "Operation not permitted", and the agent read the silence as clean)."""

import json
from pathlib import Path

from octryx_claude import hook_outputs, local_tests, local_tests_screens, style_tools
from octryx_claude.code_map import style_commands

SHIM = "/Users/u/.local/bin/octryx-claude"
STYLE = {"languages": {
    "dart": {"formatter": {"command": "dart format --output=none --set-exit-if-changed {files}",
                           "outside_sandbox": True},
             "linter": {"command": "flutter analyze --no-pub", "outside_sandbox": True}},
    "python": {"formatter": {"command": "ruff format --check {files}"},
               "linter": {"command": "ruff check --select E,F,I,B {files}"}}}}
CONTRACT = {"digest": "d", "phase": {"node_id": "implement", "capability_class": "change", "code_style": STYLE}}


def _hook(command: str) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/repo", "tool_input": {"command": command}}


def test_the_style_tools_run_in_the_app_folder_where_the_agent_works(tmp_path: Path):
    app = tmp_path / "e2e" / "python"
    (app / ".octryx").mkdir(parents=True)
    (app / ".octryx" / "environment.json").write_text("{}")
    (app / "tests").mkdir()
    assert style_tools._package(tmp_path, "e2e/python/tests/test_tip.py", "python") == app


def test_a_style_tool_on_its_own_runs_outside_the_sandbox_and_among_others_is_refused_with_its_form():
    for command in ("dart format test/a_test.dart lib", "flutter analyze --no-pub", "ruff check --select E tests/x.py"):
        output = hook_outputs.test_run_output(_hook(command), CONTRACT, SHIM)
        assert output["hookSpecificOutput"]["updatedInput"]["command"].startswith(f"{SHIM} test-run "), command
    piped = _hook("dart format test/a_test.dart 2>&1 | grep -v x; git status")
    refused = hook_outputs.test_run_output(piped, CONTRACT, SHIM)
    reason = refused["hookSpecificOutput"]["permissionDecisionReason"]
    assert refused["hookSpecificOutput"]["permissionDecision"] == "deny" and "run `dart format <files>`" in reason
    assert hook_outputs.test_run_output(_hook("ruff check . && git status"), CONTRACT, SHIM) is None  # ruff runs in it
    # never wrapped outside the repo
    outside = hook_outputs.test_run_output(_hook("dart format /etc/passwd"), CONTRACT, SHIM)
    assert outside["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_a_style_tool_that_could_not_run_in_the_sandbox_is_named_and_its_silence_never_reads_as_clean():
    tools = local_tests.style_tools(CONTRACT)
    failed = {"tool_name": "Bash", "tool_input": {"command": "dart format test/x.dart 2>&1 | tail -2"},
              "tool_response": {"stdout": "line 71: engine.stamp.tmp: Operation not permitted", "stderr": ""}}
    assert local_tests_screens.sandbox_tool_failure(failed, tools) == "dart format"
    clean = {**failed, "tool_response": {"stdout": "Formatted 1 file (0 changed)", "stderr": ""}}
    assert local_tests_screens.sandbox_tool_failure(clean, tools) is None


def test_the_code_map_names_the_platforms_style_commands_for_the_apps_languages():
    commands = style_commands(["app/lib/main.dart", "app/test/a_test.dart"], CONTRACT)
    assert commands == ["dart format --output=none --set-exit-if-changed <files>", "flutter analyze --no-pub"]


class _RanError(Exception):
    pass


def _wrapper_runs(command: str, home: Path, monkeypatch, contract: dict | None) -> bool:
    """``run_wrapped`` on the hook's own wrapped form: ``True`` when it hands the command to the shell."""
    key = "00000000-0000-0000-0000-0000000000a5"
    if contract is not None:
        (home / "sessions" / key).mkdir(parents=True)
        (home / "sessions" / key / "workflow_run.json").write_text(json.dumps(contract))
    monkeypatch.setenv("OCTRYX_CLAUDE_HOME", str(home))
    monkeypatch.setenv("OCTRYX_SESSION_KEY", key)
    monkeypatch.chdir(home)

    def ran(*_args):
        raise _RanError

    monkeypatch.setattr(local_tests.os, "execv", ran)
    output = hook_outputs.test_run_output(_hook(command), CONTRACT, SHIM)
    wrapped = output["hookSpecificOutput"]["updatedInput"]["command"]
    try:
        return local_tests.run_wrapped([wrapped.split()[-1]]) != local_tests.REFUSED_EXIT
    except _RanError:
        return True


def test_the_wrapper_runs_every_style_command_the_hook_wrapped(tmp_path: Path, monkeypatch):
    """Style commands the hook wrapped (`ruff check`, `dart format`) pass the wrapper's check with the contract's
    style tools."""
    for index, command in enumerate(("ruff check --select E,F,I,B tests/x.py", "ruff format --check tests/x.py",
                                     "dart format lib/a.dart test/a_test.dart")):
        assert _wrapper_runs(command, tmp_path / str(index), monkeypatch, CONTRACT), command


def test_the_wrapper_refuses_a_style_command_without_the_sessions_contract(tmp_path: Path, monkeypatch):
    assert not _wrapper_runs("ruff check tests/x.py", tmp_path, monkeypatch, None)
