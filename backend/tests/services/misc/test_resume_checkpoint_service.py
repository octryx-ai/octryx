"""Tests for resume checkpoint and run resumption service."""

import uuid

import pytest

from app.models import ContextCheckpoint, ResumeCheckpoint, Session
from app.models.runtime.durable_runtime import (
    RECOVERY_POLICY_AUTO_RETRY,
    RECOVERY_POLICY_FAIL,
    RECOVERY_POLICY_MANUAL_RESUME,
)
from app.services.resume_checkpoint_service import (
    attempt_resume,
    can_resume,
    create_resume_checkpoint,
    find_all_recoverable_sessions,
    get_active_checkpoint_for_session,
    get_session_recovery_policy,
    mark_resume_failed,
    mark_resume_success,
)


@pytest.mark.asyncio
async def test_create_resume_checkpoint(db):
    session_id = str(uuid.uuid4())
    session = Session(id=session_id, user_id="u1", agent_type="change", status="active", metadata_={})
    db.add(session)
    checkpoint = ContextCheckpoint(
        id=str(uuid.uuid4()),
        session_id=session_id,
        checkpoint_name="test-checkpoint",
        status="active",
    )
    db.add(checkpoint)
    await db.commit()

    rc = await create_resume_checkpoint(db, session_id=session_id, checkpoint_id=checkpoint.id)
    await db.commit()
    assert rc.session_id == session_id
    assert rc.checkpoint_id == checkpoint.id
    assert rc.status == "pending"
    assert rc.resume_attempt_count == 0


@pytest.mark.asyncio
async def test_create_resume_checkpoint_idempotent(db):
    session_id = str(uuid.uuid4())
    session = Session(id=session_id, user_id="u1", agent_type="change", status="active", metadata_={})
    db.add(session)
    checkpoint = ContextCheckpoint(
        id=str(uuid.uuid4()),
        session_id=session_id,
        checkpoint_name="test-checkpoint",
        status="active",
    )
    db.add(checkpoint)
    await db.commit()

    rc1 = await create_resume_checkpoint(db, session_id=session_id, checkpoint_id=checkpoint.id)
    rc2 = await create_resume_checkpoint(db, session_id=session_id, checkpoint_id=checkpoint.id)
    assert rc1.id == rc2.id


@pytest.mark.asyncio
async def test_can_resume_pending(db):
    rc = ResumeCheckpoint(
        id=str(uuid.uuid4()),
        session_id="s1",
        checkpoint_id="c1",
        status="pending",
        resume_attempt_count=0,
        max_resume_attempts=3,
    )
    assert can_resume(rc) is True


@pytest.mark.asyncio
async def test_can_resume_exhausted(db):
    rc = ResumeCheckpoint(
        id=str(uuid.uuid4()),
        session_id="s1",
        checkpoint_id="c1",
        status="pending",
        resume_attempt_count=3,
        max_resume_attempts=3,
    )
    assert can_resume(rc) is False


@pytest.mark.asyncio
async def test_can_resume_already_resumed(db):
    rc = ResumeCheckpoint(
        id=str(uuid.uuid4()),
        session_id="s1",
        checkpoint_id="c1",
        status="resumed",
        resume_attempt_count=1,
        max_resume_attempts=3,
    )
    assert can_resume(rc) is False


@pytest.mark.asyncio
async def test_attempt_resume_increments_count(db):
    session_id = str(uuid.uuid4())
    session = Session(id=session_id, user_id="u1", agent_type="change", status="active", metadata_={})
    db.add(session)
    checkpoint = ContextCheckpoint(
        id=str(uuid.uuid4()),
        session_id=session_id,
        checkpoint_name="test-checkpoint",
        status="active",
    )
    db.add(checkpoint)
    await db.commit()

    rc = await create_resume_checkpoint(db, session_id=session_id, checkpoint_id=checkpoint.id)
    await db.commit()

    updated = await attempt_resume(db, session, checkpoint, resume_checkpoint=rc)
    assert updated.resume_attempt_count == 1
    assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_mark_resume_success(db):
    session_id = str(uuid.uuid4())
    session = Session(id=session_id, user_id="u1", agent_type="change", status="active", metadata_={})
    db.add(session)
    checkpoint = ContextCheckpoint(
        id=str(uuid.uuid4()),
        session_id=session_id,
        checkpoint_name="test-checkpoint",
        status="active",
    )
    db.add(checkpoint)
    await db.commit()

    rc = await create_resume_checkpoint(db, session_id=session_id, checkpoint_id=checkpoint.id)
    await db.commit()

    updated = await mark_resume_success(db, rc)
    assert updated.status == "resumed"


