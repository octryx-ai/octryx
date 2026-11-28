"""Run/Attempt identity in ``turn_execution_summary.v1``."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models import Message, Project, Session, TurnTrace, User
from app.models.runtime.product_run import ProductRunTransition
from app.services.auth import hash_password
from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.product_run.service import GateFacts, open_run, transition
from app.services.product_run.turn_stamp import PRODUCT_RUN_STAMP_KEY, bound_stamp, unscoped_stamp
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import (
    RUNTIME_OUTCOME_FINISHED,
    RUNTIME_OUTCOME_KEY,
    TURN_EXECUTION_SNAPSHOT_KEY,
    build_turn_execution_snapshot,
)
from app.services.session.turn_execution_summary_service import load_user_turn_execution_summary
from app.services.session.turn_run_identity import ResolvedTurnRun, build_run_identity
from tests.conftest import ADMIN_PASSWORD

ALLOWED = GateFacts(status="allowed", decision_source="execution_profile")


def _empty(kind: str) -> dict:
    return {"kind": kind, "product_run_id": None, "run_state": None, "attempt": None}


def _snapshot(stamp: dict | None) -> dict:
    profile = {
        "version": "execution_profile.v1",
        "status": "allowed",
        "profile_id": "direct_chat_safe",
        "decision_source": "direct_chat_safe",
        "execution_strategy": "direct",
    }
    snapshot = build_turn_execution_snapshot(
        execution_profile=profile,
        gate=evaluate_execution_gate(profile),
        session_metadata={},
        agent_definition=None,
    )
    snapshot[RUNTIME_OUTCOME_KEY] = RUNTIME_OUTCOME_FINISHED
    if stamp is not None:
        snapshot[PRODUCT_RUN_STAMP_KEY] = stamp
    return snapshot


def _context(stamp: dict | None) -> dict:
    return {TURN_EXECUTION_SNAPSHOT_KEY: _snapshot(stamp)}


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _workspace_session(db, owner_id: str) -> Session:
    project = Project(name=f"run-identity-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    session = Session(id=str(uuid.uuid4()), user_id=owner_id, project_id=project.id, agent_type="diagnosis")
    db.add(session)
    await db.flush()
    return session


async def _finished_run(db, session: Session):
    handle = await open_run(
        db,
        workspace_id=WorkspaceId.parse(session.project_id),
        owner_user_id=session.user_id,
        session_id=session.id,
        origin="chat_turn",
    )
    handle = await transition(db, handle, to_state="admitted", gate=ALLOWED)
    handle = await transition(db, handle, to_state="running")
    return await transition(db, handle, to_state="finished_unverified", end_reason="runtime_finished")


def _stamp_for(handle, **overrides) -> dict:
    values = {"run_id": handle.run_id, "attempt_id": handle.attempt_id, "attempt_number": 1, "origin": "chat_turn"}
    values.update(overrides)
    return bound_stamp(**values)


async def _trace(db, session: Session, stamp: dict | None) -> TurnTrace:
    message = Message(id=str(uuid.uuid4()), session_id=session.id, role="assistant", content="Done.")
    db.add(message)
    await db.flush()
    trace = TurnTrace(
        id=str(uuid.uuid4()),
        session_id=session.id,
        message_id=message.id,
        provider="openrouter",
        model="stepfun/step-3.5-flash:free",
        input_messages_json=[],
        context_snapshot_json=_context(stamp),
        tool_trace_json=[],
        raw_output={"content": "Done."},
        usage_json={},
    )
    db.add(trace)
    await db.flush()
    return trace


async def _identity(db, user_id: str, trace: TurnTrace) -> dict:
    summary = await load_user_turn_execution_summary(db, user_id=user_id, trace_id=trace.id)
    return summary["run_identity"]


def test_stamp_statuses_map_to_closed_kinds_without_a_row() -> None:
    run_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
    bound = bound_stamp(run_id=run_id, attempt_id=attempt_id, attempt_number=1, origin="chat_turn")
    assert build_run_identity({}, None) == _empty("compat_turn")
    assert build_run_identity(_context(None), None) == _empty("compat_turn")
    assert build_run_identity(_context(unscoped_stamp(origin="chat_turn")), None) == _empty("unscoped_turn")
    assert build_run_identity(_context({**bound, "status": "done"}), None) == _empty("unresolved")
    assert build_run_identity(_context(bound), None) == _empty("unresolved")
    other = ResolvedTurnRun(run_id, "failed", str(uuid.uuid4()), 1, "failed", "runtime_error")
    assert build_run_identity(_context(bound), other) == _empty("unresolved")


def test_reserved_and_unknown_stored_states_never_read_as_success() -> None:
    run_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
    stamp = bound_stamp(run_id=run_id, attempt_id=attempt_id, attempt_number=1, origin="chat_turn")
    resolved = ResolvedTurnRun(run_id, "verifying", attempt_id, 1, "verifying", "made_up")
    identity = build_run_identity(_context(stamp), resolved)
    assert identity["kind"] == "product_run"
    assert identity["run_state"] == "unknown"
    assert identity["attempt"] == {"id": attempt_id, "number": 1, "state": "unknown", "end_reason": "unknown"}


@pytest.mark.asyncio
async def test_bound_turn_reports_the_stored_run_and_attempt(db) -> None:
    admin = await _admin(db)
    session = await _workspace_session(db, admin.id)
    handle = await _finished_run(db, session)
    trace = await _trace(db, session, _stamp_for(handle))
    audit_before = (await db.execute(select(func.count()).select_from(ProductRunTransition))).scalar_one()

    assert await _identity(db, admin.id, trace) == {
        "kind": "product_run",
        "product_run_id": handle.run_id,
        "run_state": "finished_unverified",
        "attempt": {
            "id": handle.attempt_id,
            "number": 1,
            "state": "finished_unverified",
            "end_reason": "runtime_finished",
        },
    }
    assert not db.new and not db.dirty
    assert (await db.execute(select(func.count()).select_from(ProductRunTransition))).scalar_one() == audit_before


@pytest.mark.asyncio
async def test_unscoped_and_legacy_turns_keep_their_kinds(db) -> None:
    admin = await _admin(db)
    session = await _workspace_session(db, admin.id)
    unscoped = await _trace(db, session, unscoped_stamp(origin="chat_turn"))
    legacy = await _trace(db, session, None)
    assert await _identity(db, admin.id, unscoped) == _empty("unscoped_turn")
    assert await _identity(db, admin.id, legacy) == _empty("compat_turn")


@pytest.mark.asyncio
async def test_forged_stamps_never_resolve(db) -> None:
    admin = await _admin(db)
    session = await _workspace_session(db, admin.id)
    handle = await _finished_run(db, session)
    other_session = await _workspace_session(db, admin.id)
    foreign_handle = await _finished_run(db, other_session)
    forged = [
        _stamp_for(handle, attempt_number=2),
        _stamp_for(handle, attempt_id=foreign_handle.attempt_id),
        _stamp_for(handle, run_id=foreign_handle.run_id),
        _stamp_for(foreign_handle),
        _stamp_for(handle, run_id=str(uuid.uuid4()), attempt_id=str(uuid.uuid4())),
        _stamp_for(handle, origin="api_call"),
        {**_stamp_for(handle), "attempt_number": "1"},
    ]
    for stamp in forged:
        trace = await _trace(db, session, stamp)
        assert await _identity(db, admin.id, trace) == _empty("unresolved"), stamp


@pytest.mark.asyncio
async def test_workspace_or_owner_drift_makes_the_run_unresolved(db) -> None:
    admin = await _admin(db)
    session = await _workspace_session(db, admin.id)
    handle = await _finished_run(db, session)
    trace = await _trace(db, session, _stamp_for(handle))
    moved = Project(name=f"run-identity-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(moved)
    await db.flush()
    session.project_id = moved.id
    await db.flush()
    assert await _identity(db, admin.id, trace) == _empty("unresolved")


@pytest.mark.asyncio
async def test_old_turn_identity_is_stable_after_a_later_run(db) -> None:
    admin = await _admin(db)
    session = await _workspace_session(db, admin.id)
    first = await _finished_run(db, session)
    first_trace = await _trace(db, session, _stamp_for(first))
    before = await _identity(db, admin.id, first_trace)

    second = await open_run(
        db,
        workspace_id=WorkspaceId.parse(session.project_id),
        owner_user_id=admin.id,
        session_id=session.id,
        origin="chat_turn",
    )
    await transition(
        db, second, to_state="denied", end_reason="gate_denied", gate=GateFacts("denied", "execution_profile")
    )
    second_trace = await _trace(db, session, _stamp_for(second))
    await db.commit()
    db.expunge_all()

    assert await _identity(db, admin.id, first_trace) == before
    later = await _identity(db, admin.id, second_trace)
    assert later["product_run_id"] == second.run_id
    assert (later["run_state"], later["attempt"]["end_reason"]) == ("denied", "gate_denied")


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "/admin"])
async def test_route_resolves_for_the_owner_and_404s_for_anyone_else(client, db, prefix) -> None:
    admin = await _admin(db)
    session = await _workspace_session(db, admin.id)
    handle = await _finished_run(db, session)
    trace = await _trace(db, session, _stamp_for(handle))
    outsider = User(
        id=str(uuid.uuid4()),
        username=f"outsider-{uuid.uuid4().hex[:6]}",
        email=f"outsider-{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("secret123"),
        display_name="Outsider",
        is_active=True,
    )
    db.add(outsider)
    await db.commit()
    url = f"{prefix}/chat/api/turn-traces/{trace.id}/execution-summary"

    assert (
        await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    ).status_code == 303
    owner = await client.get(url)
    assert owner.status_code == 200
    assert owner.json()["run_identity"]["kind"] == "product_run"
    assert owner.json()["run_identity"]["attempt"]["id"] == handle.attempt_id

    client.cookies.clear()
    assert (
        await client.post("/admin/login", data={"username": outsider.username, "password": "secret123"})
    ).status_code == 303
    foreign = await client.get(url)
    assert foreign.status_code == 404
    assert handle.run_id not in foreign.text
