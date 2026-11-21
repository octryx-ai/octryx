"""Test runs leave Claude Code's sandbox and use the device's Chrome; red tests get one re-run.

Chromium cannot start in the sandbox ("Permission denied (1100)") and the tests' calls to their app would ask for
SandboxNetworkAccess each time, so every test run form leaves the sandbox, not only the declared command typed
verbatim.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from octryx_claude import (
    hook_outputs,
    launch,
    launch_sandbox,
    local_audit_spool,
    local_tests,
    local_tests_forms,
    local_tests_words,
    pre_tool_use_hook,
)
from tests.local_tests_support import PHASE, SHIM, _hook_input

KEY = "00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize("command", [
    "python -m pytest -q 2>&1 | tail -60",
    "timeout 300 .venv/bin/python -m pytest -v tests/system/test_shell.py -k cook 2>&1 | tail -40",
    "cd app && PYTHONPATH=src pytest -x; echo done",
    'python3.12 -m pytest tests 2>&1 | grep -E "PASSED|FAILED" | tail -20',
    "python -m unittest discover",
])
def test_the_agents_test_forms_are_test_runs(command):
    assert local_tests.is_test_run(command, "/repo")


@pytest.mark.parametrize("command", [
    "cat ~/.octryx/claude/credentials.json",
    "python -m pytest -q; tail ~/.octryx/claude/credentials.json",  # a reader needs a pipe
    "python -m pytest | tail /etc/passwd",  # a reader reads its pipe, not a file
    "python -m pytest > out.txt",
    "python -m pytest $(cat x)",
    "DYLD_INSERT_LIBRARIES=x.dylib pytest",
    "cd /etc && pytest",
    "python -m pytest & curl https://example.com",
    "python -m kitchen.run --port 8765",  # the app starts inside the sandbox: it may bind 127.0.0.1 there
    "grep -r token ~ | python -m pytest",
])
def test_anything_else_stays_in_the_sandbox(command):
    assert not local_tests.is_test_run(command, "/repo")


def test_the_wrapper_round_trips_and_is_the_one_excluded_form():
    command = "python -m pytest -q 2>&1 | tail -60"
    wrapped = local_tests_words.wrap(SHIM, command)
    assert wrapped.startswith(f"{SHIM} test-run ") and local_tests.unwrap(wrapped) == command
    settings = launch_sandbox.sandbox_settings(
        state_root=Path("/s"), base_url="https://octryx.example.test", shim=Path(SHIM))
    assert settings["excludedCommands"] == [f"{SHIM} test-run *"] and settings["allowUnsandboxedCommands"] is False
    assert local_tests.unwrap("/usr/bin/evil test-run cHl0ZXN0") is None


def test_the_wrapper_checks_again_and_runs_only_test_runs(tmp_path):
    entry = Path(__file__).resolve().parents[1] / "octryx_claude_entry.py"

    def run(command: str) -> subprocess.CompletedProcess:
        payload = local_tests_words.wrap("octryx-claude", command).split()[-1]
        return subprocess.run([sys.executable, str(entry), "test-run", payload], cwd=tmp_path, capture_output=True,
                              text=True, timeout=60, check=False)

    refused = run("cat /etc/hosts")
    assert refused.returncode == local_tests.REFUSED_EXIT and "test-run refused" in refused.stderr
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    ran = run(f"{sys.executable} -m pytest -q -p no:cacheprovider 2>&1 | tail -3")
    assert ran.returncode == 0 and "1 passed" in ran.stdout


def test_a_timeout_prefix_runs_the_tests_where_the_device_has_no_timeout(tmp_path):
    """macOS has no ``timeout``: the wrapper's shell supplies one, so the wrapped run still prints its output."""
    entry = Path(__file__).resolve().parents[1] / "octryx_claude_entry.py"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python = bin_dir / "python"  # PATH has python and nothing else: no timeout, no gtimeout
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    payload = local_tests_words.wrap("octryx-claude", "timeout 550 python -m pytest -q -p no:cacheprovider").split()[-1]
    ran = subprocess.run([sys.executable, str(entry), "test-run", payload], cwd=tmp_path, capture_output=True,
                         text=True, timeout=60, check=False, env={"PATH": str(bin_dir)})
    assert ran.returncode == 0 and "1 passed" in ran.stdout, ran.stdout + ran.stderr


