"""A size class's rounds per loop and its escalation, on a synthetic workflow.

Without classes, loops can run to their limits for many hours and every limit pauses the run for a
person. A class gives a loop fewer rounds (one number, or per loop edge with "*"); when they are used up the run
escalates along escalate_to and goes on by itself; a class without escalate_to pauses there, and a person's "more
rounds" then count from the pause. The class names and numbers here are the test's own.
"""

from __future__ import annotations

import pytest

from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.pause import continue_run
from app.services.workflow_runs.records import start_run
from app.services.workflow_runs.run_sessions import new_bound_session
from tests.phased_workflow_fixtures import admin_user, phase_turn, phased_definition, publish_phased, run_workspace


async def _run_with(db, size_classes: dict):
    admin = await admin_user(db)
    definition = {**phased_definition(max_iterations=4), "size_classes": size_classes}
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition), project_id=workspace_id)
    return admin, run, await new_bound_session(db, run, admin)


async def _fail_until_paused(db, run, session, *, limit: int = 12) -> int:
    for turn in range(1, limit):
        resolution = await run_turn_resolution(db, session, user_message="Again.")
        await phase_turn(db, session.id, resolution, ["knowledge_search"])  # the gate fails every time
        if run.status == "paused":
            return turn
    raise AssertionError("the run never paused")


@pytest.mark.asyncio
async def test_a_class_out_of_rounds_escalates_and_the_next_class_counts_its_own(db):
    _admin, run, session = await _run_with(db, {
        "default": "tiny", "rules": [],
        "classes": {"tiny": {"max_rounds": 1, "escalate_to": "mid"},
                    "mid": {"max_rounds": {"rework": 1, "*": 3}, "escalate_to": "big"},
                    "big": {}}})
    # tiny: 1 round; mid: 1 round of its own; big: the edge's own 4, counting the round mid used; then the pause.
    assert await _fail_until_paused(db, run, session) == 6 and run.pause_reason == "loop_limit"
    assert [(item["from"], item["to"]) for item in run.context["size_class"]["escalations"]] == [
        ("tiny", "mid"), ("mid", "big")]
    assert run.node_state["pause"]["limit"] == 4


@pytest.mark.asyncio
async def test_a_class_without_escalation_pauses_at_its_rounds_and_a_persons_rounds_count_from_there(db):
    admin, run, session = await _run_with(db, {"default": "solo", "rules": [],
                                               "classes": {"solo": {"max_rounds": 2}}})
    assert await _fail_until_paused(db, run, session) == 3
    assert run.node_state["pause"]["limit"] == 2 and run.loop_counters["rework"]["limit"] == 2
    await continue_run(db, run, user=admin, k=1, is_admin=True)
    # The continue takes the waiting loop edge at once (the one more round); its failure pauses again at 3, not 2.
    assert run.status == "running" and run.loop_counters["rework"]["used"] == 3
    assert await _fail_until_paused(db, run, session) == 1
    assert run.node_state["pause"]["limit"] == 3


@pytest.mark.asyncio
async def test_a_workflow_without_classes_keeps_its_edge_limit(db):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition(max_iterations=4)),
                          project_id=workspace_id)
    assert await _fail_until_paused(db, run, await new_bound_session(db, run, admin)) == 5
    assert "size_class" not in run.context
