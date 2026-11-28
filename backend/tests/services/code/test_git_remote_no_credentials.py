"""A Git remote never keeps a credential: neither ``.git/config``, a clone URL nor any Git argv holds the token."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest

from app.services.git_http_auth import has_credentials, without_credentials
from app.services.repository_bootstrap import local as bootstrap_local
from app.services.repository_bootstrap import providers
from app.services.repository_bootstrap.service import ensure_workspace_repository

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")

TOKEN = "ghs_tok1SECRETvalue"
BASIC = "Basic " + base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()


class _GitServer(BaseHTTPRequestHandler):
    root = ""
    seen: list[str] = []

    def log_message(self, *_args) -> None:
        return

    def _serve(self) -> None:
        self.seen.append(self.path)
        if self.headers.get("Authorization") != BASIC:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="git"')
            self.end_headers()
            return
        parts = urlsplit(self.path)
        env = {"PATH": os.environ.get("PATH", ""), "GIT_PROJECT_ROOT": self.root, "GIT_HTTP_EXPORT_ALL": "1",
               "PATH_INFO": parts.path, "QUERY_STRING": parts.query, "REQUEST_METHOD": self.command,
               "CONTENT_TYPE": self.headers.get("Content-Type", ""), "REMOTE_ADDR": "127.0.0.1",
               "REMOTE_USER": "x-access-token", "GIT_PROTOCOL": self.headers.get("Git-Protocol", "")}
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if self.command == "POST" else b""
        if self.headers.get("Content-Encoding") == "gzip":
            import gzip

            body = gzip.decompress(body)
        out = subprocess.run(["git", "http-backend"], input=body, env=env, capture_output=True, check=False).stdout
        head, _, payload = out.partition(b"\r\n\r\n")
        status, headers = 200, []
        for line in head.decode().split("\r\n"):
            name, _, value = line.partition(": ")
            if name.lower() == "status":
                status = int(value.split()[0])
            elif name:
                headers.append((name, value))
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _serve  # noqa: N815 - the http.server handler names
    do_POST = _serve  # noqa: N815 - the http.server handler names


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "server"
    bare = root / "repo.git"
    _git("init", "--bare", "-b", "main", str(bare))
    _git("config", "http.receivepack", "true", cwd=bare)
    handler = type("Handler", (_GitServer,), {"root": str(root), "seen": []})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/repo.git", bare
    httpd.shutdown()


def test_credentials_are_found_and_removed_from_urls_only():
    assert has_credentials("https://x-access-token:t@github.com/a/b.git")
    assert has_credentials("http://user@127.0.0.1:8/r.git")
    assert not has_credentials("https://github.com/a/b.git") and not has_credentials("git@github.com:a/b.git")
    assert without_credentials("https://u:p%40x@host:8443/a/b.git?x=1") == "https://host:8443/a/b.git?x=1"
    assert without_credentials("git@github.com:a/b.git") == "git@github.com:a/b.git"


async def test_a_bootstrap_pushes_with_the_header_and_keeps_the_token_out_of_config_and_argv(
        server, tmp_path, monkeypatch):
    url, bare = server

    def github_api(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(201, json={"name": "repo", "full_name": "acme/repo", "clone_url": url,
                                         "html_url": "https://github.example/acme/repo"})

    monkeypatch.setattr(providers, "egress_transport", lambda _kind: httpx.MockTransport(github_api))
    argv: list[list[str]] = []
    real_run_git = bootstrap_local.run_git

    async def recording_run_git(command, **kwargs):
        argv.append(list(command))
        return await real_run_git(command, **kwargs)

    monkeypatch.setattr(bootstrap_local, "run_git", recording_run_git)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = await ensure_workspace_repository(
        workspace_root=workspace,
        project_config={"github_token": TOKEN, "repository_bootstrap": {
            "enabled": True, "provider": "github", "auto_bootstrap_on_session_start": False,
            "default_branch": "main", "default_repo_name": "repo"}},
    )

    assert result["status"] == "bootstrapped", result
    repo = Path(result["repo_path"])
    assert TOKEN not in (repo / ".git" / "config").read_text()
    assert _git("remote", "get-url", "origin", cwd=repo).strip() == url
    assert not any(TOKEN in part for command in argv for part in command)
    assert TOKEN not in str(result) and "git_env" not in str(result)
    assert _git("rev-parse", "main", cwd=bare).strip() == _git("rev-parse", "HEAD", cwd=repo).strip(), "pushed"


def test_clone_urls_never_carry_a_credential_from_the_configured_base_url():
    from app.tools.bitbucket_impl._bitbucket_internal_core import _bitbucket_clone_url
    from app.tools.connectors.github_source_control_common import github_clone_url_for_repository
    from app.tools.connectors.gitlab_source_control_common import gitlab_clone_url_for_project

    github = github_clone_url_for_repository("a", "b", configured_url="https://u:t@git.example.test/api/v3")
    gitlab = gitlab_clone_url_for_project("g/p", configured_url="https://u:t@gitlab.example.test")
    context = SimpleNamespace(project_config={"bitbucket_url": "https://u:t@bitbucket.example.test"})
    bitbucket = _bitbucket_clone_url(context, "OCX", "repo")

    assert github == "https://git.example.test/a/b.git"
    assert gitlab == "https://gitlab.example.test/g/p.git"
    assert bitbucket == "https://bitbucket.example.test/scm/OCX/repo.git"
