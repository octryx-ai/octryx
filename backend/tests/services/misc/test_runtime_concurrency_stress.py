"""Concurrency and isolation stress tests for the parallel runtime hardening."""

import uuid

import pytest
from sqlalchemy import select

from app.models import ContextCheckpoint, Session
from app.services.double_text_guard_service import (
    DoubleTextGuardError,
    check_double_text_guard,
)
from app.services.resume_checkpoint_service import (
    attempt_resume,
    can_resume,
    create_resume_checkpoint,
    mark_resume_success,
)
from app.services.session.run_timeout import timeout_stalled_sessions
from app.time_utils import utc_now


async def _create_session(db, *, project_id: str | None = None, run_status: str = "completed") -> Session:
    session = Session(
        id=str(uuid.uuid4()),
        user_id="u1",
        project_id=project_id or str(uuid.uuid4()),
        status="active",
        run_status=run_status,
        recovery_policy="auto_retry",
        metadata_={},
    )
    db.add(session)
    await db.flush()
    return session


@pytest.mark.asyncio
async def test_parallel_session_creation_isolation(db):
    project_id = str(uuid.uuid4())

    sessions = []
    for _ in range(20):
        s = await _create_session(db, project_id=project_id)
        sessions.append(s)
    await db.commit()

    ids = [s.id for s in sessions]
    assert len(ids) == len(set(ids)), "Duplicate session IDs detected"

    result = await db.execute(select(Session).where(Session.project_id == project_id))
    rows = list(result.scalars().all())
    assert len(rows) == 20


@pytest.mark.asyncio
async def test_checkpoint_resume_prevents_duplicate(db):
    session = await _create_session(db, run_status="in_progress")
    checkpoint = ContextCheckpoint(
        id=str(uuid.uuid4()),
        session_id=session.id,
        checkpoint_name="pre-tool-call",
        context_snapshot_json={"step": 3},
        status="active",
    )
    db.add(checkpoint)
    await db.flush()

    rc = await create_resume_checkpoint(db, session_id=session.id, checkpoint_id=checkpoint.id)
    await db.commit()

    rc = await attempt_resume(db, session, checkpoint, resume_checkpoint=rc)
    assert rc.status == "in_progress"
    assert rc.resume_attempt_count == 1

    await mark_resume_success(db, rc)
    assert rc.status == "resumed"

    assert not can_resume(rc)


@pytest.mark.asyncio
async def test_double_text_guard_blocks_concurrent_input(db):
    session = await _create_session(db, run_status="in_progress")
    session.run_status = "in_progress"
    await db.flush()

    with pytest.raises(DoubleTextGuardError):
        await check_double_text_guard(db, session)


@pytest.mark.asyncio
async def test_double_text_guard_allows_after_completion(db):
    session = await _create_session(db, run_status="completed")
    await check_double_text_guard(db, session)


@pytest.mark.asyncio
async def test_timeout_stalled_sessions(db):
    from datetime import timedelta

    session = await _create_session(db, run_status="in_progress")
    session.started_at = utc_now() - timedelta(hours=2)
    await db.flush()

    fresh = await _create_session(db, run_status="in_progress")
    fresh.started_at = utc_now()
    await db.flush()
    await db.commit()

    count = await timeout_stalled_sessions(db, timeout_minutes=60)
    await db.commit()

    assert count == 1

    await db.refresh(session)
    await db.refresh(fresh)
    assert session.run_status == "error"
    metadata = dict(session.metadata_ or {})
    assert metadata.get("run_completion_reason") == "timeout"
    assert fresh.run_status == "in_progress"


@pytest.mark.asyncio
async def test_timeout_respects_minimum(db):
    from datetime import timedelta

    session = await _create_session(db, run_status="in_progress")
    session.started_at = utc_now() - timedelta(minutes=3)
    await db.flush()
    await db.commit()

    count = await timeout_stalled_sessions(db, timeout_minutes=1)
    await db.commit()

    assert count == 0


@pytest.mark.asyncio
async def test_workspace_paths_are_session_isolated(db):
    from app.services.session.workspace import get_session_workspace_root

    s1 = await _create_session(db)
    s2 = await _create_session(db)
    await db.commit()

    path1 = await get_session_workspace_root(db, s1.id, create=False)
    path2 = await get_session_workspace_root(db, s2.id, create=False)

    assert path1 != path2
    assert s1.id in str(path1)
    assert s2.id in str(path2)


@pytest.mark.asyncio
async def test_concurrent_different_tasks_do_not_interfere(db):
    sessions = []
    for _ in range(5):
        s = await _create_session(db, run_status="in_progress")
        sessions.append(s)
    await db.commit()

    for s in sessions:
        await db.refresh(s)
        assert s.run_status == "in_progress"

    project_ids = [s.project_id for s in sessions]
    assert len(set(project_ids)) == 5


@pytest.mark.asyncio
async def test_same_session_single_active_run(db):
    session = await _create_session(db, run_status="in_progress")
    await db.flush()

    with pytest.raises(DoubleTextGuardError):
        await check_double_text_guard(db, session)

    session.run_status = "completed"
    await db.flush()

    await check_double_text_guard(db, session)
