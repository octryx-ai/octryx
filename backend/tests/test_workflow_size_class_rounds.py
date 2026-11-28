"""A size class's rounds per loop and its escalation, on a synthetic workflow."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.pause import continue_run
from app.services.workflow_runs.records import start_run
from app.services.workflow_runs.run_sessions import new_bound_session
from tests.phased_workflow_fixtures import admin_user, phase_turn, phased_definition, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


async def _workspace(db, admin) -> str:
    from app.models import Project
    from app.services.devices.workspace_policy import set_workspace_device_runs

    workspace_id = await run_workspace(db, admin)
    # The check-attempt bound stays out of the way: these tests are about the size classes' rounds.
    await set_workspace_device_runs(db, project=await db.get(Project, workspace_id), patch={"check_attempts": 10},
                                    actor_id=admin.id)
    return workspace_id


async def _run_with(db, size_classes: dict):
    admin = await admin_user(db)
    definition = {**phased_definition(max_iterations=4), "size_classes": size_classes}
    workspace_id = await _workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition), project_id=workspace_id)
    return admin, run, await new_bound_session(db, run, admin)


async def _fail_until_paused(db, run, session, *, limit: int = 12) -> int:
    for turn in range(1, limit):
        resolution = await run_turn_resolution(db, session, user_message="Again.")
        await phase_turn(db, session.id, resolution, ["knowledge_search"])
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
    assert run.status == "running" and run.loop_counters["rework"]["used"] == 3
    assert await _fail_until_paused(db, run, session) == 1
    assert run.node_state["pause"]["limit"] == 3


@pytest.mark.asyncio
async def test_a_workflow_without_classes_keeps_its_edge_limit(db):
    admin = await admin_user(db)
    workspace_id = await _workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition(max_iterations=4)),
                          project_id=workspace_id)
    assert await _fail_until_paused(db, run, await new_bound_session(db, run, admin)) == 5
    assert "size_class" not in run.context
