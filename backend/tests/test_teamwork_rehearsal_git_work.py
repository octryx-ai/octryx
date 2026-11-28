"""The run's board with the device grant, merge conflicts resolved on retry, git work ends, side-by-side stall records and the main folder clean-up."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.models import DeviceJob
from app.models.runtime.secure_work import WorkItem
from app.services.devices.job_events import apply_event
from app.services.workflow_runs.teamwork import device_items, device_work_state
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
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

pytestmark = [pytest.mark.usefixtures("admitted", "_hub", "agent_checks_pass"), pytest.mark.usefixtures("scripted_pool")]


async def _device_grant(db, admin, scopes=None) -> str:
    from app.models.security.oauth_provider import OAuthGrant
    from app.services.devices.contract import DEVICE_JOB_SCOPES

    grant = OAuthGrant(user_id=admin.id, client_id="octryx-device", scopes=sorted(scopes or DEVICE_JOB_SCOPES),
                       project_ids=None)
    db.add(grant)
    await db.flush()
    return grant.id


async def _registered(db, admin, gateway) -> str:
    from app.models import AgentPresence
    from app.services.agent_gateway.contract import SESSION_KEY_METADATA
    from app.time_utils import utc_now

    key = gateway.metadata_[SESSION_KEY_METADATA]
    db.add(AgentPresence(id=str(uuid.uuid4()), session_key=key, session_id=gateway.id, user_id=admin.id,
                         project_id=gateway.project_id, profile="seat", client="octryx-claude", state="active",
                         device_key="device-rehearsal", registered_at=utc_now(), last_seen_at=utc_now()))
    await db.flush()
    return key


async def _board(db, admin, grant_id: str, key: str, tool: str, arguments: dict, scopes=None) -> dict:
    from app.services.devices.contract import DEVICE_JOB_SCOPES
    from app.services.mcp_agent_board_tools import board_call

    return await board_call(db, headers={"x-octryx-session": key}, user_id=admin.id, grant_id=grant_id,
                            scopes=tuple(scopes or DEVICE_JOB_SCOPES), client_name="claude-code", tool_name=tool,
                            arguments=arguments)


@_DEVICE_RUN
@pytest.mark.asyncio
async def test_items_and_the_coordinator_use_their_runs_board_with_the_device_grant(db, tmp_path):
    from fastapi import HTTPException

    from app.services.agent_gateway.presence import session_key_hash
    from app.services.workflow_runs.octryx.attach import bind_device_session

    admin, project, device, thread, run, main, base = await _story_run(db, tmp_path)
    coordinator = await coordinator_plans(db, admin, project, thread, run, plan=PLAN[:2])
    await Device(db, admin, project, run, main, base).git_work()
    core = _items(run)["core-domain"]
    job = await db.get(DeviceJob, core["job_id"])
    gateway = await _gateway_session(db, admin, project.id, str(uuid.uuid4()))
    assert await bind_device_session(db, gateway_session=gateway, user=admin, workspace_id=project.id,
                                     run_id=run.id, job_id=job.id)
    item_key, coordinator_key = await _registered(db, admin, gateway), await _registered(db, admin, coordinator)
    grant = await _device_grant(db, admin)
    story = await db.get(WorkItem, run.work_item_id)

    asked = await _board(db, admin, grant, item_key, "board_post", {
        "kind": "question", "body": "Which field name does the search API return?", "work_item_id": "OCX-91",
        "to_agent_hash": session_key_hash(coordinator_key)})
    message = asked["message"]
    assert message["project_id"] == project.id and message["work_item"]["id"] == story.id
    assert message["author"]["agent_hash"] == session_key_hash(item_key)

    inbox = await _board(db, admin, grant, coordinator_key, "board_read", {"addressed_to_me": True})
    assert [entry["id"] for entry in inbox["items"]] == [message["id"]]
    answered = await _board(db, admin, grant, coordinator_key, "board_post", {
        "kind": "answer", "body": "results[].title", "reply_to": message["id"]})
    acked = await _board(db, admin, grant, coordinator_key, "board_ack", {"message_ids": [message["id"]]})
    assert acked["acked"] == 1
    thread_view = await _board(db, admin, grant, item_key, "board_read", {})
    assert answered["message"]["id"] in [entry["id"] for entry in thread_view["items"]]

    other = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-77", title="Other",
                     project_id=project.id, work_state="intake")
    db.add(other)
    await db.flush()
    for arguments, scopes, key in (
            ({"kind": "info", "body": "x", "work_item_id": other.id}, None, item_key),
            ({"kind": "info", "body": "x"}, ("workflow:read",), item_key),
            ({"kind": "info", "body": "x"}, None, str(uuid.uuid4()))):
        with pytest.raises(HTTPException) as refused:
            await _board(db, admin, grant, key, "board_post", arguments, scopes=scopes)
        assert refused.value.status_code == 403
    with pytest.raises(HTTPException):
        await _board(db, admin, grant, item_key, "board_read", {"work_item_id": other.id})


@_DEVICE_RUN
@pytest.mark.asyncio
async def test_a_merge_conflict_is_resolved_on_the_items_retry_with_the_storys_work_merged_in(
        db, tmp_path, monkeypatch):
    admin, project, device, thread, run, main, base = await _story_run(db, tmp_path)
    monkeypatch.setitem(FILES, "frontend-shell", FILES["core-domain"])
    await coordinator_plans(db, admin, project, thread, run, plan=PLAN[:2])
    device_side = Device(db, admin, project, run, main, base)
    await device_side.git_work()
    await device_side.item_turn("core-domain")
    await device_side.git_work()
    await device_side.item_turn("frontend-shell")
    await device_side.git_work()
    state = run.context[device_work_state.GIT_KEY]
    assert "frontend-shell" not in state["branched"] and state["resync"] == ["frontend-shell"]

    assert run.current_node_id == "plan"
    await coordinator_plans(db, admin, project, thread, run, plan=PLAN[:2])
    assert run.current_node_id == "work"
    [op] = run.context[device_work_state.GIT_KEY]["sent"]["ops"]
    assert (op["key"], op.get("sync")) == ("frontend-shell", True)
    await device_side.git_work()
    shell = _items(run)["frontend-shell"]
    assert shell["status"] == "running" and shell["iteration"] == 2
    worktree = Path(shell["path"])
    assert "<<<<<<<" in (worktree / FILES["core-domain"]).read_text()
    job = await db.get(DeviceJob, shell["job_id"])
    assert FILES["core-domain"] in job.turn_prompt and "conflict markers" in job.turn_prompt

    await device_side.item_turn("frontend-shell")
    if run.context[device_work_state.GIT_KEY].get("sent"):
        await device_side.git_work()
    assert _items(run)["frontend-shell"]["status"] == "merged"
    assert (main / FILES["core-domain"]).read_text() == "# frontend-shell\n"
    assert run.current_node_id == "pipeline"


@_DEVICE_RUN
@pytest.mark.asyncio
async def test_the_git_works_end_is_matched_by_its_turn_and_never_swallows_the_coordinators(db, tmp_path):
    from app.models import UserDevice
    from app.services.devices.jobs import start_turn
    from app.services.workflow_runs.engine import restart_at

    admin, project, device, thread, run, main, base = await _story_run(db, tmp_path)
    await coordinator_plans(db, admin, project, thread, run, plan=PLAN[:2])
    sent = dict(run.context[device_work_state.GIT_KEY]["sent"])
    git_job = await db.get(DeviceJob, sent["job_id"])
    assert sent["turn_id"] == git_job.turn_id and device_items._own_job(run, thread, git_job)
    await apply_event(db, git_job, "job_accepted", {"turn_id": git_job.turn_id}, limits={})

    await restart_at(db, run, "plan", actor_id=admin.id)
    state = run.context[device_work_state.GIT_KEY]
    assert state["sent"] is None and [op["key"] for op in state["ops"]] == ["core-domain", "frontend-shell"]
    assert git_job.stop_state == "pending"
    assert device_items._own_job(run, thread, git_job)
    await apply_event(db, git_job, "turn_finished", {"turn_id": git_job.turn_id, "status": "cancelled"}, limits={})
    coordinator = await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id),
                                   session_id=thread.id, workspace_id=project.id, folder=str(main),
                                   profile="governed", prompt="the coordinator's next turn")
    assert coordinator.id == git_job.id
    assert not device_items._own_job(run, thread, coordinator)


@_DEVICE_RUN
@pytest.mark.asyncio
async def test_items_stopping_side_by_side_each_keep_their_own_stall_record(db, tmp_path):
    from app.services.workflow_runs.octryx.attach import bind_device_session
    from app.services.workflow_runs.octryx.stop import run_stop

    admin, project, device, thread, run, main, base = await _story_run(db, tmp_path)
    await coordinator_plans(db, admin, project, thread, run, plan=PLAN[:2])
    await Device(db, admin, project, run, main, base).git_work()
    gateways = {}
    for key in ("core-domain", "frontend-shell"):
        job = await db.get(DeviceJob, _items(run)[key]["job_id"])
        gateways[key] = await _gateway_session(db, admin, project.id, f"key-{key}")
        await bind_device_session(db, gateway_session=gateways[key], user=admin, workspace_id=project.id,
                                  run_id=run.id, job_id=job.id)
        await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})

    async def stop(key):
        return await run_stop(db, session=gateways[key], hook_input={"hook_event_name": "Stop"}, tool_calls=[],
                              test_prefixes=())

    assert (await stop("core-domain"))["state"] == "blocked"
    assert (await stop("frontend-shell"))["state"] == "blocked"
    assert (await stop("core-domain"))["state"] != "blocked"
    assert _items(run)["core-domain"]["status"] == "failed"
    assert "stopped twice" in _items(run)["core-domain"]["reason"]
    assert _items(run)["frontend-shell"]["status"] == "running"


@_DEVICE_RUN
@pytest.mark.asyncio
async def test_the_main_folder_is_cleaned_of_an_earlier_run_only_before_the_runs_own_git_work(db, tmp_path):
    from app.services.workflow_runs.octryx.contract import run_contract

    admin, project, device, thread, run, main, base = await _story_run(db, tmp_path)
    gateway = await _gateway_session(db, admin, project.id, "key-main")
    contract = await run_contract(db, run, session=gateway)
    assert contract["preparation"]["run_commits_on_device"] is False
    await coordinator_plans(db, admin, project, thread, run, plan=PLAN[:1])
    device_side = Device(db, admin, project, run, main, base)
    await device_side.git_work()
    await device_side.item_turn("core-domain")
    await device_side.git_work()
    merged = _git(main, "rev-parse", "HEAD")
    assert merged != base

    contract = await run_contract(db, run, session=gateway)
    assert contract["preparation"]["run_commits_on_device"] is True
    report = device_side.prep.prepare(contract, main, runtime="device")
    assert "earlier_run_cleaned" not in report and _git(main, "rev-parse", "HEAD") == merged
