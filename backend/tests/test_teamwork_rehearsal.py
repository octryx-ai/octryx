"""Team delivery v2 on a device, end to end.

The real seed, the real scheduler and device executor, the real device job chain (``apply_event`` → continuation →
``job_ended``), the gateway's bindings, contracts and Stop hook, and the launcher's own git and preparation code in a
real repository: the coordinator's plan, four items (three side by side, one after them; two with long keys),
each item's worktree prepared on its own branch, its result, its merge back into the
story's folder, the run's change, and the pipeline after the merge.

Two failure modes, each pinned:

- ``octryx:frontend-shell`` (21 characters) must fit ``WorkflowRunSession.role``, else registration fails with 500
  → ``registration_refused``;
- an item must not be marked failed at its first Stop with failing checks while its agent goes on, else the run goes
  back to the plan under it, its session gets the plan phase's contract and Stop, and its turn end pauses the run.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import DeviceJob, WorkflowRunSession
from app.services.devices.job_events import apply_event
from app.services.devices.job_state import ACTIVE_STATUSES
from app.services.workflow_runs.teamwork import WORK_KEY, device_work_state, item_order, scheduler
from tests.teamwork_device_support import _gateway_session, _hub, admitted  # noqa: F401 - fixtures
from tests.teamwork_rehearsal_support import (  # noqa: F401
    _DEVICE_RUN,
    FILES,
    PLAN,
    Device,
    _git,
    _items,
    _story_run,
    agent_checks_pass,
    coordinator_plans,
)
from tests.test_team_delivery import actions  # noqa: F401 - ``actions`` is a fixture

pytestmark = pytest.mark.usefixtures("admitted", "_hub", "agent_checks_pass")


@_DEVICE_RUN
@pytest.mark.asyncio
async def test_team_delivery_v2_runs_four_items_on_a_device_through_their_merges_to_the_pipeline(
        db, tmp_path):
    admin, project, device, thread, run, main, base = await _story_run(db, tmp_path)
    await coordinator_plans(db, admin, project, thread, run)
    assert run.current_node_id == "work"  # the readiness of an epic's story is accepted for the product owner
    device_side = Device(db, admin, project, run, main, base)

    # The three independent items are branched on the main thread first, then start side by side.
    await device_side.git_work()
    started = {key: item["status"] for key, item in _items(run).items()}
    assert started == {"core-domain": "running", "frontend-shell": "running", "frontend-components": "running",
                       "flow-wiring": "pending"}
    roles = (await db.execute(select(WorkflowRunSession.role).where(WorkflowRunSession.run_id == run.id))).scalars()
    limit = WorkflowRunSession.role.type.length
    assert all(len(role) <= limit for role in roles)

    for key in ("core-domain", "frontend-shell"):
        await device_side.item_turn(key)
        await device_side.git_work()  # its merge (and, once both are merged, the dependent item's worktree)
    assert _items(run)["core-domain"]["status"] == "merged" and _items(run)["frontend-shell"]["status"] == "merged"
    if run.context[device_work_state.GIT_KEY].get("sent"):
        await device_side.git_work()
    assert _items(run)["flow-wiring"]["status"] == "running"  # it waited for both of its dependencies

    for key in ("frontend-components", "flow-wiring"):
        await device_side.item_turn(key)
        if run.context[device_work_state.GIT_KEY].get("sent"):
            await device_side.git_work()

    assert {key: item["status"] for key, item in _items(run).items()} == dict.fromkeys(FILES, "merged")
    assert run.current_node_id == "pipeline" and run.status == "running"  # the CI pipeline after the merges
    for key, name in FILES.items():
        assert (main / name).read_text() == f"# {key}\n"  # every item's work is in the story's folder
        assert f"b/{name}" in run.context["device_change"]["patch"]  # and in the change the review sees
    assert not (main / ".octryx-items" / "core-domain").exists()  # merged worktrees are removed
    assert _git(main, "status", "--porcelain") == ""


@_DEVICE_RUN
@pytest.mark.asyncio
async def test_an_items_session_never_follows_the_runs_phase_and_its_end_never_pauses_the_run(
        db, tmp_path):
    from app.services.workflow_runs.octryx.attach import bind_device_session
    from app.services.workflow_runs.octryx.contract import run_contract
    from app.services.workflow_runs.octryx.stop import REASON_ITEM_NOT_RUNNING, run_stop

    admin, project, device, thread, run, main, base = await _story_run(db, tmp_path)
    await coordinator_plans(db, admin, project, thread, run, plan=PLAN[:2])
    await Device(db, admin, project, run, main, base).git_work()
    core = _items(run)["core-domain"]
    job = await db.get(DeviceJob, core["job_id"])
    gateway = await _gateway_session(db, admin, project.id, "key-core")
    await bind_device_session(db, gateway_session=gateway, user=admin, workspace_id=project.id, run_id=run.id,
                              job_id=job.id)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})

    # Its Stop with failing checks: blocked, the item keeps running ("its checks did not pass", attempts 1).
    answer = await run_stop(db, session=gateway, hook_input={"hook_event_name": "Stop"}, tool_calls=[],
                            test_prefixes=())
    assert answer["state"] == "blocked" and _items(run)["core-domain"]["status"] == "running"

    # The other item fails; the node waits for the running one instead of going back to the plan under it.
    for _ in range(item_order.MAX_START_REFUSALS):
        shell = _items(run)["frontend-shell"]
        if shell["status"] == "pending":
            scheduler_items = run.context[WORK_KEY]
            run.context = {**run.context, WORK_KEY: {**scheduler_items, "items": {
                **scheduler_items["items"], "frontend-shell": {**shell, "retry_at": "2000-01-01T00:00:00"}}}}
            await scheduler.advance(db, run)
            shell = _items(run)["frontend-shell"]
        shell_job = await db.get(DeviceJob, shell["job_id"])
        await apply_event(db, shell_job, "job_rejected", {"turn_id": shell_job.turn_id,
                                                          "reason": "registration_refused"}, limits={})
    assert _items(run)["frontend-shell"]["status"] == "failed"
    assert run.current_node_id == "work" and _items(run)["core-domain"]["status"] == "running"

    # A person restarts the run at the plan: the running item stops and waits for the next pass, with its session.
    from app.services.workflow_runs.engine import restart_at

    await restart_at(db, run, "plan", actor_id=admin.id)
    assert run.current_node_id == "plan"
    assert (_items(run)["core-domain"]["status"], _items(run)["core-domain"]["session_id"]) == (
        "pending", core["session_id"])
    job = await db.get(DeviceJob, core["job_id"])
    assert job.stop_state == "pending" or job.status not in ACTIVE_STATUSES

    # Its session now has nothing to do: no phase in its contract (never the plan's), its Stop ends it ...
    contract = await run_contract(db, run, session=gateway)
    assert contract["phase"] is None and "core-domain" in contract["item_idle"]
    answer = await run_stop(db, session=gateway, hook_input={"hook_event_name": "Stop"}, tool_calls=[],
                            test_prefixes=())
    assert answer["state"] == "not_applicable" and answer["reason"] == REASON_ITEM_NOT_RUNNING
    # ... and its turn's end is the item's, never the plan phase's: the run does not pause.
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success",
                                                 "result_text": "I'm not the coordinator."}, limits={})
    assert run.status == "running" and run.pause_reason is None


@_DEVICE_RUN
@pytest.mark.asyncio
async def test_an_items_agent_submits_its_result_over_mcp_and_only_its_own_session_may(db, tmp_path):
    """An item agent's submit_phase_result must not be refused ``outside_phase_tools`` ("the run is still on node
    `work` with phase null") while its Stop asks for it, until the loop limit pauses the run. The MCP tools read the
    run's contract, not the calling session's: an item's session works under its item's phase."""
    from app.services.mcp_workflow_run_tools import PHASE_OUTPUT_MCP_HANDLERS, mcp_workflow_run_status
    from app.services.workflow_runs.octryx.attach import bind_device_session
    from app.services.workflow_runs.octryx.stop import run_stop

    admin, project, device, thread, run, main, base = await _story_run(db, tmp_path)
    coordinator = await coordinator_plans(db, admin, project, thread, run, plan=PLAN[:2])
    device_side = Device(db, admin, project, run, main, base)
    await device_side.git_work()
    core = _items(run)["core-domain"]
    job = await db.get(DeviceJob, core["job_id"])
    gateway = await _gateway_session(db, admin, project.id, str(uuid.uuid4()))
    assert await bind_device_session(db, gateway_session=gateway, user=admin, workspace_id=project.id,
                                     run_id=run.id, job_id=job.id)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})

    # The main thread's session at the parallel node has no phase: the result tool stays refused there.
    status = await mcp_workflow_run_status(db, caller=device_side.caller(coordinator), user=admin,
                                           workspace_id=project.id, arguments={})
    assert status["workflow_run"]["phase"] is None
    refused = await PHASE_OUTPUT_MCP_HANDLERS["submit_phase_result"](
        db, caller=device_side.caller(coordinator), user=admin, workspace_id=project.id,
        arguments={"value": "done"})
    assert refused["reason"] == "outside_phase_tools"

    # The item's own agent: "blocked" is accepted on its item, its Stop passes, the coordinator gets it back.
    recorded = await device_side.agent_submits(gateway, "core-domain", value="blocked")
    assert (recorded["state"], recorded["item"], recorded["value"]) == ("recorded", "core-domain", "blocked")
    assert _items(run)["core-domain"]["result"]["value"] == "blocked"
    answer = await run_stop(db, session=gateway, hook_input={"hook_event_name": "Stop"}, tool_calls=[],
                            test_prefixes=())
    assert answer["state"] == "passed", answer
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success",
                                                 "result_text": "Blocked: needs a shared type."}, limits={})
    assert _items(run)["core-domain"]["status"] == "blocked" and run.status == "running"

    # Once its item no longer runs, its session has no phase and the result tool is refused again.
    again = await PHASE_OUTPUT_MCP_HANDLERS["submit_phase_result"](
        db, caller=device_side.caller(gateway), user=admin, workspace_id=project.id, arguments={"value": "done"})
    assert again["reason"] == "outside_phase_tools"
