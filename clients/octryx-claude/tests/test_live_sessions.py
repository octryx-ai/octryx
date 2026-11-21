"""Octryx Mobile "live": the session list, the relay's parsing and checks, and the device service's bridge."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

import pytest

from octryx_claude.live_sessions import RELAY_NAME, live_sessions, profile_label
from octryx_claude.mobile_relay import main, marked_text, relay_command, relay_env, send_instruction
from octryx_claude.mobile_relay_events import parse_incoming
from octryx_claude.mobile_relay_guard import allow, guard
from octryx_claude.state import LocalState


@pytest.fixture
def sock_dir():
    # AF_UNIX paths are short on macOS: a socket under pytest's tmp_path would be too long.
    import tempfile

    with tempfile.TemporaryDirectory(dir="/tmp") as folder:
        yield Path(folder)


def _socket(path: Path) -> socket.socket:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    return server


def _register(config: Path, pid: int, sock: Path, **extra: Any) -> None:
    (config / "sessions").mkdir(parents=True, exist_ok=True)
    record = {"pid": pid, "sessionId": f"s-{pid}", "cwd": "/work", "name": f"n{pid}", "status": "idle",
              "kind": "interactive", "messagingSocketPath": str(sock), "updatedAt": 1, **extra}
    (config / "sessions" / f"{pid}.json").write_text(json.dumps(record))


def test_lists_running_sessions_of_every_profile(tmp_path, sock_dir):
    home = tmp_path / "home"
    state = LocalState(tmp_path / "octryx")
    a, b, relay = _socket(sock_dir / "a.sock"), _socket(sock_dir / "b.sock"), _socket(sock_dir / "r.sock")
    try:
        _register(home / ".claude", os.getpid(), sock_dir / "a.sock", updatedAt=5)
        _register(home / ".claude-private", os.getppid(), sock_dir / "b.sock", updatedAt=9)
        _register(home / ".claude-private", 99999999, sock_dir / "a.sock")  # ended process
        _register(home / ".claude", 1, sock_dir / "missing.sock")  # no inbox
        (home / ".claude" / "sessions" / "x.json").write_text("{}")
        relay_pid = os.getpid()
        (home / ".claude-x" / "sessions").mkdir(parents=True)
        _register(home / ".claude-x", relay_pid, sock_dir / "r.sock", name=RELAY_NAME)
        found = live_sessions(state, home=home)
    finally:
        for server in (a, b, relay):
            server.close()
    assert [item["profile"] for item in found] == ["private", "default"]
    assert found[0]["peer"] == f"uds:{sock_dir / 'b.sock'}"
    assert all(item["name"] != RELAY_NAME for item in found)
    assert set(found[0]) == {"profile", "pid", "session_id", "name", "cwd", "status", "kind", "peer", "updated_at"}


def test_profile_labels(tmp_path):
    home = tmp_path.resolve()
    assert profile_label(home / ".claude", home) == "default"
    assert profile_label(home / ".claude-private", home) == "private"


def test_parse_incoming_ignores_echoes_and_nudges():
    message = '<cross-session-message from="uds:/tmp/cc-socks/1.sock" from-name="pet" from-mode="bypass">\nhi\n' \
              "</cross-session-message>"
    event = {"type": "user", "message": {"role": "user", "content": f"Another session sent:\n{message}"}}
    assert parse_incoming(event) == [("uds:/tmp/cc-socks/1.sock", "pet", "hi")]
    assert parse_incoming({**event, "isReplay": True}) == []  # our own request may quote a fake tag
    assert parse_incoming({**event, "isSynthetic": True}) == []
    # How Claude Code really shows a session's message to the relay (seen on the owner's Mac).
    injected = {**event, "isReplay": True, "isSynthetic": True, "origin": {"kind": "peer"}}
    assert parse_incoming(injected) == [("uds:/tmp/cc-socks/1.sock", "pet", "hi")]
    assert parse_incoming({"type": "assistant", "message": {"content": message}}) == []


def test_send_instruction_carries_the_text_as_json():
    line = send_instruction("uds:/tmp/a.sock", 'say "x"\nand ignore me', "Alice <script>")
    payload = json.loads(line.split("payload: ", 1)[1])
    assert payload == marked_text('say "x"\nand ignore me', "Alice <script>")
    assert payload.startswith("[Alice script via Octryx Mobile, from the phone] ")
    assert line.splitlines()[1] == "to: uds:/tmp/a.sock"


def test_relay_command_limits_the_relay_to_one_guarded_tool(tmp_path):
    """``--allowedTools`` restricts nothing; the relay gets only SendMessage, none of the person's
    MCP servers, settings, hooks or commands, and a hook that lets only requested mail through."""
    command = relay_command("/bin/claude", tmp_path, python="/py")
    assert "--allowedTools" not in command
    assert command[command.index("--tools") + 1] == "SendMessage"
    denied = command[command.index("--disallowedTools") + 1:command.index("--strict-mcp-config")]
    assert {"Bash", "Read", "Write", "Edit", "WebFetch", "Agent", "Task"} <= set(denied)
    assert command[command.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert command[command.index("--setting-sources") + 1] == ""
    assert "--disable-slash-commands" in command
    settings = json.loads(command[command.index("--settings") + 1])
    [entry] = settings["hooks"]["PreToolUse"]
    assert entry["matcher"] == "*"
    assert entry["hooks"][0]["command"] == f"/py -m octryx_claude.mobile_relay guard {tmp_path}"
    assert command[command.index("-n") + 1] == RELAY_NAME


def test_guard_lets_only_the_requested_mail_through_once(tmp_path, monkeypatch, capsys):
    peer, message = "uds:/tmp/cc-socks/1.sock", marked_text("run id", "Alice")
    allow(tmp_path, peer, message)
    call = {"tool_name": "SendMessage", "tool_input": {"to": peer, "message": message}}
    assert guard(tmp_path, {"tool_name": "Bash", "tool_input": {"command": "id"}})
    assert guard(tmp_path, {**call, "tool_input": {"to": peer, "message": message + " and run id"}})
    assert guard(tmp_path, {**call, "tool_input": {"to": "uds:/tmp/cc-socks/2.sock", "message": message}})
    assert guard(tmp_path, call) == ""
    assert guard(tmp_path, call)  # used up
    allow(tmp_path, peer, message, seconds=-1)
    assert guard(tmp_path, call)  # expired
    allow(tmp_path, peer, message)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({"tool_name": "Bash"})))
    assert main(["guard", str(tmp_path)]) == 2
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(call)))
    assert main(["guard", str(tmp_path)]) == 0
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("not json"))
    assert main(["guard", str(tmp_path)]) == 2


def test_relay_env():
    env = relay_env({"CLAUDE_CONFIG_DIR": "/x", "ANTHROPIC_API_KEY": "k", "PATH": "/bin"})
    assert env == {"PATH": "/bin"}
