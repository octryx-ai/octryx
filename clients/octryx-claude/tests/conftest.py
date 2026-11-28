from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

from octryx_claude.oauth import SCOPES
from octryx_claude.state import LocalState
from octryx_claude.tokens import GATEWAY_AUDIENCE

BASE_URL = "https://octryx.example.test"


def _logged_in(root: Path, monkeypatch) -> LocalState:
    monkeypatch.setenv("OCTRYX_CLAUDE_HOME", str(root))
    local = LocalState(root).ensure()
    local.write_credentials(
        {
            "base_url": BASE_URL,
            "client_id": "oec_test",
            "redirect_uri": "http://127.0.0.1:50000/callback",
            "refresh_token": "refresh-1",
            # A login with the current scopes (seat finding SL-1: the launcher records what was granted).
            "scopes": sorted(SCOPES.split()),
            "tokens": {GATEWAY_AUDIENCE: {"access_token": "gw-cached", "expires_at": time.time() + 3600}},
        }
    )
    return local


@pytest.fixture
def state(tmp_path, monkeypatch) -> LocalState:
    return _logged_in(tmp_path / "octryx", monkeypatch)


FAKE_CLAUDE = """\
import json, os, signal, sys
socket_path = os.path.join(os.environ["OCTRYX_CLAUDE_HOME"], "sessions", os.environ["OCTRYX_SESSION_KEY"], "hook.sock")
with open(os.environ["FAKE_CLAUDE_OUT"], "w") as handle:
    json.dump({"argv": sys.argv, "env": dict(os.environ), "socket_present": os.path.exists(socket_path)}, handle)
if os.environ.get("FAKE_CLAUDE_SIGNAL"):
    os.kill(os.getpid(), int(os.environ["FAKE_CLAUDE_SIGNAL"]))
sys.exit(int(os.environ.get("FAKE_CLAUDE_EXIT", "0")))
"""


@pytest.fixture
def fake_claude(tmp_path, monkeypatch) -> tuple[Path, Path]:
    script = tmp_path / "fake-claude"
    script.write_text(f"#!{sys.executable}\n{FAKE_CLAUDE}")
    script.chmod(0o755)
    record = tmp_path / "fake-claude.json"
    monkeypatch.setenv("FAKE_CLAUDE_OUT", str(record))
    return script, record


@pytest.fixture
def launch_env(short_state, fake_claude, monkeypatch) -> dict:
    from octryx_claude import cli_account, cli_launch, cli_session, launch, skills, usage, workspaces
    from octryx_claude.platform import PlatformResult

    short_state.write_config({"base_url": BASE_URL, "workspace_id": "ws-1"})
    monkeypatch.setattr(launch, "resolve_claude", lambda: str(fake_claude[0]))
    calls: dict = {"steps": [], "bodies": {}, "record": fake_claude[1], "state": short_state,
                   "hook_key": PlatformResult("ok", body={"state": "registered"}, status_code=200,
                                              state="registered"),
                   "register": PlatformResult("ok", body={"state": "registered", "profile": "governed"},
                                              status_code=200, state="registered"),
                   "policy": PlatformResult("ok", body={"state": "allowed"}, status_code=200, state="allowed")}

    def fake_control_plane(state_arg, context, method, path, *, http, timeout, body=None):
        if path.startswith("/daily-budget?"):  # a status read, not a session step
            calls.setdefault("usage_reads", []).append(path)
            return calls.get("usage") or PlatformResult("refused", status_code=404)
        calls["steps"].append(path)
        calls["bodies"][path] = body
        if path in calls.get("responses", {}):
            return calls["responses"][path]
        if path == "/sessions/hook-key":
            return calls["hook_key"]
        if path == "/sessions/register":
            return calls["register"]
        if path == "/skills/manifest":  # no catalog skills unless a test sets a manifest
            return PlatformResult("refused", status_code=404, reason="not_configured")
        return calls["policy"]

    def fake_code_intelligence(state_arg, context, cwd, *, http, out):
        calls["steps"].append("code_intelligence")
        calls["code_intelligence"] = (context, cwd)
        raise RuntimeError("boom")  # a failure must not block the launch

    for module in (cli_launch, cli_session, cli_account, usage, skills):
        monkeypatch.setattr(module, "call_control_plane", fake_control_plane)
    # The Workspace list cannot be read unless a test sets ``calls["workspaces"]`` (no network).
    monkeypatch.setattr(workspaces, "fetch_workspaces", lambda *_a, **_k: calls.get("workspaces"))
    monkeypatch.setattr(cli_session, "run_code_intelligence", fake_code_intelligence)
    return calls


@pytest.fixture
def short_state(monkeypatch):
    # macOS limits a Unix socket path to 104 bytes.
    base = tempfile.gettempdir()
    root = Path(tempfile.mkdtemp(prefix="ocx", dir=base if len(base) <= 40 else "/tmp"))
    try:
        yield _logged_in(root, monkeypatch)
    finally:
        shutil.rmtree(root, ignore_errors=True)
