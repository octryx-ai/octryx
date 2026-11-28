"""Chat, /api/v1 and channel turns without a device of their own run on a server runner: the synchronous callers get
the answer, Stop ends the runner's turn, and the chat approval confirms a change on the runner."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Project, Session, User, UserDevice
from app.services.devices import agent_runtime
from app.services.devices.agent_runtime import POOL_TARGET, chat_target_for
from app.services.devices.hub import device_hub
from app.services.devices.job_events import apply_event
from tests.devices.test_runner_pool import Connected, _enroll, _runners_on  # noqa: F401


@pytest.fixture
def pool():
    return POOL_TARGET  # no switch: the pool is the only server runtime


async def _runner(client, db):
    runner = await db.get(UserDevice, (await _enroll(client, db)).json()["device"]["id"])
    device_hub._connections[runner.id] = Connected(runner.id)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    return runner, project


def _answers(db, text: str, monkeypatch):
    # The runner answers while the caller waits: the turn finishes on the next poll.
    async def finish(_seconds):
        job = (await db.execute(select(DeviceJob).order_by(DeviceJob.created_at.desc()).limit(1))).scalar_one()
        await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success",
                                                      "result_text": text}, limits={})
        await db.commit()

    monkeypatch.setattr(agent_runtime.asyncio, "sleep", finish)


@pytest.mark.asyncio
async def test_a_chat_message_without_a_target_starts_a_runner_turn(client, db, auth_headers, pool):
    runner, project = await _runner(client, db)
    response = await client.post("/chat/api/send", headers=auth_headers, json={
        "prompt": "Hello", "project_id": project.id, "runtime_target_id": "some-server-model"})
    assert response.status_code == 200, response.text
    job = (await db.execute(select(DeviceJob))).scalar_one()
    assert job.device_id == runner.id and job.workspace_id == project.id


@pytest.mark.asyncio
async def test_an_api_session_message_waits_for_the_runners_answer(client, db, auth_headers, auth_user, pool,
                                                                    monkeypatch):
    _runner_device, project = await _runner(client, db)
    thread = Session(user_id=auth_user.id, project_id=project.id, agent_type="diagnosis", metadata_={})
    db.add(thread)
    await db.commit()
    _answers(db, "Hi from the runner.", monkeypatch)

    response = await client.post(f"/api/v1/sessions/{thread.id}/messages", headers=auth_headers,
                                 json={"content": "Hello"})
    assert response.status_code == 200, response.text
    assert [(item["role"], item["content"]) for item in response.json()] == [
        ("user", "Hello"), ("assistant", "Hi from the runner.")]


@pytest.mark.asyncio
async def test_a_channel_turn_replies_with_the_runners_answer(client, db, auth_user, pool, monkeypatch):
    from app.services.channel_router_runtime.message_turns import InboundMessage
    from app.services.channel_router_runtime.service import ChannelMessageRouter

    _runner_device, project = await _runner(client, db)
    thread = Session(user_id=auth_user.id, project_id=project.id, agent_type="diagnosis", origin="channel",
                     metadata_={})
    db.add(thread)
    await db.commit()
    _answers(db, "Done.", monkeypatch)
    inbound = InboundMessage("ch-1", "teams", "Teams", project.id, "sender-1", "Status?", "personal", "conv-1",
                             "teams:ch-1:sender-1")

    reply = await ChannelMessageRouter.__new__(ChannelMessageRouter)._run_turn(
        db, inbound, session_id=thread.id, user_id=auth_user.id)
    assert reply == ["Done."]
    assert (await db.get(Session, thread.id)).metadata_["channel"] == "teams"


@pytest.mark.asyncio
async def test_the_chats_stop_ends_the_runners_turn(client, db, auth_headers, auth_user, pool):
    _runner_device, project = await _runner(client, db)
    await client.post("/chat/api/send", headers=auth_headers, json={"prompt": "Long task", "project_id": project.id})
    job = (await db.execute(select(DeviceJob))).scalar_one()
    stopped = await client.post(f"/chat/api/sessions/{job.session_id}/stop", headers=auth_headers)
    assert stopped.status_code == 200, stopped.text
    await db.refresh(job)
    assert (job.status, job.status_reason) == ("idle", "stopped_by_owner")


@pytest.mark.asyncio
async def test_the_persons_chat_approval_confirms_a_change_on_the_runner(client, db, auth_headers, auth_user, pool):
    from app.services.devices.chat_confirmation import device_job_for_hook

    runner, project = await _runner(client, db)
    await client.post("/chat/api/send", headers=auth_headers, json={"prompt": "Edit", "project_id": project.id})
    job = (await db.execute(select(DeviceJob))).scalar_one()
    launcher = Session(user_id=auth_user.id, project_id=project.id, agent_type="external_agent", metadata_={})
    db.add(launcher)
    await db.flush()
    hook = {"cwd": job.folder, "session_id": ""}
    assert (await device_job_for_hook(db, session=launcher, grant_id=runner.grant_id, hook_input=hook)).id == job.id
    other = (await db.execute(select(User).where(User.id != auth_user.id, User.id != runner.owner_user_id)
                              .limit(1))).scalar_one_or_none()
    if other is not None:
        launcher.user_id = other.id
        assert await device_job_for_hook(db, session=launcher, grant_id=runner.grant_id, hook_input=hook) is None


@pytest.mark.asyncio
async def test_compact_starts_a_compact_turn_where_the_thread_runs(client, db, auth_headers, auth_user, pool):
    runner, project = await _runner(client, db)
    await client.post("/chat/api/send", headers=auth_headers, json={"prompt": "Hello", "project_id": project.id})
    job = (await db.execute(select(DeviceJob))).scalar_one()
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success", "result_text": "Hi"},
                      limits={})
    await db.commit()

    compacted = await client.post(f"/chat/api/sessions/{job.session_id}/compact", headers=auth_headers)
    assert compacted.status_code == 200, compacted.text
    await db.refresh(job)
    assert (job.device_id, job.turn_prompt, job.status) == (runner.id, "/compact", "offered")

    server_thread = Session(user_id=auth_user.id, project_id=project.id, agent_type="diagnosis", metadata_={})
    db.add(server_thread)
    await db.commit()
    refused = await client.post(f"/chat/api/sessions/{server_thread.id}/compact", headers=auth_headers)
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "not_a_device_thread"


@pytest.mark.asyncio
async def test_a_decided_approval_continues_the_runner_thread(client, db, auth_headers, auth_user, pool):
    from app.models import Approval

    runner, project = await _runner(client, db)
    await client.post("/chat/api/send", headers=auth_headers, json={"prompt": "Save it", "project_id": project.id})
    job = (await db.execute(select(DeviceJob))).scalar_one()
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success", "result_text": "Held"},
                      limits={})
    approval = Approval(session_id=job.session_id, requested_by=auth_user.id, status="pending",
                        action="Approve tool execution for knowledge_episode_summary")
    db.add(approval)
    await db.commit()

    decided = await client.post(f"/chat/api/approvals/{approval.id}/approve", headers=auth_headers, json={})
    assert decided.status_code == 200, decided.text
    await db.refresh(job)
    assert job.status == "offered" and job.device_id == runner.id
    assert "approved approval" in job.turn_prompt and "Repeat exactly the same call" in job.turn_prompt


@pytest.mark.asyncio
async def test_a_diagram_made_for_a_runner_turn_lands_whole_in_its_answer(client, db, auth_headers, pool, monkeypatch):
    from app.models import Message, ToolCall
    from app.services.devices import device_turn_results

    _runner_device, project = await _runner(client, db)
    await client.post("/chat/api/send", headers=auth_headers, json={"prompt": "Draw it", "project_id": project.id})
    job = (await db.execute(select(DeviceJob))).scalar_one()

    async def the_job(*_args):
        return job

    monkeypatch.setattr(device_turn_results, "caller_device_job", the_job)
    xml = "<mxCell id='a' value='Order'/>" * 400  # far above the launcher's 4 KB clip
    await device_turn_results.keep_turn_diagram(db, caller=None, user=None, workspace=project.id,
                                                tool_name="create_diagram", result={"diagram_xml": xml, "title": "Flow"})
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success",
                                                  "result_text": "Here is the flow."}, limits={})
    await db.commit()

    answer = (await db.execute(select(Message).where(Message.session_id == job.session_id,
                                                     Message.role == "assistant"))).scalar_one()
    kept = (await db.execute(select(ToolCall).where(ToolCall.message_id == answer.id))).scalar_one()
    assert (kept.tool_name, kept.result["diagram_xml"]) == ("create_diagram", xml)


@pytest.mark.asyncio
async def test_a_thread_that_follows_a_workflow_run_runs_where_its_run_runs(db, pool, monkeypatch):
    from types import SimpleNamespace

    from app.services.workflow_runs import records

    device = {"kind": "device", "device_id": "laptop-1", "folder": "/src/shop", "profile": "governed"}

    async def no_run(_db, _session_id):
        return None

    async def a_run(_db, _session_id):
        return SimpleNamespace(context={"runtime_target": {**device, "chosen_by": "u", "at": "now"}})

    monkeypatch.setattr(records, "active_run_for_session", no_run)
    assert await chat_target_for(db, "thread-1") == POOL_TARGET
    monkeypatch.setattr(records, "active_run_for_session", a_run)
    assert await chat_target_for(db, "thread-1") == device, "the run's own target, never the pool's default"
    assert await chat_target_for(db, "") == POOL_TARGET, "a new chat follows no run"


@pytest.mark.asyncio
async def test_a_server_workflow_run_resolves_to_the_pool(client, db, auth_user, pool, monkeypatch):
    from app.services.devices import chat_turn, device_models
    from app.services.workflow_runs.runtime_target.target import validate_target

    async def governed(*_args, **_kwargs):
        return "team-coder"

    async def admitted(*_args, model, **_kwargs):
        return model, None

    monkeypatch.setattr(chat_turn, "pool_default_model", governed)
    monkeypatch.setattr(device_models, "admitted_device_model", admitted)
    runner, project = await _runner(client, db)
    for raw in (None, "server", {"kind": "server"}):
        target = await validate_target(db, user=auth_user, project_id=project.id, raw=raw)
        assert (target["kind"], target["device_id"], target["resolved_from"]) == ("device", runner.id, "server"), raw
        assert target["model"] == "team-coder", "a runner has no model of its own: the Workspace's governed one"
    own = await validate_target(db, user=auth_user, project_id=project.id, raw={"kind": "terminal"})
    assert own == {"kind": "terminal"}, "an explicit other target stays"


@pytest.mark.asyncio
async def test_a_scheduled_task_runs_as_a_runner_turn_and_keeps_its_answer(client, db, auth_user, pool, monkeypatch):
    import uuid
    from contextlib import asynccontextmanager

    import app.db as database_module
    from app.models import Task, TaskRun
    from app.scheduler import TaskScheduler

    runner, project = await _runner(client, db)
    task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id,
                name="Morning summary", task_type="agent_run", agent_type="diagnosis", owner_id=auth_user.id,
                is_active=True, config={"prompt": "Summarise the open orders."})
    db.add(task)
    await db.commit()
    _answers(db, "Three orders are open.", monkeypatch)

    @asynccontextmanager
    async def shared():
        yield db

    monkeypatch.setattr(database_module, "async_session_factory", shared)
    await TaskScheduler()._execute_task(task.id, trigger_type="manual")

    run = (await db.execute(select(TaskRun).where(TaskRun.task_id == task.id))).scalar_one()
    assert run.status == "success", run.output
    assert run.output["response"] == "Three orders are open." and run.output["runtime"] == "server_runner_pool"
    job = (await db.execute(select(DeviceJob).where(DeviceJob.session_id == run.session_id))).scalar_one()
    assert job.device_id == runner.id