@pytest.mark.asyncio
async def test_mark_resume_failed(db):
    session_id = str(uuid.uuid4())
    session = Session(id=session_id, user_id="u1", agent_type="change", status="active", metadata_={})
    db.add(session)
    checkpoint = ContextCheckpoint(
        id=str(uuid.uuid4()),
        session_id=session_id,
        checkpoint_name="test-checkpoint",
        status="active",
    )
    db.add(checkpoint)
    await db.commit()

    rc = await create_resume_checkpoint(db, session_id=session_id, checkpoint_id=checkpoint.id)
    await db.commit()

    updated = await mark_resume_failed(db, rc, "LLM timeout")
    assert updated.status == "failed"
    assert updated.last_error == "LLM timeout"


@pytest.mark.asyncio
async def test_get_active_checkpoint_for_session(db):
    session_id = str(uuid.uuid4())
    session = Session(id=session_id, user_id="u1", agent_type="change", status="active", metadata_={})
    db.add(session)
    checkpoint = ContextCheckpoint(
        id=str(uuid.uuid4()),
        session_id=session_id,
        checkpoint_name="active-checkpoint",
        status="active",
    )
    db.add(checkpoint)
    # Also create a released one
    released = ContextCheckpoint(
        id=str(uuid.uuid4()),
        session_id=session_id,
        checkpoint_name="released-checkpoint",
        status="released",
    )
    db.add(released)
    await db.commit()

    found = await get_active_checkpoint_for_session(db, session_id=session_id)
    assert found is not None
    assert found.id == checkpoint.id
    assert found.status == "active"


@pytest.mark.asyncio
async def test_find_all_recoverable_sessions_auto_retry(db):
    session_id = str(uuid.uuid4())
    session = Session(
        id=session_id,
        user_id="u1",
        agent_type="change",
        status="active",
        metadata_={},
        run_status="in_progress",
        recovery_policy=RECOVERY_POLICY_AUTO_RETRY,
    )
    db.add(session)
    checkpoint = ContextCheckpoint(
        id=str(uuid.uuid4()),
        session_id=session_id,
        checkpoint_name="test",
        status="active",
    )
    db.add(checkpoint)
    await db.commit()

    results = await find_all_recoverable_sessions(db)
    assert any(s.id == session_id for s, c in results)


@pytest.mark.asyncio
async def test_find_all_recoverable_sessions_excludes_completed(db):
    session_id = str(uuid.uuid4())
    session = Session(
        id=session_id,
        user_id="u1",
        agent_type="change",
        status="completed",
        metadata_={},
        run_status="completed",
        recovery_policy=RECOVERY_POLICY_AUTO_RETRY,
    )
    db.add(session)
    checkpoint = ContextCheckpoint(
        id=str(uuid.uuid4()),
        session_id=session_id,
        checkpoint_name="test",
        status="active",
    )
    db.add(checkpoint)
    await db.commit()

    results = await find_all_recoverable_sessions(db)
    assert not any(s.id == session_id for s, c in results)


@pytest.mark.asyncio
async def test_get_session_recovery_policy_defaults(db):
    session = Session(id=str(uuid.uuid4()), user_id="u1", agent_type="change", status="active", metadata_={})
    assert get_session_recovery_policy(session) == RECOVERY_POLICY_MANUAL_RESUME


@pytest.mark.asyncio
async def test_get_session_recovery_policy_explicit(db):
    session = Session(
        id=str(uuid.uuid4()),
        user_id="u1",
        agent_type="change",
        status="active",
        metadata_={},
        recovery_policy=RECOVERY_POLICY_FAIL,
    )
    assert get_session_recovery_policy(session) == RECOVERY_POLICY_FAIL
