"""Gate facts and reasons must fit the move and are write-once, another workspace's handle cannot move a run, open_run refuses foreign or missing workspaces and values outside closed sets, and errors carry fixed text."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as ChatSession
from app.models import User
from app.models.runtime.product_run import ProductRun, ProductRunAttempt
from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.product_run.errors import (
    IllegalProductRunTransitionError,
    InvalidProductRunInputError,
    ProductRunScopeError,
    StaleProductRunTransitionError,
)
from app.services.product_run.service import GateFacts, open_run, transition
from tests.services.workflow.product_run_service_support import ALLOWED, DENIED, _audit, _open, _workspace_session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("to_state", "end_reason", "gate"),
    [
        ("admitted", None, None),  # the gate decision must be recorded
        ("admitted", None, DENIED),  # admitted with a denying gate
        ("denied", "gate_denied", ALLOWED),
        ("denied", "gate_missing_profile", DENIED),
        ("needs_configuration", "gate_needs_configuration", DENIED),
        ("failed", "preparation_failed", ALLOWED),  # the gate was never reached
        ("failed", "provider_error", None),  # a runtime cause before admission
    ],
)
async def test_gate_facts_and_reasons_must_fit_the_move(
    db: AsyncSession, auth_user: User, to_state, end_reason, gate
) -> None:
    _, _, handle = await _open(db, auth_user)
    with pytest.raises(IllegalProductRunTransitionError):
        await transition(db, handle, to_state=to_state, end_reason=end_reason, gate=gate)
    assert await _audit(db, handle.run_id) == [(1, None, "requested", None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("end_reason", "gate"),
    [
        ("gate_missing_profile", GateFacts(status="denied", decision_source="missing_profile")),
        ("gate_unknown_status", GateFacts(status="unknown", decision_source="unknown_execution_profile_status")),
        ("gate_denied", DENIED),
    ],
)
async def test_each_denying_gate_decision_is_recorded_once(db: AsyncSession, auth_user: User, end_reason, gate) -> None:
    _, _, handle = await _open(db, auth_user)
    handle = await transition(db, handle, to_state="denied", end_reason=end_reason, gate=gate)
    attempt = await db.get(ProductRunAttempt, handle.attempt_id)
    assert (attempt.state, attempt.end_reason, attempt.gate_status, attempt.gate_decision_source) == (
        "denied",
        end_reason,
        gate.status,
        gate.decision_source,
    )


@pytest.mark.asyncio
async def test_gate_facts_are_write_once(db: AsyncSession, auth_user: User) -> None:
    _, _, handle = await _open(db, auth_user)
    handle = await transition(db, handle, to_state="admitted", gate=ALLOWED)
    handle = await transition(db, handle, to_state="running")
    with pytest.raises(IllegalProductRunTransitionError):
        await transition(db, handle, to_state="finished_unverified", end_reason="runtime_finished", gate=DENIED)
    with pytest.raises(IllegalProductRunTransitionError):
        # A gate block cannot be recorded for an attempt that is already running.
        await transition(db, handle, to_state="needs_clarification", end_reason="gate_needs_clarification")
    attempt = await db.get(ProductRunAttempt, handle.attempt_id)
    assert (attempt.state, attempt.gate_status) == ("running", "allowed")


@pytest.mark.asyncio
async def test_a_handle_carrying_another_workspace_cannot_move_the_run(db: AsyncSession, auth_user: User) -> None:
    _, _, handle = await _open(db, auth_user)
    other_project, _ = await _workspace_session(db, auth_user)
    forged = replace(handle, workspace_id=other_project.id)
    with pytest.raises(StaleProductRunTransitionError):
        await transition(db, forged, to_state="admitted", gate=ALLOWED)
    assert await _audit(db, handle.run_id) == [(1, None, "requested", None)]


@pytest.mark.asyncio
async def test_open_run_refuses_a_workspace_or_owner_that_is_not_the_sessions(
    db: AsyncSession, auth_user: User
) -> None:
    _, session = await _workspace_session(db, auth_user)
    other_project, _ = await _workspace_session(db, auth_user)
    with pytest.raises(ProductRunScopeError):
        await open_run(
            db,
            workspace_id=WorkspaceId.parse(other_project.id),
            owner_user_id=auth_user.id,
            session_id=session.id,
            origin="chat_turn",
        )
    with pytest.raises(ProductRunScopeError):
        await open_run(
            db,
            workspace_id=WorkspaceId.parse(session.project_id),
            owner_user_id=str(uuid.uuid4()),
            session_id=session.id,
            origin="chat_turn",
        )
    count = await db.execute(select(ProductRun.id).where(ProductRun.session_id == session.id))
    assert count.first() is None


@pytest.mark.asyncio
async def test_open_run_refuses_a_session_without_a_workspace(db: AsyncSession, auth_user: User) -> None:
    project, _ = await _workspace_session(db, auth_user)
    unscoped = ChatSession(user_id=auth_user.id, project_id=None)
    db.add(unscoped)
    await db.flush()
    with pytest.raises(ProductRunScopeError):
        await open_run(
            db,
            workspace_id=WorkspaceId.parse(project.id),
            owner_user_id=auth_user.id,
            session_id=unscoped.id,
            origin="chat_turn",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"origin": "scheduler"},
        {"actor": "user"},
        {"session_id": "not-a-uuid"},
        {"turn_user_message_id": "{00000000-0000-4000-8000-000000000000}"},
    ],
)
async def test_open_run_refuses_values_outside_closed_sets(db: AsyncSession, auth_user: User, kwargs) -> None:
    project, session = await _workspace_session(db, auth_user)
    arguments = {
        "workspace_id": WorkspaceId.parse(project.id),
        "owner_user_id": auth_user.id,
        "session_id": session.id,
        "origin": "chat_turn",
    } | kwargs
    with pytest.raises(InvalidProductRunInputError):
        await open_run(db, **arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "gate",
    [
        GateFacts(status="maybe", decision_source="execution_profile"),
        GateFacts(status="allowed", decision_source="free text"),
        GateFacts(status="allowed", decision_source="execution_profile", execution_profile_id="id with space"),
    ],
)
async def test_gate_facts_outside_the_allow_list_are_refused(db: AsyncSession, auth_user: User, gate) -> None:
    _, _, handle = await _open(db, auth_user)
    with pytest.raises(InvalidProductRunInputError):
        await transition(db, handle, to_state="admitted", gate=gate)
    assert await _audit(db, handle.run_id) == [(1, None, "requested", None)]


@pytest.mark.asyncio
async def test_errors_carry_only_fixed_text(db: AsyncSession, auth_user: User) -> None:
    _, _, handle = await _open(db, auth_user)
    with pytest.raises(IllegalProductRunTransitionError) as caught:
        await transition(db, handle, to_state="completed")
    assert str(caught.value) == "product run transition is not allowed"
    assert caught.value.code == "illegal_transition"
    assert handle.run_id not in str(caught.value)
