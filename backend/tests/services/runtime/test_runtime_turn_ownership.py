"""Turns whose owning process died are settled; paused and live-owned turns are not."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Project, User
from app.models import Session as ChatSession
from app.models.runtime.process_lease import RuntimeProcessLease
from app.models.runtime.product_run import ProductRunAttempt, ProductRunTransition
from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.product_run.service import GateFacts, ProductRunHandle, open_run, transition
from app.services.runtime_ownership.interrupted_turns import (
    AUDIT_ACTION,
    TRIGGER_SWEEP,
    settle_interrupted_turns,
)
from app.services.runtime_ownership.process_identity import current_process_id
from app.services.runtime_ownership.process_lease import renew_process_lease
from app.services.runtime_ownership.worker import RuntimeOwnershipWorker
from app.services.session.run_state import RUN_STATUS_IN_PROGRESS, set_session_run_state
from app.time_utils import utc_now

ALLOWED = GateFacts(status="allowed", decision_source="execution_profile")


class _SharedSession:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def __aenter__(self) -> AsyncSession:
        return self._db

    async def __aexit__(self, *_exc) -> None:
        return None


async def _running_turn(db: AsyncSession, owner: User, *, owner_process_id: str | None) -> tuple[ChatSession, ProductRunHandle]:
    project = Project(name=f"ownership-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    session = ChatSession(user_id=owner.id, project_id=project.id, status="running")
    set_session_run_state(session, RUN_STATUS_IN_PROGRESS)
    session.turn_owner_process_id = owner_process_id
    db.add(session)
    await db.flush()
    handle = await open_run(
        db, workspace_id=WorkspaceId.parse(project.id), owner_user_id=owner.id, session_id=session.id, origin="chat_turn"
    )
    handle = await transition(db, handle, to_state="admitted", gate=ALLOWED)
    handle = await transition(db, handle, to_state="running")
    await db.execute(
        update(ProductRunAttempt).where(ProductRunAttempt.id == handle.attempt_id).values(owner_process_id=owner_process_id)
    )
    await db.flush()
    return session, handle


async def _attempt(db: AsyncSession, handle: ProductRunHandle) -> tuple[str, str | None]:
    row = (
        await db.execute(
            select(ProductRunAttempt.state, ProductRunAttempt.end_reason).where(ProductRunAttempt.id == handle.attempt_id)
        )
    ).one()
    return row.state, row.end_reason


async def _expired_lease(db: AsyncSession) -> str:
    process_id = str(uuid.uuid4())
    now = utc_now()
    db.add(
        RuntimeProcessLease(
            id=process_id,
            started_at=now - timedelta(hours=1),
            heartbeat_at=now - timedelta(minutes=10),
            expires_at=now - timedelta(minutes=5),
        )
    )
    await db.flush()
    return process_id


@pytest.mark.asyncio
async def test_startup_settles_a_turn_whose_process_is_gone(db: AsyncSession, auth_user: User) -> None:
    session, handle = await _running_turn(db, auth_user, owner_process_id=str(uuid.uuid4()))
    worker = RuntimeOwnershipWorker(lambda: _SharedSession(db), heartbeat_seconds=3600)
    try:
        settlement = await worker.start()
    finally:
        await worker.stop()

    assert settlement is not None and (settlement.sessions, settlement.attempts) == (1, 1)
    await db.refresh(session)
    metadata = session.metadata_ or {}
    assert session.status == "active"
    assert metadata["run_status"] == "failed"
    assert metadata["run_completion_reason"] == "interrupted_by_restart"
    assert metadata["last_stop_reason"] == "interrupted_by_restart"
    assert await _attempt(db, handle) == ("failed", "interrupted_by_restart")
    last = (
        await db.execute(
            select(ProductRunTransition.to_state, ProductRunTransition.end_reason, ProductRunTransition.actor)
            .where(ProductRunTransition.run_id == handle.run_id)
            .order_by(ProductRunTransition.sequence.desc())
            .limit(1)
        )
    ).one()
    assert tuple(last) == ("failed", "interrupted_by_restart", "system")
    audit = (
        (await db.execute(select(AuditLog).where(AuditLog.action == AUDIT_ACTION, AuditLog.session_id == session.id)))
        .scalars()
        .one()
    )
    assert audit.details == {
        "reason": "interrupted_by_restart",
        "trigger": "startup",
        "session_settled": 1,
        "attempts_settled": 1,
    }


@pytest.mark.asyncio
async def test_sweep_settles_a_turn_whose_lease_expired(db: AsyncSession, auth_user: User) -> None:
    session, handle = await _running_turn(db, auth_user, owner_process_id=await _expired_lease(db))

    settlement = await settle_interrupted_turns(db, trigger=TRIGGER_SWEEP)

    assert (settlement.sessions, settlement.attempts) == (1, 1)
    await db.refresh(session)
    assert session.status == "active"
    assert await _attempt(db, handle) == ("failed", "interrupted_by_restart")


@pytest.mark.asyncio
async def test_a_waiting_approval_pause_is_left_resumable(db: AsyncSession, auth_user: User) -> None:
    session, handle = await _running_turn(db, auth_user, owner_process_id=await _expired_lease(db))
    await transition(db, handle, to_state="waiting_approval", end_reason="approval_pending")
    session.status = "pending_approval"
    await db.flush()

    settlement = await settle_interrupted_turns(db, trigger=TRIGGER_SWEEP)

    assert (settlement.sessions, settlement.attempts) == (0, 0)
    await db.refresh(session)
    assert session.status == "pending_approval"
    assert await _attempt(db, handle) == ("waiting_approval", "approval_pending")


@pytest.mark.asyncio
async def test_a_turn_owned_by_a_live_lease_is_untouched(db: AsyncSession, auth_user: User) -> None:
    await renew_process_lease(db)
    session, handle = await _running_turn(db, auth_user, owner_process_id=current_process_id())

    settlement = await settle_interrupted_turns(db, trigger=TRIGGER_SWEEP)

    assert (settlement.sessions, settlement.attempts) == (0, 0)
    await db.refresh(session)
    assert session.status == "running"
    assert (session.metadata_ or {})["run_status"] == RUN_STATUS_IN_PROGRESS
    assert await _attempt(db, handle) == ("running", None)
