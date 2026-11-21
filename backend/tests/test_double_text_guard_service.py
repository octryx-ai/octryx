"""Tests for double-texting guard and message idempotency."""

import uuid

import pytest

from app.models import Message, Session
from app.services.double_text_guard_service import (
    DoubleTextGuardError,
    check_double_text_guard,
    mark_session_complete,
    mark_session_failed,
    mark_session_running,
)
from app.services.session.run_state import RUN_STATUS_IN_PROGRESS


@pytest.mark.asyncio
async def test_double_text_guard_passes_when_not_running(db):
    session = Session(id=str(uuid.uuid4()), user_id="u1", agent_type="change", status="active", metadata_={})
    db.add(session)
    await db.commit()

    # No exception should be raised
    await check_double_text_guard(db, session)


@pytest.mark.asyncio
async def test_double_text_guard_raises_when_in_progress(db):
    session = Session(
        id=str(uuid.uuid4()),
        user_id="u1",
        agent_type="change",
        status="active",
        metadata_={},
        run_status=RUN_STATUS_IN_PROGRESS,
    )
    db.add(session)
    await db.commit()

    with pytest.raises(DoubleTextGuardError) as exc_info:
        await check_double_text_guard(db, session)
    assert exc_info.value.session_id == session.id
    assert exc_info.value.current_status == RUN_STATUS_IN_PROGRESS


@pytest.mark.asyncio
async def test_mark_session_running(db):
    session = Session(id=str(uuid.uuid4()), user_id="u1", agent_type="change", status="active", metadata_={})
    db.add(session)
    await db.commit()

    await mark_session_running(db, session)
    assert session.run_status == RUN_STATUS_IN_PROGRESS


@pytest.mark.asyncio
async def test_mark_session_complete(db):
    session = Session(
        id=str(uuid.uuid4()),
        user_id="u1",
        agent_type="change",
        status="active",
        metadata_={},
        run_status=RUN_STATUS_IN_PROGRESS,
    )
    db.add(session)
    await db.commit()

    await mark_session_complete(db, session)
    assert session.run_status == "completed"


@pytest.mark.asyncio
async def test_mark_session_failed(db):
    session = Session(
        id=str(uuid.uuid4()),
        user_id="u1",
        agent_type="change",
        status="active",
        metadata_={},
        run_status=RUN_STATUS_IN_PROGRESS,
    )
    db.add(session)
    await db.commit()

    await mark_session_failed(db, session, error="LLM timeout")
    assert session.run_status == "error"
    assert session.metadata_.get("last_error") == "LLM timeout"


@pytest.mark.asyncio
async def test_idempotency_key_on_message(db):
    session_id = str(uuid.uuid4())
    session = Session(id=session_id, user_id="u1", agent_type="change", status="active", metadata_={})
    db.add(session)
    await db.commit()

    key = str(uuid.uuid4())
    msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="user",
        content="Hello world",
        idempotency_key=key,
    )
    db.add(msg)
    await db.commit()

    fetched = await db.get(Message, msg.id)
    assert fetched is not None
    assert fetched.idempotency_key == key


@pytest.mark.asyncio
async def test_double_text_guard_with_completed_session(db):
    """Completed sessions should allow new turns."""
    session = Session(
        id=str(uuid.uuid4()),
        user_id="u1",
        agent_type="change",
        status="completed",
        metadata_={},
        run_status="completed",
    )
    db.add(session)
    await db.commit()

    # Should not raise — completed is a terminal state
    await check_double_text_guard(db, session)


@pytest.mark.asyncio
async def test_double_text_guard_syncs_metadata_to_db(db):
    """If metadata has in_progress but DB column doesn't, sync it."""
    session = Session(
        id=str(uuid.uuid4()),
        user_id="u1",
        agent_type="change",
        status="active",
        metadata_={"run_status": RUN_STATUS_IN_PROGRESS},
        run_status=None,
    )
    db.add(session)
    await db.commit()

    with pytest.raises(DoubleTextGuardError):
        await check_double_text_guard(db, session)
