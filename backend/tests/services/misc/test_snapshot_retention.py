from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import BackgroundWorkerRunState, Session
from app.services.session.workspace import SESSION_WORKSPACE_BASE_DIR_ENV, SessionWorkspaceCleanupWorker
from app.services.snapshot import SnapshotService, service

pytestmark = pytest.mark.asyncio

DAY = 24 * 3600


@pytest.fixture
def snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(service, "_DATA_DIR", tmp_path)
    monkeypatch.setenv(SESSION_WORKSPACE_BASE_DIR_ENV, str(tmp_path / "workspaces"))
    return tmp_path / "snapshots"


def _snapshot(snapshots: Path, session_id: str, *, days_ago: float, index_days_ago: float | None = None) -> Path:
    git_dir = snapshots / session_id
    (git_dir / "objects").mkdir(parents=True)
    index = git_dir / "index"
    index.write_bytes(b"DIRC")
    index_stamp = time.time() - (days_ago if index_days_ago is None else index_days_ago) * DAY
    os.utime(index, (index_stamp, index_stamp))
    stamp = time.time() - days_ago * DAY
    os.utime(git_dir, (stamp, stamp))
    return git_dir


async def _never_in_use(_session_id: str) -> bool:
    return False


def _remaining(snapshots: Path) -> set[str]:
    return {entry.name for entry in snapshots.iterdir()}


async def test_snapshots_older_than_the_age_limit_are_pruned(snapshots):
    _snapshot(snapshots, "old", days_ago=8)
    _snapshot(snapshots, "fresh", days_ago=1)

    pruned = await SnapshotService.prune_old_snapshots(in_use=_never_in_use)

    assert pruned == ["old"]
    assert _remaining(snapshots) == {"fresh"}


async def test_only_the_newest_snapshots_up_to_the_count_limit_are_kept(snapshots):
    for age in range(5):
        _snapshot(snapshots, f"session-{age}", days_ago=age / 10)

    pruned = await SnapshotService.prune_old_snapshots(in_use=_never_in_use, max_count=3)

    assert sorted(pruned) == ["session-3", "session-4"]
    assert _remaining(snapshots) == {"session-0", "session-1", "session-2"}


async def test_a_recent_snapshot_in_an_old_directory_counts_as_recent(snapshots):
    _snapshot(snapshots, "reused", days_ago=30, index_days_ago=0.1)

    assert await SnapshotService.prune_old_snapshots(in_use=_never_in_use) == []
    assert _remaining(snapshots) == {"reused"}


async def test_a_snapshot_of_a_session_in_use_is_kept_past_both_limits(snapshots):
    _snapshot(snapshots, "busy", days_ago=30)
    _snapshot(snapshots, "idle", days_ago=30)

    async def in_use(session_id: str) -> bool:
        return session_id == "busy"

    pruned = await SnapshotService.prune_old_snapshots(in_use=in_use, max_count=0)

    assert pruned == ["idle"]
    assert _remaining(snapshots) == {"busy"}


async def test_without_snapshots_nothing_is_pruned(snapshots):
    assert await SnapshotService.prune_old_snapshots(in_use=_never_in_use) == []


async def test_the_cleanup_worker_prunes_old_snapshots_but_keeps_a_running_sessions(db, snapshots, auth_user):
    running, finished = str(uuid.uuid4()), str(uuid.uuid4())
    db.add_all([Session(id=running, user_id=auth_user.id, status="running", metadata_={}),
                Session(id=finished, user_id=auth_user.id, status="completed", metadata_={})])
    await db.commit()
    for session_id in (running, finished, "no-session-row"):
        _snapshot(snapshots, session_id, days_ago=30)
    worker = SessionWorkspaceCleanupWorker(async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False))

    result = await worker.run_once()

    assert sorted(result["snapshotsPruned"]) == sorted([finished, "no-session-row"])
    assert _remaining(snapshots) == {running}
    state = await db.get(BackgroundWorkerRunState, "session_workspace_cleanup_worker")
    assert state is not None and state.status == "success"
