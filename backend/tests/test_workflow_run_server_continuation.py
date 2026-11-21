"""A Server run starts its next phase's turn by itself (autonomy B/E).

Contract: entering a phase of a run whose explicit target is the Server marks the pass ``pending``; the platform
then sends the phase prompt on the run's main thread as the requester, once (claimed ``started`` first), and never
while the thread's turn is still running. A failed platform turn or a refused start pauses the run
``runtime_failed``. Runs without an explicit Server target (or on a device) are untouched.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.session.turn_refusals import TurnRefusal, TurnRefusalState
from app.services.workflow_runs import server_continuation as sc
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.devices.device_support import enable_device_runs
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.workflow_run_octryx_continuation_support import DEFINITION, _confirm


class _Shared:
    def __init__(self, db) -> None:
        self._db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *_exc) -> None:
        return None


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []
    answer: dict = {"value": []}

    async def fake_send(db, **kwargs):
        calls.append(kwargs)
        return answer["value"]

    monkeypatch.setattr("app.services.session.message_dispatch.send_session_message", fake_send)
    monkeypatch.setattr(sc, "schedule_continuation", lambda *a, **k: None)
    return calls, answer


async def _server_run(db, *, target: dict | None = {"kind": "server"}):  # noqa: B006 - read only
    project = await enable_device_runs(db)
    admin = await admin_user(db)
    thread = await new_chat_session(db, admin, project.id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, DEFINITION), project_id=project.id,
                          session=thread, runtime_target=target)
    return admin, thread, run


@pytest.mark.asyncio
async def test_a_server_run_starts_the_phase_turn_once_as_the_requester(db, sent):
    calls, _answer = sent
    admin, thread, run = await _server_run(db)
    await _confirm(db, run, admin)
    assert run.current_node_id == "work" and run.context[sc.CONTEXT_KEY]["state"] == "pending"

    await sc.start_pending_turn(thread.id, session_factory=_Shared(db))
    assert len(calls) == 1 and calls[0]["user_id"] == admin.id and calls[0]["session_id"] == thread.id
    assert "phase 'Work'" in calls[0]["content"]
    assert run.context[sc.CONTEXT_KEY]["state"] == "started"
    [started] = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == sc.EVENT_STARTED))).scalars()
    assert started.node_id == "work"

    await sc.start_pending_turn(thread.id, session_factory=_Shared(db))
    assert len(calls) == 1  # the pass is claimed: no second platform turn


@pytest.mark.asyncio
async def test_no_turn_while_the_thread_is_busy_and_none_without_a_server_target(db, sent):
    calls, _answer = sent
    admin, thread, run = await _server_run(db)
    await _confirm(db, run, admin)
    thread.status = "running"
    await sc.start_pending_turn(thread.id, session_factory=_Shared(db))
    assert calls == [] and run.context[sc.CONTEXT_KEY]["state"] == "pending"

    admin, thread, run = await _server_run(db, target=None)
    await _confirm(db, run, admin)
    assert sc.CONTEXT_KEY not in run.context


@pytest.mark.asyncio
async def test_a_failed_platform_turn_and_a_refused_start_pause_the_run(db, sent):
    calls, answer = sent
    admin, thread, run = await _server_run(db)
    await _confirm(db, run, admin)
    await sc.start_pending_turn(thread.id, session_factory=_Shared(db))
    await sc.server_turn_ended(thread.id, failed=True, session_factory=_Shared(db))
    assert (run.status, run.pause_reason) == ("paused", "turn_failed")
    assert run.node_state["pause"]["code"] == "server_turn_failed"

    admin, thread, run = await _server_run(db)
    await _confirm(db, run, admin)
    answer["value"] = TurnRefusal(state=TurnRefusalState.RUNTIME_NOT_ALLOWED, detail="no runtime")
    await sc.start_pending_turn(thread.id, session_factory=_Shared(db))
    assert (run.status, run.pause_reason) == ("paused", "turn_failed")
    assert run.node_state["pause"]["code"] == "server_turn_refused_runtime_not_allowed"
