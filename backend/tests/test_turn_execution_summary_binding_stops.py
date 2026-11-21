"""Turn execution binding lifetimes, explicit runtime stops and outcomes reported by a Mac device."""

import asyncio
from types import SimpleNamespace

import pytest

from app.agent.core.runtime.turn_execution_binding import (
    bind_turn_execution_snapshot,
    bound_turn_execution_snapshot,
    clear_turn_execution_snapshot,
    mark_turn_runtime_stopped,
    scoped_turn_execution_binding,
)
from app.services.session.turn_execution_snapshot import RUNTIME_OUTCOME_KEY, TURN_EXECUTION_SNAPSHOT_KEY
from app.services.session.turn_execution_summary import build_turn_execution_summary, runtime_outcome_from_trace
from tests.turn_execution_summary_support import (
    _evidence,
    _profile,
    _snapshot,
    _stopped_summary,
    _summary,
)


def _decision(status: str) -> dict:
    return _snapshot(_profile(status))


@scoped_turn_execution_binding
async def _fake_run(session_id: str, *, status: str = "allowed", fail_before_bind: bool = False,
                    fail_after_bind: bool = False, nested=None):
    if fail_before_bind:
        raise RuntimeError("preparation failed")
    bind_turn_execution_snapshot(session_id, _decision(status))
    yield bound_turn_execution_snapshot(session_id)["gate"]["status"]
    if nested is not None:
        async for event in nested():
            yield event
        yield bound_turn_execution_snapshot(session_id)["gate"]["status"]
    if fail_after_bind:
        raise RuntimeError("loop failed")
    yield "done"


async def _drain(generator) -> list:
    return [event async for event in generator]


# A Mac turn's trace (devices/run_trace.py) carries no execution snapshot; the device reports the outcome itself.
DEVICE_CONTEXT = {"source": "device", "job_id": "dj_1", "turn_id": "t-1", "profile": "seat"}


@pytest.mark.asyncio
async def test_binding_is_cleared_after_normal_exit_and_failure() -> None:
    assert await _drain(_fake_run("s-life")) == ["allowed", "done"]
    assert bound_turn_execution_snapshot("s-life") is None
    with pytest.raises(RuntimeError):
        await _drain(_fake_run("s-life", fail_after_bind=True))
    assert bound_turn_execution_snapshot("s-life") is None


@pytest.mark.asyncio
async def test_second_turn_failing_before_bind_never_sees_the_previous_decision() -> None:
    bind_turn_execution_snapshot("s-stale", _decision("denied"))
    observed: list = []

    @scoped_turn_execution_binding
    async def failing_turn(session_id: str):
        observed.append(bound_turn_execution_snapshot(session_id))
        raise RuntimeError("preparation failed")
        yield  # pragma: no cover

    with pytest.raises(RuntimeError):
        await _drain(failing_turn("s-stale"))
    assert observed == [None]
    clear_turn_execution_snapshot("s-stale")


@pytest.mark.asyncio
async def test_binding_is_cleared_on_generator_close_and_cancellation() -> None:
    events = _fake_run("s-close")
    assert await events.__anext__() == "allowed"
    assert bound_turn_execution_snapshot("s-close") is not None
    await events.aclose()
    assert bound_turn_execution_snapshot("s-close") is None

    started = asyncio.Event()
    release = asyncio.Event()

    @scoped_turn_execution_binding
    async def slow_turn(session_id: str):
        bind_turn_execution_snapshot(session_id, _decision("allowed"))
        started.set()
        await release.wait()
        yield "never"

    async def consume() -> list:
        observed = await _drain(slow_turn("s-cancel"))
        return observed

    async def consume_and_report():
        try:
            await consume()
        finally:
            leaked.append(bound_turn_execution_snapshot("s-cancel"))

    leaked: list = []
    task = asyncio.create_task(consume_and_report())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert leaked == [None]


@pytest.mark.asyncio
async def test_nested_different_session_keeps_the_parent_binding() -> None:
    events = await _drain(
        _fake_run("s-parent", nested=lambda: _fake_run("s-child", status="denied"))
    )
    assert events == ["allowed", "denied", "done", "allowed", "done"]
    assert bound_turn_execution_snapshot("s-parent") is None
    assert bound_turn_execution_snapshot("s-child") is None


@pytest.mark.asyncio
async def test_same_session_nesting_restores_the_parent_decision() -> None:
    events = await _drain(
        _fake_run("s-same", nested=lambda: _fake_run("s-same", status="needs_configuration"))
    )
    # After the nested same-session run ends, the parent's decision is back.
    assert events == ["allowed", "needs_configuration", "done", "allowed", "done"]
    assert bound_turn_execution_snapshot("s-same") is None


