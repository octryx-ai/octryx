"""Code intelligence against a fake control plane: bind, manifest, wanted uploads, summary."""

from __future__ import annotations

import base64
import io
import json

import httpx

from octryx_claude import snapshot
from octryx_claude.platform import SessionContext
from octryx_claude.repository import TreeFile

from .conftest import BASE_URL
from .gitrepo import git, make_repo, requires_git

KEY = ("0b6c" + "4a52-3b1e-4c1b-9f55-1d1c1b1a1f10")
CONTEXT = SessionContext(BASE_URL, KEY, "ws-1")
PREFIX = "/api/v1/agent-gateway/sessions/repository"


class FakePlatform:
    def __init__(self, *, snapshot_state: str = "allowed", wanted: tuple[str, ...] = ("src/app.py",)) -> None:
        self.snapshot_state = snapshot_state
        self.wanted = list(wanted)
        self.requests: list[httpx.Request] = []

    def body(self, path: str) -> dict:
        return next(json.loads(r.content) for r in self.requests if r.url.path == path)

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == PREFIX:
            head = json.loads(request.content)["head_commit"]
            return httpx.Response(200, json={
                "state": "bound",
                "binding": {"connector_key": "github", "repository": "o/r", "workspace_id": "ws-1",
                            "head_commit": head, "head_dirty": False, "links": "host"},
                "snapshot": {"state": self.snapshot_state,
                             "reason": None if self.snapshot_state == "allowed" else "local_snapshots_disabled"},
            })
        if path == f"{PREFIX}/manifest":
            return httpx.Response(200, json={"state": "ok", "wanted": self.wanted, "unchanged": 1, "skipped": []})
        if path == f"{PREFIX}/files":
            files = json.loads(request.content)["files"]
            return httpx.Response(200, json={"state": "ok", "results": [
                {"path": f["path"], "outcome": "ingested", "reason": None} for f in files]})
        if path == f"{PREFIX}/complete":
            return httpx.Response(200, json={"state": "indexed", "files_indexed": 2, "files_new": 1,
                                             "files_removed": 0, "missing": 0})
        return httpx.Response(404)


def _run(state, repo, platform) -> tuple[snapshot.CodeIntelligenceOutcome, str]:
    out = io.StringIO()
    outcome = snapshot.run_code_intelligence(
        state, CONTEXT, repo, http=httpx.Client(transport=httpx.MockTransport(platform)), out=out
    )
    return outcome, out.getvalue()


def test_batches_respect_the_file_count_byte_budget_and_single_file_cap():
    mib = 1024 * 1024
    small = [TreeFile(f"f{i}", "a" * 40, 10) for i in range(120)]
    assert [len(batch) for batch in snapshot.plan_batches(small)] == [50, 50, 20]
    sized = [TreeFile(f"b{i}", "a" * 40, mib) for i in range(7)] + [TreeFile("huge", "a" * 40, mib + 1)]
    batches = snapshot.plan_batches(sized)
    assert [len(batch) for batch in batches] == [3, 3, 1]
    assert all(sum(item.size for item in batch) <= 3 * mib for batch in batches)
    assert "huge" not in {item.path for batch in batches for item in batch}


@requires_git
def test_binds_and_uploads_only_wanted_files(state, tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    head = git(repo, "rev-parse", "HEAD")
    platform = FakePlatform()

    outcome, line = _run(state, repo, platform)

    assert platform.paths() == [PREFIX, f"{PREFIX}/manifest", f"{PREFIX}/files", f"{PREFIX}/complete"]
    assert platform.requests[0].headers["x-octryx-session"] == KEY
    assert platform.requests[0].headers["authorization"] == "Bearer gw-cached"
    assert platform.body(PREFIX) == {"remote_url": "https://github.com/o/r.git", "head_commit": head,
                                     "head_dirty": False, "head_pushed": False, "branch": "main",
                                     "root": git(repo, "rev-parse", "--show-toplevel")}
    manifest = platform.body(f"{PREFIX}/manifest")
    assert {f["path"] for f in manifest["files"]} == {"README.md", "src/app.py"} and manifest["truncated"] is False
    [uploaded] = platform.body(f"{PREFIX}/files")["files"]
    assert uploaded["path"] == "src/app.py"
    assert base64.b64decode(uploaded["content_base64"]) == b"print('hello')\n"
    for request in platform.requests:
        assert b"user:tok" not in request.content and b"tok@" not in request.content
    assert outcome.state == "indexed"
    assert line == (f"octryx-claude: code intelligence: o/r @ {head[:7]} bound to Workspace ws-1, "
                    "2 files indexed (1 new)\n")

    (repo / "README.md").write_text("# edited\n")
    _, dirty_line = _run(state, repo, FakePlatform(wanted=()))
    assert dirty_line.endswith("(1 new); working tree has uncommitted changes, HEAD was indexed\n")


@requires_git
def test_denied_snapshot_binds_without_uploading(state, tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    head = git(repo, "rev-parse", "HEAD")
    platform = FakePlatform(snapshot_state="denied")

    outcome, line = _run(state, repo, platform)

    assert platform.paths() == [PREFIX]
    assert outcome.state == "snapshot_denied"
    assert line == (f"octryx-claude: code intelligence: o/r @ {head[:7]} bound to Workspace ws-1; "
                    "local snapshots are not allowed in this Workspace (local_snapshots_disabled)\n")


@requires_git
def test_unreachable_platform_and_refusal_turn_code_intelligence_off(state, tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"x-octryx-gateway-state": "denied",
                                            "x-octryx-gateway-reason": "repository_not_allowed"})

    assert _run(state, repo, unreachable)[1] == "octryx-claude: code intelligence: off (platform_unreachable)\n"
    assert _run(state, repo, refused)[1] == "octryx-claude: code intelligence: off (repository_not_allowed)\n"
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    platform = FakePlatform()
    outcome, line = _run(state, plain, platform)
    assert outcome.state == "off" and platform.requests == []
    assert line == "octryx-claude: code intelligence: off (not_a_git_repository)\n"
