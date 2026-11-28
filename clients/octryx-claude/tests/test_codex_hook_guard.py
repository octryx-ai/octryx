from __future__ import annotations

import json
import stat
import subprocess
import sys

import pytest

from octryx_claude import codex_hook_guard, codex_hook_input

ALLOW = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}


def _deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


@pytest.mark.parametrize(("returncode", "stdout"), [
    (1, b""), (3, b""), (2, b""), (-9, b""), (0, b""), (0, b"hello"), (0, b"[1]"),
    (0, json.dumps({"hookSpecificOutput": {}}).encode()),
    (0, json.dumps({"hookSpecificOutput": {"permissionDecision": "ask"}}).encode()),
    (0, json.dumps({"hookSpecificOutput": {"permissionDecision": "allow", "hookEventName": "Stop"}}).encode()),
    (0, json.dumps({"hookSpecificOutput": {"permissionDecision": "allow", "updatedInput": "x"}}).encode())])
def test_anything_but_an_explicit_decision_blocks_with_a_fixed_reason(returncode, stdout):
    assert codex_hook_guard.answer(returncode, stdout) == (2, "", codex_hook_guard.REFUSED)


def test_a_deny_blocks_with_its_reason_or_the_fixed_one():
    assert codex_hook_guard.answer(0, json.dumps(_deny("rule x")).encode()) == (2, "", "rule x")
    assert codex_hook_guard.answer(0, json.dumps(_deny("")).encode()) == (2, "", codex_hook_guard.REFUSED)
    assert codex_hook_guard.answer(0, json.dumps(_deny(["x"])).encode()) == (2, "", codex_hook_guard.REFUSED)


def test_an_allow_runs_the_call_in_the_form_codex_accepts():
    assert codex_hook_guard.answer(0, json.dumps(ALLOW).encode()) == (0, "", "")
    with_context = {"hookSpecificOutput": {**ALLOW["hookSpecificOutput"], "additionalContext": "note"}}
    code, shown, _ = codex_hook_guard.answer(0, json.dumps(with_context).encode())
    assert code == 0 and json.loads(shown) == {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                                      "additionalContext": "note"}}
    rewritten = {"hookSpecificOutput": {**ALLOW["hookSpecificOutput"], "updatedInput": {"file_path": "/copy"}}}
    code, shown, _ = codex_hook_guard.answer(0, json.dumps(rewritten).encode())
    assert json.loads(shown)["hookSpecificOutput"] == {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                                       "updatedInput": {"file_path": "/copy"}}


def _hook(tmp_path, body):
    script = tmp_path / "hook"
    script.write_text(f"#!/bin/sh\ncat > /dev/null\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


# Long enough for a shell hook to start on a loaded machine; the hang test sets its own short deadline.
def _guarded(tmp_path, body, deadline="10"):
    return subprocess.run([sys.executable, "-I", codex_hook_guard.__file__, deadline, _hook(tmp_path, body)],
                          input=b"{}", capture_output=True, timeout=30, check=False)


def test_a_hook_that_hangs_is_blocked_before_codexs_own_deadline(tmp_path):
    done = _guarded(tmp_path, "sleep 30", deadline="0.5")
    assert done.returncode == 2 and b"in time" in done.stderr


def test_a_hook_that_cannot_run_is_blocked(tmp_path):
    done = subprocess.run([sys.executable, "-I", codex_hook_guard.__file__, "2", str(tmp_path / "missing")],
                          input=b"{}", capture_output=True, timeout=30, check=False)
    assert done.returncode == 2 and done.stderr.strip()


def test_the_guard_passes_an_explicit_allow_through(tmp_path):
    done = _guarded(tmp_path, f"echo '{json.dumps(ALLOW)}'")
    assert (done.returncode, done.stdout) == (0, b"")


def test_under_codex_the_hook_always_states_its_decision():
    assert codex_hook_input.decided(None) == ALLOW
    context = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "hint"}}
    assert codex_hook_input.decided(context)["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert codex_hook_input.decided(_deny("no")) == _deny("no")


def test_the_probe_checks_that_the_hook_can_run(tmp_path):
    hook = _hook(tmp_path, "exit 0")
    probe = [sys.executable, "-I", codex_hook_guard.__file__, "--probe"]
    assert subprocess.run([*probe, hook], check=False).returncode == 0
    assert subprocess.run([*probe, str(tmp_path / "missing")], check=False).returncode == 1


def test_the_guard_tells_the_hook_it_is_guarded(tmp_path):
    done = _guarded(tmp_path, f"[ \"$OCTRYX_CODEX_GUARDED\" = 1 ] && echo '{json.dumps(ALLOW)}'")
    assert done.returncode == 0
