"""An item's gateway session binds by its job as its own role next to the main one, its Stop reports to its item, and the coordinator's board wake is no phase pass."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import UserDevice, WorkflowRunSession
from app.services.devices.jobs import start_turn
from app.services.workflow_runs.teamwork import WORK_KEY, device_work_state, item_key_of
from tests.teamwork_device_support import (  # noqa: F401
    FOLDER,
    _gateway_session,
    _hub,
    _item_running,
    _run,
    _set_item,
    scheduler,
)


@pytest.mark.asyncio
async def test_an_items_gateway_session_binds_by_its_job_as_its_own_role_next_to_the_main_one(db, scheduler):  # noqa: F811
    from app.services.workflow_runs.octryx.attach import ROLE_OCTRYX, bind_device_session
    from app.services.workflow_runs.octryx.contract import run_contract

    admin, device, thread, run = await _run(db)
    started, job = await _item_running(db, run)
    main_job = await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id),
                                session_id=thread.id, workspace_id=thread.project_id, folder=FOLDER,
                                profile="governed", prompt="main thread")
    main = await _gateway_session(db, admin, thread.project_id, "key-main")
    item = await _gateway_session(db, admin, thread.project_id, "key-api")
    assert await bind_device_session(db, gateway_session=main, user=admin, workspace_id=thread.project_id,
                                     run_id=run.id, job_id=main_job.id) is not None
    assert await bind_device_session(db, gateway_session=item, user=admin, workspace_id=thread.project_id,
                                     run_id=run.id, job_id=job.id) is not None
    roles = {row.session_id: (row.role, row.active) for row in (await db.execute(select(WorkflowRunSession).where(
        WorkflowRunSession.run_id == run.id, WorkflowRunSession.session_id.in_([main.id, item.id])))).scalars()}
    assert roles == {main.id: (ROLE_OCTRYX, True), item.id: ("octryx:api", True)}  # both bindings stay
    assert item_key_of(item) == "api" and item_key_of(main) is None
    assert run.context[WORK_KEY]["items"]["api"]["agent_hash"]  # the item's board identity

    # Its contract is its item's phase: its paths, its work, the team; never the main folder's git work.
    run.context = {**run.context, device_work_state.GIT_KEY: {**run.context[device_work_state.GIT_KEY], "sent": {
        "seq": 2, "ops": [{"op": "merge", "key": "ui", "branch": "x"}], "node_id": "work", "entry": 2}}}
    contract = await run_contract(db, run, session=item)
    assert contract["phase"]["path_rules"]["write"] == ["server/**"] and "work_git" not in contract
    assert contract["phase"]["work_item"]["instructions"] == "Build GET /search"
    assert contract["phase"]["work_item"]["shared_contract"] == "GET /search"
    assert {entry["id"] for entry in contract["phase"]["work_item"]["team"]["items"]} == {"api", "ui"}
    assert "work_git" in await run_contract(db, run, session=main)

    # Its facts are its worktree's: the run's device change stays the main folder's.
    from app.services.workflow_runs.octryx.facts import record_facts

    facts = {"node_id": "work", "entry": 2, "change": {"base": "a" * 40, "patch": "diff --git a/x b/x\n"}}
    assert record_facts(run, facts, session=item) is False and "device_change" not in run.context
    assert record_facts(run, facts, session=main) is True and run.context["device_change"]["patch"]


@pytest.mark.asyncio
async def test_an_items_stop_reports_to_its_item(db, scheduler, monkeypatch):  # noqa: F811
    from app.services.workflow_runs import binding
    from app.services.workflow_runs.octryx.attach import bind_device_session
    from app.services.workflow_runs.octryx.stop import run_stop

    admin, device, thread, run = await _run(db)
    _started, job = await _item_running(db, run)
    item = await _gateway_session(db, admin, thread.project_id, "key-api")
    await bind_device_session(db, gateway_session=item, user=admin, workspace_id=thread.project_id, run_id=run.id,
                              job_id=job.id)
    reported = []

    async def record_phase_turn(db, *, request_analysis, session_id, state, results, evidence):
        reported.append(request_analysis)

    monkeypatch.setattr(binding, "record_phase_turn", record_phase_turn)
    # A Stop whose checks fail is no end of the item: it blocks, the agent goes on.
    answer = await run_stop(db, session=item, hook_input={"hook_event_name": "Stop"}, tool_calls=[],
                            test_prefixes=())
    assert answer["state"] == "blocked" and reported == []
    assert run.context[WORK_KEY]["items"]["api"]["status"] == "running"

    from app.services.workflow_runs.octryx import stop as stop_module

    monkeypatch.setattr(stop_module, "evaluate_checks", lambda checks, evidence: [])
    answer = await run_stop(db, session=item, hook_input={"hook_event_name": "Stop"}, tool_calls=[],
                            test_prefixes=())
    assert answer["state"] == "blocked" and "submit_phase_result" in answer["detail"] and reported == []
    _set_item(run, "api", result={"value": "done", "summary": "built"})  # its submit_phase_result
    await run_stop(db, session=item, hook_input={"hook_event_name": "Stop"}, tool_calls=[], test_prefixes=())
    [analysis] = reported
    marker = next(iter(next(iter(analysis.values())).values()))  # {routing resolution: {run resolution: marker}}
    assert marker["item"] == "api" and marker["node_id"] == "work"


@pytest.mark.asyncio
async def test_the_coordinators_board_wake_is_no_phase_pass(db, scheduler, monkeypatch):  # noqa: F811
    """The engine wakes the coordinator on the main thread while the items run: its session works under the plan
    phase and its Stop never reports a pass of the ``parallel_work`` node."""
    from app.services.workflow_runs import binding
    from app.services.workflow_runs.octryx.attach import ROLE_OCTRYX, bind_device_session
    from app.services.workflow_runs.octryx.stop import REASON_COORDINATOR_WAKE, run_stop

    admin, device, thread, run = await _run(db)
    wake_job = await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id),
                                session_id=thread.id, workspace_id=thread.project_id, folder=FOLDER,
                                profile="governed", prompt="the team wrote to you")
    run.context = {**run.context, "coordinator_wake": {"pending": [], "woken": ["m1"], "job_id": wake_job.id}}
    gateway = await _gateway_session(db, admin, thread.project_id, "key-coordinator")
    await bind_device_session(db, gateway_session=gateway, user=admin, workspace_id=thread.project_id,
                              run_id=run.id, job_id=wake_job.id)
    role = (await db.execute(select(WorkflowRunSession.role).where(
        WorkflowRunSession.session_id == gateway.id))).scalar_one()
    assert role == ROLE_OCTRYX and item_key_of(gateway) is None
    reported = []

    async def record_phase_turn(db, **kwargs):
        reported.append(kwargs)

    monkeypatch.setattr(binding, "record_phase_turn", record_phase_turn)
    answer = await run_stop(db, session=gateway, hook_input={"hook_event_name": "Stop"}, tool_calls=[],
                            test_prefixes=())
    assert answer["reason"] == REASON_COORDINATOR_WAKE and answer["workflow_run"]["phase"]["coordinator_wake"]
    assert reported == []
