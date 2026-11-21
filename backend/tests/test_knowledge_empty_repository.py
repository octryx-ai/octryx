"""An empty repository is no error.

Contract:

- ``GitCloneReader`` against real Git: a reachable repository that advertises no ref at all (no head, no tag, no
  default branch) is ``repository_empty``; a repository with refs but not the configured one, and a repository that
  does not exist, stay ``source_not_found`` (the empty check runs only after a "not found" fetch, with the same
  credential, and needs ``ls-remote`` to succeed);
- a Knowledge sync of a Bitbucket Data Center repository without any commit **completes** with 0 items, the reason
  ``repository_empty`` and ``report.repository.empty``; the Problems collector reports nothing for it;
- a repository that loses every branch completes the same way: its served files are retired, ``head_commit`` is
  cleared and the file index emptied.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

import app.services.knowledge.sources.sync.git_clone as git_clone
from app.models import KnowledgeCodeFile
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.atlassian_auth import resolve_credential
from app.services.atlassian_auth_modes import BITBUCKET
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.git_clone import (
    GitCloneReader,
    RepositoryEmptyError,
    advertises_no_ref,
    run_git,
)
from app.services.knowledge.sources.sync.service_run import run_connector
from app.services.problems import syncs
from app.services.problems.model import CollectContext
from app.time_utils import utc_now
from tests.knowledge_bitbucket_dc_repositories_support import BASE, FILES, _author, _connection, _save_body
from tests.knowledge_bitbucket_dc_support import world  # noqa: F401 - the ``world`` fixture
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user
from tests.policy_engine_support import bearer

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
CLONE_URL = f"{BASE}/scm/shop/aws-shop-deployment.git"


def _git(*args: str, cwd: str | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _empty_bare(tmp_path: Path) -> str:
    bare = tmp_path / "empty.git"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    return str(bare)


def _filled_bare(tmp_path: Path) -> tuple[str, str]:
    work, bare = tmp_path / "work", tmp_path / "filled.git"
    _git("init", "-q", "-b", "main", str(work))
    for path, data in FILES.items():
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).write_bytes(data)
    ident = ("-c", "user.name=t", "-c", "user.email=t@example.test")
    _git(*ident, "add", ".", cwd=str(work))
    _git(*ident, "commit", "-q", "-m", "init", cwd=str(work))
    _git("clone", "-q", "--bare", str(work), str(bare))
    return str(bare), _git("rev-parse", "HEAD", cwd=str(work))


def _local(bare: str):
    """A Git runner that serves ``CLONE_URL`` from the local bare repository ``bare`` (file protocol allowed)."""
    seen: list[list[str]] = []

    async def run(argv, env, timeout, max_stdout):
        seen.append(list(argv))
        local = [bare if item == CLONE_URL else item for item in argv if item != "protocol.allow=never"]
        local = [item for index, item in enumerate(local) if not (item == "-c" and local[index + 1:index + 2] == ["-c"])]
        return await run_git(local, env, timeout, max_stdout)

    return run, seen


async def _no_egress_check(url: str) -> None:
    return None


def _reader(run) -> GitCloneReader:
    credential = resolve_credential(BITBUCKET, {"bitbucket_url": BASE, "bitbucket_auth_mode": "bearer_pat",
                                                "bitbucket_token": "pat-1"})
    return GitCloneReader(credential=credential, egress_check=_no_egress_check, run=run)


def test_only_an_advertised_ref_makes_a_repository_non_empty() -> None:
    assert advertises_no_ref(b"")
    assert advertises_no_ref(b"0" * 40 + b"\tcapabilities^{}\n")
    assert not advertises_no_ref(b"a" * 40 + b"\trefs/heads/main\n")
    assert not advertises_no_ref(b"b" * 64 + b"\trefs/tags/v1\n")


async def test_a_reachable_repository_without_refs_is_empty_and_a_missing_one_is_not(tmp_path) -> None:
    run, seen = _local(_empty_bare(tmp_path))
    with pytest.raises(RepositoryEmptyError) as empty:
        await _reader(run).snapshot(CLONE_URL, ref="main", commit=None, max_bytes=1024 * 1024)
    assert empty.value.reason == "repository_empty"
    assert any("ls-remote" in argv for argv in seen) and all("pat-1" not in " ".join(argv) for argv in seen)

    filled, _sha = _filled_bare(tmp_path)
    run, _ = _local(filled)
    with pytest.raises(ConnectorError) as missing_ref:
        await _reader(run).snapshot(CLONE_URL, ref="develop", commit=None, max_bytes=1024 * 1024)
    assert missing_ref.value.reason == "source_not_found", "refs exist, just not the configured one"

    run, _ = _local(str(tmp_path / "does-not-exist.git"))
    with pytest.raises(ConnectorError) as missing_repo:
        await _reader(run).snapshot(CLONE_URL, ref="main", commit=None, max_bytes=1024 * 1024)
    assert missing_repo.value.reason == "source_not_found", "ls-remote fails: no repository"


async def _sync(client, db, world, monkeypatch, bare: str):  # noqa: F811 - ``world`` is the imported fixture
    workspace_id, user_id = await _author(db)
    connection_id = await _connection(db, [workspace_id])
    saved = await client.put(f"/api/v1/workspaces/{workspace_id}/knowledge/connectors/shop", headers=bearer(user_id),
                             json=_save_body(connection_id))
    assert saved.status_code == 200, saved.text
    run, _ = _local(bare)
    monkeypatch.setattr(git_clone, "run_git", run)
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime()

    row = (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == workspace_id))).scalar_one()

    async def once():
        return await run_connector(db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id,
                                   transport=httpx.MockTransport(world.handle))

    return workspace_id, row, once


async def test_a_sync_of_an_empty_repository_completes_without_a_problem(client, db, world, monkeypatch,  # noqa: F811
                                                                         tmp_path) -> None:
    workspace_id, row, once = await _sync(client, db, world, monkeypatch, _empty_bare(tmp_path))
    run = await once()
    assert (run.state, run.reason) == ("completed", "repository_empty")
    assert run.report["repository"] == {"ref": "main", "commit": None, "empty": True}
    counts = ("created", "updated", "unchanged", "retired", "skipped", "failed", "deferred")
    assert run.report["listed"] == 0 and not any(run.report[key] for key in counts)
    assert run.report["pass_completed"] is True
    await db.refresh(row)
    assert "head_commit" not in row.scope
    problems = await syncs.collect(db, CollectContext(now=utc_now(), workspace_ids=frozenset({workspace_id})))
    assert not [item for item in problems if item.object_id == row.id], "an empty repository is no problem"


async def test_a_repository_that_loses_every_branch_retires_what_it_served(client, db, world, monkeypatch,  # noqa: F811
                                                                           tmp_path) -> None:
    bare, sha = _filled_bare(tmp_path)
    _workspace_id, row, once = await _sync(client, db, world, monkeypatch, bare)
    first = await once()
    assert first.state == "completed" and first.reason is None and first.report["created"] == len(FILES)
    await db.refresh(row)
    assert row.scope["head_commit"] == sha
    _git("update-ref", "-d", "refs/heads/main", cwd=bare)  # every branch deleted: the repository is empty again

    second = await once()
    assert (second.state, second.reason) == ("completed", "repository_empty")
    assert second.report["retired"] == len(FILES)
    await db.refresh(row)
    assert "head_commit" not in row.scope
    files = (await db.execute(select(KnowledgeCodeFile).where(KnowledgeCodeFile.connector_id == row.id))).scalars()
    assert not list(files)
