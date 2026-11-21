"""The supervisor: claude runs as a child, exit codes pass through, the hook key stays in memory."""

from __future__ import annotations

import base64
import json
import os
import signal
import sys

from octryx_claude import cli, supervisor
from octryx_claude.platform import PlatformResult


def test_supervise_forwards_exit_codes_and_signal_deaths(fake_claude, monkeypatch):
    script, _ = fake_claude
    monkeypatch.setenv("OCTRYX_CLAUDE_HOME", "/nonexistent")
    monkeypatch.setenv("OCTRYX_SESSION_KEY", "k")
    before = signal.getsignal(signal.SIGINT)
    assert supervisor.supervise([str(script)], {**os.environ, "FAKE_CLAUDE_EXIT": "7"}) == 7
    assert supervisor.supervise([sys.executable, str(script)], dict(os.environ)) == 0
    killed = {**os.environ, "FAKE_CLAUDE_SIGNAL": str(int(signal.SIGTERM))}
    assert supervisor.supervise([str(script)], killed) == 128 + signal.SIGTERM
    assert signal.getsignal(signal.SIGINT) is before


def test_launch_registers_the_hook_key_first_and_never_leaks_it(launch_env, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "3")
    assert cli.main(["--", "-p", "hi"]) == 3

    assert launch_env["steps"] == ["/client-policy", "/sessions/register", "/skills/manifest", "/sessions/hook-key",
                                   "code_intelligence"]
    body = launch_env["bodies"]["/sessions/hook-key"]
    assert body["state_root"] == str(launch_env["state"].root)
    encoded = body["hook_key"]
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    assert len(raw) == 32 and "=" not in encoded
    record = json.loads(launch_env["record"].read_text())
    assert record["socket_present"] is True
    context, _ = launch_env["code_intelligence"]
    session_dir = launch_env["state"].session_dir(context.session_key)
    exposed = [json.dumps(record), (session_dir / "settings.json").read_text(), (session_dir / "mcp.json").read_text()]
    exposed.append(capsys.readouterr().err)  # the key is never logged either
    for form in (encoded, raw.hex(), base64.b64encode(raw).decode()):
        assert all(form not in text for text in exposed)
    assert not (session_dir / "hook.sock").exists()


def test_a_refused_hook_key_does_not_start_the_session(launch_env, capsys):
    launch_env["hook_key"] = PlatformResult("refused", status_code=409, reason="hook_key_already_registered")
    assert cli.main(["--", "-p", "hi"]) == 2

    assert "code_intelligence" not in launch_env["steps"] and not launch_env["record"].exists()
    assert "session not started: hook key hook_key_already_registered" in capsys.readouterr().err
