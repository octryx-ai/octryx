"""Git that talks to a remote never asks anyone: credentials come only from the platform's
connection. An askpass the developer's shell passes down (e.g. VS Code's) is never called; one the connection sets
explicitly still is. A local HTTP server answers 401, so git really wants credentials; nothing leaves this machine."""

import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.services.execution_runtime.server_env import GIT_HARDENING, with_git_hardening
from app.services.repository_bootstrap.local import run_git
from app.services.workflow_runs import safe_git


class _AuthRequired(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server's naming
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="test"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args):
        pass


@pytest.fixture
def remote():
    server = HTTPServer(("127.0.0.1", 0), _AuthRequired)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/repo.git"
    server.shutdown()


@pytest.fixture
def askpass(tmp_path: Path):
    """An askpass that records every call and answers, so a call would also let git go on."""
    log = tmp_path / "askpass.log"
    script = tmp_path / "askpass.sh"
    script.write_text(f'#!/bin/sh\necho "$1" >> "{log}"\necho x\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, log


@pytest.fixture
def inherited_askpass(monkeypatch, askpass):
    script, log = askpass
    monkeypatch.setenv("GIT_ASKPASS", str(script))
    monkeypatch.setenv("SSH_ASKPASS", str(script))
    monkeypatch.setenv("VSCODE_GIT_ASKPASS_MAIN", str(script))
    return log


@pytest.mark.asyncio
async def test_safe_git_never_calls_an_inherited_askpass(remote, inherited_askpass, tmp_path):
    code, _out, _err = await safe_git.git(tmp_path, "ls-remote", remote)
    assert code != 0
    assert not inherited_askpass.exists(), inherited_askpass.read_text()


@pytest.mark.asyncio
async def test_the_repository_bootstrap_never_calls_an_inherited_askpass(remote, inherited_askpass, tmp_path):
    code, _out, _err = await run_git(["git", "ls-remote", remote], cwd=tmp_path, timeout_sec=30)
    assert code != 0
    assert not inherited_askpass.exists(), inherited_askpass.read_text()


@pytest.mark.asyncio
async def test_an_askpass_the_connection_sets_is_still_used(remote, askpass, tmp_path):
    script, log = askpass
    env = {**os.environ, "GIT_ASKPASS": str(script)}  # explicit: differs from this process's environment
    await safe_git.git(tmp_path, "ls-remote", remote, env=env)
    assert "Username" in log.read_text()


def test_ssh_runs_in_batch_mode_and_inherited_prompt_variables_are_dropped():
    process = {"GIT_ASKPASS": "/inherited", "SSH_ASKPASS": "/inherited", "GIT_SSH_COMMAND": "ssh -i k"}
    env = with_git_hardening({**process, "VSCODE_GIT_IPC_HANDLE": "/tmp/x", "PATH": "/bin"}, process_env=process)
    assert not {"GIT_ASKPASS", "SSH_ASKPASS", "GIT_SSH_COMMAND", "VSCODE_GIT_IPC_HANDLE"} & set(env)
    assert env["GIT_TERMINAL_PROMPT"] == "0" and env["PATH"] == "/bin"
    assert ("core.sshCommand", "ssh -o BatchMode=yes") in GIT_HARDENING