@pytest.mark.parametrize(
    ("reason", "code", "action"),
    [
        ("step_tool_required", "runtime_stopped_step_tool_required", "complete_configuration"),
        ("step_stalled", "runtime_stopped_step_stalled", "complete_configuration"),
        # The agent's checked reply format refused its final reply.
        ("agent_reply_not_json", "runtime_stopped_agent_reply_not_json", "retry"),
        ("agent_reply_schema_mismatch", "runtime_stopped_agent_reply_schema_mismatch", "retry"),
        ("agent_reply_contract_invalid", "runtime_stopped_agent_reply_contract_invalid", "complete_configuration"),
    ],
)
def test_an_explicit_runtime_stop_reads_stopped_with_its_closed_reason(reason, code, action) -> None:
    summary = _stopped_summary(reason)
    assert summary["state"] == "stopped"
    assert summary["state_reason"]["code"] == code
    assert summary["state_reason"]["source"] == "runtime"
    assert summary["next_action"]["kind"] == action


def test_a_stop_without_a_closed_reason_is_never_recorded_or_read() -> None:
    trace = SimpleNamespace(context_snapshot_json={TURN_EXECUTION_SNAPSHOT_KEY: _snapshot()})
    mark_turn_runtime_stopped(trace, "model_said_so")
    assert RUNTIME_OUTCOME_KEY not in trace.context_snapshot_json[TURN_EXECUTION_SNAPSHOT_KEY]
    forged = {TURN_EXECUTION_SNAPSHOT_KEY: {**_snapshot(), RUNTIME_OUTCOME_KEY: "stopped"}}
    assert runtime_outcome_from_trace(forged, {}) == "unknown"
    foreign = {
        TURN_EXECUTION_SNAPSHOT_KEY: {**_snapshot(), RUNTIME_OUTCOME_KEY: "stopped", "runtime_stop_reason": "x"}
    }
    assert runtime_outcome_from_trace(foreign, {}) == "unknown"


@pytest.mark.asyncio
async def test_the_persisted_stop_answer_carries_the_stop_on_its_own_trace(db) -> None:
    from sqlalchemy import select

    from app.agent.core.assistant_message import persist_traced_assistant_message
    from app.models import TurnTrace

    session_id = "stop-session"
    bind_turn_execution_snapshot(session_id, _snapshot())
    try:
        message = await persist_traced_assistant_message(
            db=db,
            session_id=session_id,
            content="Agent stopped because the step needs a tool.",
            provider="test",
            model="m",
            input_messages=[{"role": "user", "content": "x"}],
            context_snapshot={},
            update_thread_context=False,
            runtime_stop_reason="step_tool_required",
        )
    finally:
        clear_turn_execution_snapshot(session_id)
    trace = (await db.execute(select(TurnTrace).where(TurnTrace.message_id == message.id))).scalar_one()
    assert runtime_outcome_from_trace(trace.context_snapshot_json, trace.raw_output) == "stopped"


@pytest.mark.parametrize(
    ("raw_output", "outcome", "state", "code"),
    [
        ({"status": "", "device_status": "success"}, "finished", "finished_unverified", "runtime_finished"),
        ({"status": "failed", "device_status": "error"}, "failed", "failed", "runtime_failed"),
        ({"status": "blocked", "device_status": ""}, "failed", "failed", "runtime_failed"),
        ({"status": "", "device_status": "stopped"}, "stopped", "cancelled", "runtime_cancelled"),
        ({"status": "", "device_status": ""}, "unknown", "unknown", "runtime_outcome_unknown"),
    ],
)
def test_a_mac_turn_reads_as_the_outcome_its_device_reported(raw_output, outcome, state, code) -> None:
    assert runtime_outcome_from_trace(DEVICE_CONTEXT, raw_output) == outcome
    summary = build_turn_execution_summary(_evidence(context_snapshot=DEVICE_CONTEXT, runtime_outcome=outcome,
                                                     provider="device"))
    assert (summary["state"], summary["state_reason"]["code"]) == (state, code)


def test_a_trace_without_snapshot_that_is_not_a_mac_turn_stays_unknown() -> None:
    assert runtime_outcome_from_trace({"source": "other"}, {"device_status": "success"}) == "unknown"
    assert _summary(None)["state_reason"]["code"] == "missing_snapshot"
