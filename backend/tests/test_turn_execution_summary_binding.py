"""The agent marks only a turn's final trace finished, and the turn's policy decision binding survives failures, closing and nested runs."""

import pytest

import app.agent.engine as engine_module
from app.agent.core.runtime.trace_runtime import persist_turn_trace
from app.agent.core.runtime.turn_execution_binding import bound_turn_execution_snapshot
from app.agent.engine import run_agent
from app.services.session.turn_execution_snapshot import (
    RUNTIME_OUTCOME_FINISHED,
    RUNTIME_OUTCOME_KEY,
    TURN_EXECUTION_SNAPSHOT_KEY,
)
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN
from tests.turn_execution_summary_api_support import (
    _admin,
    _fake_runtime,
    _run_turn,
    _session,
    _session_traces,
    _summary,
    _user_message,
)


@pytest.mark.asyncio
async def test_run_agent_marks_only_the_final_trace_of_a_turn_finished(db, monkeypatch):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    user = await _user_message(db, session, "ping")
    session.metadata_ = {**UNDECLARED_READ_ONLY_RUN, "current_turn_user_message_id": user.id}
    await db.commit()
    _fake_runtime(monkeypatch)

    await _run_turn(db, session, admin.id)
    traces = await _session_traces(db, session.id)
    snapshots = [trace.context_snapshot_json[TURN_EXECUTION_SNAPSHOT_KEY] for trace in traces]
    assert {snapshot["turn"]["user_message_id"] for snapshot in snapshots} == {user.id}
    assert [snapshot.get(RUNTIME_OUTCOME_KEY) for snapshot in snapshots][-1] == RUNTIME_OUTCOME_FINISHED
    assert all(RUNTIME_OUTCOME_KEY not in snapshot for snapshot in snapshots[:-1])
    assert (await _summary(db, admin.id, traces[-1]))["state"] == "finished_unverified"
    assert bound_turn_execution_snapshot(session.id) is None


@pytest.mark.asyncio
async def test_second_turn_failing_before_bind_does_not_stamp_the_first_decision(db, monkeypatch):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    await db.commit()
    _fake_runtime(monkeypatch)
    await _run_turn(db, session, admin.id)
    first_turn_traces = len(await _session_traces(db, session.id))

    observed: list = []

    async def failing_prepare(**_kwargs):
        # Anything persisted while the next turn prepares must not inherit turn one's decision.
        observed.append(bound_turn_execution_snapshot(session.id))
        trace = await persist_turn_trace(
            db=db,
            session_id=session.id,
            message_id=None,
            provider="p",
            model="m",
            input_messages=[],
            context_snapshot={},
            tool_trace=[],
            raw_output={},
            usage={},
        )
        observed.append(trace.context_snapshot_json.get(TURN_EXECUTION_SNAPSHOT_KEY))
        raise RuntimeError("preparation failed")

    monkeypatch.setattr(engine_module, "_prepare_agent_run", failing_prepare)
    with pytest.raises(RuntimeError, match="preparation failed"):
        await _run_turn(db, session, admin.id)
    assert observed == [None, None]
    assert bound_turn_execution_snapshot(session.id) is None
    assert len(await _session_traces(db, session.id)) == first_turn_traces + 1


@pytest.mark.asyncio
async def test_closing_the_run_agent_generator_clears_the_binding(db, monkeypatch):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    await db.commit()
    real_prepare = engine_module._prepare_agent_run

    async def prepare_needing_configuration(**kwargs):
        prepared = await real_prepare(**kwargs)
        prepared.session_metadata["execution_profile"] = {
            **dict(prepared.session_metadata.get("execution_profile") or {}),
            "status": "needs_configuration",
        }
        return prepared

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare_needing_configuration)
    events = run_agent(
        session_id=session.id, user_message="ping", user_id=admin.id, project_id=None, agent_type="diagnosis", db=db
    )
    await events.__anext__()
    assert bound_turn_execution_snapshot(session.id) is not None
    await events.aclose()
    assert bound_turn_execution_snapshot(session.id) is None


@pytest.mark.asyncio
async def test_nested_run_agent_for_another_session_keeps_the_parent_decision(db, monkeypatch):
    admin = await _admin(db)
    parent = await _session(db, admin.id)
    child = await _session(db, admin.id)
    await db.commit()
    real_prepare = engine_module._prepare_agent_run

    async def prepare(**kwargs):
        prepared = await real_prepare(**kwargs)
        if kwargs["session_id"] == child.id:
            prepared.session_metadata["execution_profile"] = {
                **dict(prepared.session_metadata.get("execution_profile") or {}),
                "status": "needs_configuration",
            }
        return prepared

    async def resolve(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        # The parent's model call runs a complete child turn inline.
        await _run_turn(db, child, admin.id)
        assert bound_turn_execution_snapshot(child.id) is None
        assert bound_turn_execution_snapshot(parent.id)["gate"]["allowed"] is True
        return (
            {"content": "Pong", "tool_calls": None, "model": "claude-haiku-4.5", "usage": {}},
            runtimes[0],
        )

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare)
    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", resolve)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", chat)

    await _run_turn(db, parent, admin.id)
    parent_traces = await _session_traces(db, parent.id)
    child_traces = await _session_traces(db, child.id)
    assert parent_traces and child_traces
    assert all(t.context_snapshot_json[TURN_EXECUTION_SNAPSHOT_KEY]["gate"]["allowed"] for t in parent_traces)
    assert all(not t.context_snapshot_json[TURN_EXECUTION_SNAPSHOT_KEY]["gate"]["allowed"] for t in child_traces)
    assert (await _summary(db, admin.id, parent_traces[-1]))["state"] == "finished_unverified"
    assert (await _summary(db, admin.id, child_traces[-1]))["state"] == "needs_configuration"
    assert bound_turn_execution_snapshot(parent.id) is None
