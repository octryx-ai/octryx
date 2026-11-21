"""A phase result that arrives twice is ignored once the run moved on.

The second copy of a Stop hook's result (a replay after reconnect, a retried HTTP call) must not resolve the
decision card the run has moved to with no value, or the run fails ("Node 'decisions' has no exit for 'None'").
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.devices.hub import device_hub
from app.services.devices.job_events import apply_event
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.services.workflow_runs import engine, phase_turns
from app.services.workflow_runs.binding import record_phase_turn
from app.services.workflow_runs.graph import PASSED
from app.services.workflow_runs.states import EVENT_DUPLICATE_RESULT_IGNORED, RUN_RESOLUTION_KEY
from tests.phased_workflow_fixtures import PHASE
from tests.workflow_run_octryx_continuation_support import _confirm, _device_run, _jobs

STORY = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "go", "type": "user_confirmation", "label": "Approve the plan", "config": {"subject": "advance"}},
              {"id": "work", "type": "phase", "label": "Implement", "config": copy.deepcopy(PHASE)},
              {"id": "decisions", "type": "user_confirmation", "label": "Ship or send back",
               "config": {"subject": "decisions"}},
              {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
              {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}],
    "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "go"},
              {"id": "e1", "source_node_id": "go", "target_node_id": "work", "when": "confirmed"},
              {"id": "e2", "source_node_id": "go", "target_node_id": "blocked", "when": "changed"},
              {"id": "e3", "source_node_id": "go", "target_node_id": "blocked", "when": "stopped"},
              {"id": "e4", "source_node_id": "work", "target_node_id": "decisions"},
              {"id": "e5", "source_node_id": "decisions", "target_node_id": "done", "when": "confirmed"},
              {"id": "e7", "source_node_id": "decisions", "target_node_id": "blocked", "when": "stopped"}],
}


@pytest.fixture(autouse=True)
def _hub():
    device_hub.clear()
    yield
    device_hub.clear()


async def _ignored(db, run) -> list[WorkflowRunEvent]:
    return list((await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == EVENT_DUPLICATE_RESULT_IGNORED))).scalars())


async def _at_work(db):
    admin, _device, thread, run = await _device_run(db, definition=STORY)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    assert run.current_node_id == "work"
    return admin, run


@pytest.mark.asyncio
async def test_a_duplicate_phase_result_after_the_run_moved_on_is_ignored(db):
    admin, run = await _at_work(db)
    await phase_turns.complete_phase_turn(db, run, node_id="work", state=PASSED, evidence=None)
    assert (run.status, run.current_node_id) == ("waiting", "decisions")
    await phase_turns.complete_phase_turn(db, run, node_id="work", state=PASSED, evidence=None)  # the same result again
    assert (run.status, run.current_node_id) == ("waiting", "decisions")
    [event] = await _ignored(db, run)
    assert event.node_id == "work" and event.detail["current_node_id"] == "decisions"
    await engine.resolve_current_node(db, run, "confirmed", actor_id=admin.id)
    assert (run.status, run.outcome) == ("completed", "done")


@pytest.mark.asyncio
async def test_a_replayed_stop_report_of_an_earlier_pass_is_ignored(db):
    _admin, run = await _at_work(db)
    marker = {"run_id": run.id, "node_id": "work", "entry": dict(run.node_state or {}).get("entry")}
    analysis = {ROUTING_RESOLUTION_KEY: {RUN_RESOLUTION_KEY: marker}}
    await record_phase_turn(db, request_analysis=analysis, session_id="s1", state=PASSED, results=[], evidence=None)
    assert run.current_node_id == "decisions"
    await record_phase_turn(db, request_analysis=analysis, session_id="s1", state=PASSED, results=[], evidence=None)
    assert (run.status, run.current_node_id) == ("waiting", "decisions")
    [event] = await _ignored(db, run)
    assert event.detail["session_id"] == "s1"