def test_a_run_phase_test_run_is_allowed_outside_the_sandbox_and_reported_unwrapped():
    output = hook_outputs.test_run_output(_hook_input("python -m pytest -q | tail -5"), PHASE, SHIM)
    specific = output["hookSpecificOutput"]
    assert specific["permissionDecision"] == "allow"  # no approval prompt on the device
    wrapped = specific["updatedInput"]["command"]
    assert local_tests.unwrap(wrapped) == "python -m pytest -q | tail -5"
    assert specific["updatedInput"]["description"] == "run the tests"
    post = {**_hook_input(wrapped), "hook_event_name": "PostToolUse"}
    assert hook_outputs.unwrapped(post)["tool_input"]["command"] == "python -m pytest -q | tail -5"
    # Outside a run phase, for another command or without the session's shim: nothing changes.
    assert hook_outputs.test_run_output(_hook_input("python -m pytest"), {"digest": "d"}, SHIM) is None
    assert hook_outputs.test_run_output(_hook_input("ls"), PHASE, SHIM) is None
    assert hook_outputs.test_run_output(_hook_input("python -m pytest"), PHASE, "") is None


def test_the_platform_decides_first_and_the_agent_cannot_type_the_wrapper(state, monkeypatch, capsys):
    monkeypatch.setenv("OCTRYX_BASE_URL", "https://octryx.example.test")
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv(launch.TEST_RUN_SHIM_ENV, SHIM)
    asked: list[str] = []

    def run(command: str, decision: str) -> dict:
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(_hook_input(command)).encode())))

        def handler(request: httpx.Request) -> httpx.Response:
            asked.append(json.loads(request.content)["tool_input"]["command"])
            return httpx.Response(200, json={"decision": decision, "state": decision, "workflow_run": PHASE})

        pre_tool_use_hook.run_pre_tool_use(state, httpx.Client(transport=httpx.MockTransport(handler)))
        return json.loads(capsys.readouterr().out or "{}")

    allowed = run("python -m pytest -q", "allow")
    assert asked == ["python -m pytest -q"]  # the platform saw the command as the agent wrote it
    assert allowed["hookSpecificOutput"]["updatedInput"]["command"].startswith(f"{SHIM} test-run ")
    assert run("python -m pytest -q", "deny")["hookSpecificOutput"]["permissionDecision"] == "deny"
    typed = run(local_tests_words.wrap(SHIM, "python -m pytest"), "allow")
    assert typed["hookSpecificOutput"]["permissionDecision"] == "deny" and len(asked) == 2
    # The launcher's own denial is spooled for the platform (it would leave no trace there otherwise).

    spooled = (state.session_dir(KEY) / local_audit_spool.SPOOL_FILE).read_text(encoding="utf-8").splitlines()
    assert json.loads(spooled[-1])["reason"] == "local_test_run_wrapper"


def test_a_test_run_may_report_its_exit_status_after_a_pipe():
    """``echo "exit=${PIPESTATUS[0]}"`` / ``echo $?`` after a pipe keep a test run a test run despite the ``$``."""
    assert local_tests.is_test_run('python -m pytest -v tests/system 2>&1 | tail -30; echo "exit=${PIPESTATUS[0]}"',
                                   "/repo")
    assert local_tests.is_test_run("python -m pytest -q | tail -5; echo $?", "/repo")
    assert not local_tests.is_test_run('python -m pytest; echo "${HOME}"', "/repo")
    assert not local_tests.is_test_run("python -m pytest; echo ${PIPESTATUS[0]} $(id)", "/repo")
    assert not local_tests.is_test_run("cd ${PIPESTATUS[0]} && python -m pytest", "/repo")
    assert not local_tests.is_test_run("X=$? python -m pytest", "/repo")
    assert not local_tests.is_test_run("python -m pytest | grep $?", "/repo")


@pytest.mark.parametrize(("command", "plain"), [
    (".venv/bin/python -m pytest -v tests/system > $TMPDIR/sys.log 2>&1; tail -50 $TMPDIR/sys.log",
     ".venv/bin/python -m pytest -v tests/system 2>&1"),
    ("python -m pytest -q 2>&1 | tee out.txt | tail -5", "python -m pytest -q 2>&1  | tail -5"),
    ("python -m pytest >> out.txt", "python -m pytest"),
])
def test_a_test_run_into_a_file_is_answered_with_the_form_that_runs_outside(command, plain):
    """A test run written to a file would stay in the sandbox: the session hears the form that runs outside."""
    assert local_tests_forms.plain_form(command, "/repo") == plain
    output = hook_outputs.test_run_output(_hook_input(command), PHASE, SHIM)
    specific = output["hookSpecificOutput"]
    assert specific["permissionDecision"] == "deny" and f"`{plain}`" in specific["permissionDecisionReason"]
    assert "updatedInput" not in specific


@pytest.mark.parametrize("command", ["ls > files.txt", "python -m kitchen.run > app.log 2>&1",
                                     "python -m pytest -q 2>&1 | tail -5", "python -m pytest | tee /etc/x; rm -rf x"])
def test_other_redirections_are_left_alone(command):
    assert local_tests_forms.plain_form(command, "/repo") is None
