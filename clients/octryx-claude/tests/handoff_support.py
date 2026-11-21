"""Shared git repositories, fake platform and hand-over helpers for the client handoff tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from octryx_claude.handoff import run_handoff
from octryx_claude.platform import SessionContext

from .conftest import BASE_URL

KEY = ("0b6c" + "4a52-3b1e-4c1b-9f55-1d1c1b1a1f10")


NOW = datetime(2026, 10, 6, 10, 30)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True, text=True).stdout.strip()


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """A bare 'remote', the user's clone with uncommitted work, and a second clone for the receiver."""
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = t\n\temail = t@example.test\n[commit]\n\tgpgsign = false\n"
                      "[core]\n\tautocrlf = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    user = tmp_path / "anna"
    user.mkdir()
    git(user, "init", "-q", "-b", "main")
    (user / "src").mkdir()
    (user / "src" / "app.py").write_text("print('v1')\n")
    (user / "README.md").write_text("# demo\n")
    (user / ".gitignore").write_text("build/\n")
    (user / "settings.pem").write_text("committed key\n")
    git(user, "add", "-A")
    git(user, "commit", "-q", "-m", "base")
    git(user, "remote", "add", "origin", str(remote))
    git(user, "push", "-q", "origin", "main")
    # Uncommitted work: a modified tracked file, a staged change, an untracked file, ignored and secret files.
    (user / "src" / "app.py").write_text("print('v2 work in progress')\n")
    (user / "README.md").write_text("# demo\nstaged line\n")
    git(user, "add", "README.md")
    (user / "src" / "new_module.py").write_text("NEW = True\n")
    (user / "build").mkdir()
    (user / "build" / "out.bin").write_text("ignored\n")
    (user / ".env").write_text("TOKEN=abc\n")
    (user / "config").mkdir()
    (user / "config" / ".env.local").write_text("X=1\n")
    (user / ".aws").mkdir()
    (user / ".aws" / "credentials").write_text("[default]\n")
    (user / "id_rsa").write_text("private\n")
    (user / "settings.pem").write_text("changed key\n")
    receiver = tmp_path / "ben"
    subprocess.run(["git", "clone", "-q", str(remote), str(receiver)], check=True)
    return {"remote": remote, "user": user, "receiver": receiver}


def snapshot(repo: Path) -> dict[str, object]:
    files = {}
    for path in sorted(repo.rglob("*")):
        if ".git" in path.relative_to(repo).parts or not path.is_file():
            continue
        files[str(path.relative_to(repo))] = path.read_bytes()
    return {
        "files": files,
        "index": (repo / ".git" / "index").read_bytes(),
        "head_ref": git(repo, "symbolic-ref", "HEAD"),
        "head": git(repo, "rev-parse", "HEAD"),
        "status": git(repo, "status", "--porcelain=v1", "--untracked-files=all"),
    }


# --- the fake platform --------------------------------------------------------------------------------------------


class Platform:
    def __init__(self, *, push="branch", repositories=None, items=None, upload_status=200, takeover=None):
        self.requests: list[httpx.Request] = []
        self.push, self.repositories = push, repositories or []
        self.items = items or [{"id": "item-6", "key": "BRD-6", "title": "Login"}]
        self.upload_status, self.takeover = upload_status, takeover
        self.uploads: dict[str, bytes] = {}
        self.commits: list[dict] = []
        self.polls = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/v1/agent-gateway/handoff")
        if path == "/prepare":
            return httpx.Response(200, json={"state": "ok", "items": self.items, "repositories": self.repositories,
                                             "policy": {"push": self.push, "mode": "confirm", "auto_trigger_pct": 99},
                                             "user": {"name": "Anna", "email": "anna@example.test"}})
        if path == "/attachments" and request.method == "POST":
            if self.upload_status != 200:
                return httpx.Response(self.upload_status, json={"detail": {"code": "secret_detected"}})
            bundle_id = f"bundle-{len(self.uploads) + 1}"
            self.uploads[bundle_id] = request.content
            return httpx.Response(200, json={"state": "stored", "bundle_id": bundle_id})
        if path.startswith("/attachments/"):
            data = self.uploads[path.rsplit("/", 1)[1]]
            digest = hashlib.sha256(data).hexdigest()
            return httpx.Response(200, content=data, headers={"x-octryx-sha256": digest})
        if path == "/commit":
            body = json.loads(request.content)
            self.commits.append(body)
            return httpx.Response(200, json={"state": "handed_over", "work_item": {"key": "BRD-6"},
                                             "handoff": {"id": "h", "version": len(self.commits) + 1},
                                             "takeover": self.takeover})
        if path.startswith("/takeovers/"):
            self.polls += 1
            return httpx.Response(200, json={"state": "ok", "takeover": {
                "id": "t1", "status": "confirmed", "to": {"user": {"display_name": "Ben"}}}})
        if path.startswith("/resume"):
            commit = self.commits[-1]
            return httpx.Response(200, json={"state": "ok", "work_item": {"key": "BRD-6", "title": "Login"},
                                             "handoff": {"version": 2, "sections": {"repo": commit["repo"],
                                                                                    "state": "half done"}}})
        return httpx.Response(404, json={})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


def context(work_item: str = "") -> SessionContext:
    return SessionContext(BASE_URL, KEY, "ws-1", work_item)


def hand_over(state, platform, cwd, **kwargs):
    with platform.client() as http:
        return run_handoff(state, context(), http, cwd=cwd, now=lambda: NOW, sleep=lambda _s: None, **kwargs)


# --- push policy and bundle fallback --------------------------------------------------------------------------------


def remote_branches(remote: Path) -> list[str]:
    return sorted(git(remote, "for-each-ref", "--format=%(refname)").splitlines())
