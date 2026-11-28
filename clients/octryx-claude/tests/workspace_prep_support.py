from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.gitrepo import git
from tests.test_device_session_parity import BASE, CONTRACT, RUN, _answer  # noqa: F401

BRANCH = "feature/BRD-9-slugify"


def _origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    empty = tmp_path / "gitconfig"
    empty.write_text("[user]\n  name = t\n  email = t@example.test\n[commit]\n  gpgsign = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "textkit.py").write_text("def slugify(text):\n    return text\n")
    git(seed, "init", "-q", "-b", "main")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "init")
    git(seed, "checkout", "-q", "-b", BRANCH)
    (seed / "NOTES.md").write_text("branch work\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "on the branch")
    git(seed, "checkout", "-q", "main")
    bare = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
    folder = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(bare), str(folder))
    return folder


def _contract(environment: dict | None = None, state: str = "pending") -> dict:
    return {**CONTRACT, "preparation": {"state": state, "runtime": "device", "node_id": "prepare", "entry": 4,
                                        "branch": BRANCH, "environment": environment}}


def _platform(record: list, *, ready: bool, contract: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        record.append(request)
        path = request.url.path
        if path.endswith("/client-policy"):
            return httpx.Response(200, json={"state": "allowed"})
        if path.endswith("/sessions/register"):
            return _answer(200, {"state": "registered", "workflow_run_attach": {"state": "attached"},
                                 "workflow_run": contract})
        if path.endswith("/sessions/workspace-preparation"):
            state = "ready" if ready else "not_ready"
            paused = {} if ready else {"paused": {"reason": "environment_not_ready"}}
            after = {**contract, "digest": "d2", "preparation": {**contract["preparation"], "state": state}, **paused}
            return _answer(200, {"state": "ready" if ready else "not_ready", "workflow_run": after})
        if path.endswith("/sessions/hook-key"):
            return httpx.Response(200, json={"state": "registered"})
        if path.endswith("/sessions/repository"):
            return _answer(200, {"state": "bound", "binding": {"repository": "o/r", "workspace_id": "ws-1"},
                                 "snapshot": {"state": "denied", "reason": "local_snapshots_not_allowed"}})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


# --- the live device could not fetch origin (no git credentials there) ---------


def _no_origin_access(folder: Path, tmp_path: Path) -> str:
    git(folder, "remote", "set-url", "origin", str(tmp_path / "unreachable.git"))
    return git(folder, "rev-parse", "HEAD")
