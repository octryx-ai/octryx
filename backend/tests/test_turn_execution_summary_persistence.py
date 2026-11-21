"""Allowed and blocked turns persist their policy snapshot, and a trace of an unbound session has none."""

import json

import pytest

import app.agent.engine as engine_module
from app.agent.core.runtime.trace_runtime import persist_turn_trace
from app.agent.core.runtime.turn_execution_binding import bind_turn_execution_snapshot
from app.models import Session
from app.services.session.turn_execution_snapshot import TURN_EXECUTION_SNAPSHOT_KEY
from app.services.session.turn_execution_summary_service import load_user_turn_execution_summary
from tests.turn_execution_summary_api_support import (
    SECRET,
    _admin,
    _allowed_snapshot,
    _fake_runtime,
    _run_turn,
    _session,
    _session_traces,
)


@pytest.mark.asyncio
async def test_allowed_turn_persists_snapshot_and_old_summary_ignores_later_session_changes(db, monkeypatch):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    await db.commit()
    _fake_runtime(monkeypatch, content="Task completed successfully and fully verified!")

    events = await _run_turn(db, session, admin.id)
    assert events[-1].content == "Task completed successfully and fully verified!"

    traces = await _session_traces(db, session.id)
    assert traces
    for trace in traces:
        snapshot = trace.context_snapshot_json[TURN_EXECUTION_SNAPSHOT_KEY]
        assert snapshot["gate"] == {"allowed": True, "status": "allowed", "decision_source": "execution_profile"}
        assert snapshot["execution_profile"]["status"] == "allowed"

    trace_id = traces[-1].id
    before = await load_user_turn_execution_summary(db, user_id=admin.id, trace_id=trace_id)
    # Completion-sounding assistant text never becomes a verified state.
    assert before["state"] == "finished_unverified"

    # Mutate the session's current execution state after the fact.
    refreshed = await db.get(Session, session.id)
    refreshed.metadata_ = {
        **dict(refreshed.metadata_ or {}),
        "execution_profile": {"version": "execution_profile.v1", "status": "denied", "profile_id": "denied:x"},
        "workflow_key": "other-workflow",
    }
    await db.commit()

    after = await load_user_turn_execution_summary(db, user_id=admin.id, trace_id=trace_id)
    assert after == before


@pytest.mark.asyncio
async def test_blocked_turn_persists_snapshot_without_running_the_loop(db, monkeypatch):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    await db.commit()

    real_prepare = engine_module._prepare_agent_run

    async def prepare_needing_configuration(**kwargs):
        prepared = await real_prepare(**kwargs)
        profile = dict(prepared.session_metadata.get("execution_profile") or {})
        profile["status"] = "needs_configuration"
        profile["reason"] = f"Connector inactive {SECRET}"
        prepared.session_metadata["execution_profile"] = profile
        return prepared

    async def fail_if_called(**_kwargs):
        raise AssertionError("model must not be called for a gate-blocked turn")

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare_needing_configuration)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fail_if_called)

    events = await _run_turn(db, session, admin.id)
    assert "requires configuration" in events[-1].content

    traces = await _session_traces(db, session.id)
    assert len(traces) == 1
    trace = traces[0]
    assert trace.provider == "execution-gate"
    snapshot = trace.context_snapshot_json[TURN_EXECUTION_SNAPSHOT_KEY]
    assert snapshot["gate"] == {
        "allowed": False,
        "status": "needs_configuration",
        "decision_source": "execution_profile",
    }
    assert SECRET not in json.dumps(snapshot)

    summary = await load_user_turn_execution_summary(db, user_id=admin.id, trace_id=trace.id)
    assert summary["state"] == "needs_configuration"
    assert summary["next_action"]["kind"] == "complete_configuration"
    assert summary["model"] == {"provider": None, "model": None}
    assert SECRET not in json.dumps(summary)


@pytest.mark.asyncio
async def test_trace_persisted_for_unbound_session_has_no_snapshot(db):
    admin = await _admin(db)
    bound = await _session(db, admin.id)
    unbound = await _session(db, admin.id)
    bind_turn_execution_snapshot(bound.id, _allowed_snapshot())

    trace = await persist_turn_trace(
        db=db,
        session_id=unbound.id,
        message_id=None,
        provider="openrouter",
        model="m",
        input_messages=[],
        context_snapshot={TURN_EXECUTION_SNAPSHOT_KEY: {"version": "turn_execution_snapshot.v1", "forged": True}},
        tool_trace=[],
        raw_output={"content": ""},
        usage={},
    )
    assert TURN_EXECUTION_SNAPSHOT_KEY not in trace.context_snapshot_json
