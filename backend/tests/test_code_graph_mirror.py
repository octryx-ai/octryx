"""The code graph's repository mirror, its refresh after a merge, the backfill and the agents' tools."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.models.runtime.code_intelligence import CodeRepository
from app.services.code_intelligence import graph_refresh, mirror


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c",
                           "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def remote(tmp_path) -> Path:
    """A bare repository ``acme/pay.git`` with one commit on main."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "app.py").write_text("def total(items):\n    return sum(items)\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "first")
    bare = tmp_path / "remotes" / "acme" / "pay.git"
    bare.parent.mkdir(parents=True)
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    return bare


@pytest.fixture
def mirror_root(tmp_path, monkeypatch) -> Path:
    from app.config import get_settings

    root = tmp_path / "ssd" / "code-mirrors"
    monkeypatch.setattr(get_settings(), "code_mirror_root", str(root))
    return root


async def _repository(db, remote: Path, *, graph_backend: str = "disabled") -> CodeRepository:
    from tests.observability_support import workspace

    project = await workspace(db, "Payments")
    repo = CodeRepository(project_id=project.id, name="pay", repo_root="/central-repositories/x", provider="github",
                          remote_url=f"file://{remote}", default_branch="main", graph_backend=graph_backend)
    db.add(repo)
    await db.flush()
    return repo


@pytest.mark.asyncio
async def test_a_shallow_mirror_under_the_root_follows_the_default_branch(db, remote, mirror_root):
    repo = await _repository(db, remote)
    record = await mirror.ensure_mirror(db, repo)
    target = mirror_root / repo.project_id / repo.id
    assert record["path"] == str(target) and repo.repo_root == str(target) and record["bytes"] > 0
    assert (target / "app.py").is_file() and _git(target, "rev-parse", "--is-shallow-repository") == "true"
    first = record["head"]
    # A merge on the remote: the update fetches it, still shallow.
    work = remote.parent.parent.parent / "work"
    (work / "app.py").write_text("def total(items):\n    return round(sum(items), 2)\n")
    _git(work, "commit", "-qam", "second")
    _git(work, "push", "-q", str(remote), "main")
    again = await mirror.ensure_mirror(db, repo)
    assert again["head"] != first and "round" in (target / "app.py").read_text()
    assert mirror.mirror_status(repo)["head"] == again["head"]


@pytest.mark.asyncio
async def test_no_root_or_no_remote_keeps_no_mirror(db, remote, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "code_mirror_root", "")
    repo = await _repository(db, remote)
    with pytest.raises(mirror.MirrorError, match="mirror_disabled"):
        await mirror.ensure_mirror(db, repo)


@pytest.mark.asyncio
async def test_a_merge_finds_the_repository_by_its_remote_and_the_backfill_mirrors_and_indexes_it(
        db, remote, mirror_root, monkeypatch):
    repo = await _repository(db, remote, graph_backend="auto")
    assert [found.id for found in await graph_refresh.repositories_for(db, "acme/pay", repo.project_id)] == [repo.id]
    assert await graph_refresh.repositories_for(db, "acme/other", repo.project_id) == []
    assert graph_refresh._slug("https://bitbucket.example/scm/ACME/pay.git") == "acme/pay"
    indexed = []

    async def index(_db, *, repository_id, force, trigger):
        indexed.append((repository_id, force, trigger))
        return {"status": "ok"}

    monkeypatch.setattr("app.services.code_intelligence.indexing.run_code_index", index)
    (result,) = await graph_refresh.backfill(db, project_id=repo.project_id)
    assert result["mirror"]["head"] and indexed == [(repo.id, True, "backfill")]
    # After a merge only an enabled graph is indexed again; a disabled one is only mirrored.
    repo.graph_backend = "disabled"
    outcome = await graph_refresh.refresh(db, repo, trigger="pr_merged")
    assert outcome["index"] == "graph disabled for this repository" and len(indexed) == 1


@pytest.mark.asyncio
async def test_the_admin_status_shows_the_mirror(db, remote, mirror_root):
    from app.services.code_intelligence.graph_admin import get_code_graph_admin_status_for_repository

    repo = await _repository(db, remote)
    await mirror.ensure_mirror(db, repo)
    status = await get_code_graph_admin_status_for_repository(db, repo=repo)
    assert status["status"] == "not_indexed" and status["mirror"]["bytes"] > 0


@pytest.mark.asyncio
async def test_the_agents_tools_read_only_their_own_workspaces(db, remote, mirror_root):
    from fastapi import HTTPException

    from app.services.mcp_code_graph_tools import mcp_code_graph_summary
    from tests.observability_support import admin_user

    repo = await _repository(db, remote)
    user = await admin_user(db)
    listed = await mcp_code_graph_summary(db, user=user, arguments={})
    assert repo.id not in [item["id"] for item in listed["repositories"]]  # not a member of that Workspace
    with pytest.raises(HTTPException) as refused:
        await mcp_code_graph_summary(db, user=user, arguments={"repository": repo.id})
    assert refused.value.status_code == 404


@pytest.mark.asyncio
async def test_a_merged_pull_request_refreshes_the_code_graph_without_a_waiting_run(db, remote, monkeypatch):
    import asyncio

    from app.services.workflow_runs.watch import deliver_event
    from app.services.workflow_runs.watch_events import PR_MERGED, WatchEvent

    repo = await _repository(db, remote, graph_backend="auto")
    started = []

    async def isolated(ids, trigger):
        started.append((ids, trigger))

    monkeypatch.setattr(graph_refresh, "_refresh_isolated", isolated)
    moved = await deliver_event(db, WatchEvent(PR_MERGED, "github", "acme/pay", "7"), source="webhook",
                                project_id=repo.project_id)
    await asyncio.sleep(0)
    assert moved == [] and started == [([repo.id], "pr_merged")]


@pytest.mark.asyncio
async def test_a_repository_whose_connection_refuses_the_remote_never_stops_the_backfill(
        db, remote, mirror_root, monkeypatch):
    """A Bitbucket repository whose remote is not the connection's host must not raise ValueError in the
    credential helper and fail the whole backfill with 500: that repository reports credential_refused and the
    others are mirrored."""
    from app.services.code_intelligence import mirror

    good = await _repository(db, remote)
    refused = CodeRepository(project_id=good.project_id, name="legacy", repo_root="/central-repositories/y",
                             provider="bitbucket", remote_url="https://other-host.example/scm/acme/pay.git",
                             default_branch="main", graph_backend="disabled")
    db.add(refused)
    await db.flush()
    real = mirror._provider_auth_env

    async def auth(db_, repo):
        if repo.id == refused.id:
            raise ValueError("The Git remote is not this Bitbucket connection's host; no credential is sent to it.")
        return await real(db_, repo)

    async def index(_db, *, repository_id, force, trigger):
        return {"status": "ok"}

    monkeypatch.setattr(mirror, "_provider_auth_env", auth)
    monkeypatch.setattr("app.services.code_intelligence.indexing.run_code_index", index)
    results = {item["repository_id"]: item for item in await graph_refresh.backfill(db, project_id=good.project_id)}
    assert results[refused.id]["mirror_error"] == "credential_refused"
    assert results[good.id]["mirror"]["head"]
