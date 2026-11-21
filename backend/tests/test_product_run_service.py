"""Product Run service: scoped opening, compare-and-set moves, gap-free audit."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.runtime.product_run import ProductRun, ProductRunAttempt
from app.services.product_run.errors import IllegalProductRunTransitionError, StaleProductRunTransitionError
from app.services.product_run.service import GateFacts, transition
from tests.product_run_service_support import ALLOWED, DENIED, _audit, _open


@pytest.mark.asyncio
async def test_open_run_records_requested_with_the_session_workspace(db: AsyncSession, auth_user: User) -> None:
    project, session, handle = await _open(db, auth_user)

    run = await db.get(ProductRun, handle.run_id)
    attempt = await db.get(ProductRunAttempt, handle.attempt_id)
    assert run is not None and attempt is not None
    assert (run.workspace_id, run.session_id, run.owner_user_id) == (project.id, session.id, auth_user.id)
    assert (run.state, run.attempt_count, run.version, run.origin) == ("requested", 1, 1, "chat_turn")
    assert run.workspace_source == "session_project"
    assert (attempt.workspace_id, attempt.attempt_number, attempt.state) == (project.id, 1, "requested")
    assert await _audit(db, handle.run_id) == [(1, None, "requested", None)]


@pytest.mark.asyncio
async def test_allowed_turn_moves_to_finished_unverified_with_gap_free_audit(db: AsyncSession, auth_user: User) -> None:
    _, _, handle = await _open(db, auth_user)
    trace_id = str(uuid.uuid4())

    handle = await transition(
        db,
        handle,
        to_state="admitted",
        gate=GateFacts(status="allowed", decision_source="execution_profile", execution_profile_id="standard-chat"),
    )
    handle = await transition(db, handle, to_state="running")
    handle = await transition(
        db, handle, to_state="finished_unverified", end_reason="runtime_finished", final_trace_id=trace_id
    )

    run = await db.get(ProductRun, handle.run_id)
    attempt = await db.get(ProductRunAttempt, handle.attempt_id)
    assert (run.state, run.end_reason, run.version) == ("finished_unverified", "runtime_finished", 4)
    assert run.ended_at is not None
    assert (attempt.gate_status, attempt.gate_decision_source, attempt.execution_profile_id) == (
        "allowed",
        "execution_profile",
        "standard-chat",
    )
    assert attempt.started_at is not None and attempt.ended_at is not None
    assert attempt.final_trace_id == trace_id
    assert await _audit(db, handle.run_id) == [
        (1, None, "requested", None),
        (2, "requested", "admitted", None),
        (3, "admitted", "running", None),
        (4, "running", "finished_unverified", "runtime_finished"),
    ]


@pytest.mark.asyncio
async def test_gate_block_ends_the_run_before_admission(db: AsyncSession, auth_user: User) -> None:
    _, _, handle = await _open(db, auth_user)
    handle = await transition(
        db,
        handle,
        to_state="needs_configuration",
        end_reason="gate_needs_configuration",
        gate=GateFacts(status="needs_configuration", decision_source="execution_profile"),
    )
    assert handle.state == "needs_configuration"
    with pytest.raises(IllegalProductRunTransitionError):
        await transition(db, handle, to_state="running")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("to_state", "end_reason"),
    [
        ("running", None),  # skips admission
        ("completed", None),  # reserved: no transition reaches it
        ("verifying", None),
        ("failed", None),  # terminal state without a reason
        ("failed", "runtime_finished"),  # reason of another state
        ("admitted", "gate_denied"),  # non-terminal state with a reason
    ],
)
async def test_illegal_moves_leave_no_trace(db: AsyncSession, auth_user: User, to_state, end_reason) -> None:
    _, _, handle = await _open(db, auth_user)
    with pytest.raises(IllegalProductRunTransitionError):
        await transition(db, handle, to_state=to_state, end_reason=end_reason)
    run = await db.get(ProductRun, handle.run_id)
    assert (run.state, run.version) == ("requested", 1)
    assert await _audit(db, handle.run_id) == [(1, None, "requested", None)]


@pytest.mark.asyncio
async def test_stale_handle_is_refused_without_side_effects(db: AsyncSession, auth_user: User) -> None:
    _, _, handle = await _open(db, auth_user)
    await transition(db, handle, to_state="admitted", gate=ALLOWED)

    # A second writer still holding the original handle loses the compare-and-set.
    with pytest.raises(StaleProductRunTransitionError):
        await transition(db, handle, to_state="denied", end_reason="gate_denied", gate=DENIED)

    run = await db.get(ProductRun, handle.run_id)
    assert (run.state, run.version) == ("admitted", 2)
    assert [row[0] for row in await _audit(db, handle.run_id)] == [1, 2]


@pytest.mark.asyncio
async def test_a_half_done_move_is_rolled_back_and_the_transaction_stays_usable(
    db: AsyncSession, auth_user: User
) -> None:
    _, _, handle = await _open(db, auth_user)
    # The run matches, so its UPDATE succeeds; the attempt does not, so the move must roll back.
    with pytest.raises(StaleProductRunTransitionError):
        await transition(db, replace(handle, attempt_version=7), to_state="admitted", gate=ALLOWED)

    run = await db.get(ProductRun, handle.run_id)
    attempt = await db.get(ProductRunAttempt, handle.attempt_id)
    assert (run.state, run.version) == ("requested", 1)
    assert (attempt.state, attempt.version) == ("requested", 1)
    assert await _audit(db, handle.run_id) == [(1, None, "requested", None)]

    moved = await transition(db, handle, to_state="admitted", gate=ALLOWED)
    assert moved.state == "admitted"
    assert [row[0] for row in await _audit(db, handle.run_id)] == [1, 2]


@pytest.mark.asyncio
async def test_objects_loaded_before_a_move_read_the_new_state(db: AsyncSession, auth_user: User) -> None:
    _, _, handle = await _open(db, auth_user)
    run = await db.get(ProductRun, handle.run_id)
    attempt = await db.get(ProductRunAttempt, handle.attempt_id)
    assert run.state == attempt.state == "requested"

    await transition(db, handle, to_state="admitted", gate=ALLOWED)

    assert (run.state, run.version) == ("admitted", 2)
    assert (attempt.state, attempt.gate_status) == ("admitted", "allowed")
