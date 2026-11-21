"""Scheduled workflow Actions use shared phase preparation, preserving the service identity."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine
import app.db as database_module
from app.models import Session, TaskRun, TurnTrace, WorkflowRun, WorkflowRunEvent
from app.models.integration.webhook import Webhook
from app.scheduler import TaskScheduler
from app.scheduler.execution.workflow_phase_turn import WorkflowPhasePreparationError
from app.services.webhook_service_user import ensure_webhook_service_user
from app.services.workflow_runs.automation import start_action_run
from app.services.workflow_runs.binding import run_marker
from tests.phased_workflow_fixtures import phased_definition, publish_phased
from tests.test_action_runtime_admission import _single_session
from tests.test_phase_turn_answer_evidence import SEARCH_CALL, UNCITED
from tests.test_workflow_action_dispatch_binding import _bound


async def _action(db, *, phase_class="read_only", task_class=None, second_change=False, two_sources=False):
    task, _ = await _bound(db)
    definition = phased_definition()
    phase = definition["nodes"][1]["config"]
    phase["agent"] = "assistant" if phase_class == "read_only" else "engineer"
    phase["workflow_contract"]["capability_class"] = phase_class
    phase["tool_policy"]["allowlist"].append("submit_incident_hypothesis")
    definition["nodes"][2]["config"]["checks"][0]["params"]["tools"] = ["knowledge_search"]
    if two_sources:
        check = {"type": "evidence_count", "params": {"tools": ["knowledge_search"], "min_count": 2},
                 "blocking": True, "description": "Two content-bearing source calls"}
        phase["workflow_contract"]["checks"] = [check]
        definition["nodes"][2]["config"]["checks"] = [dict(check)]
    if second_change:
        import copy
        other = copy.deepcopy(definition["nodes"][1])
        other["id"] = "work2"
        other["config"]["agent"] = "engineer"
        other["config"]["workflow_contract"]["capability_class"] = "change"
        definition["nodes"].insert(2, other)
        definition["edges"][1]["target_node_id"] = "work2"
        definition["edges"].append({"id": "work2verify", "source_node_id": "work2", "target_node_id": "verify"})
    key = await publish_phased(db, definition)
    task.config = {**task.config, "workflow_run": {"workflow_key": key, "runtime_target": {"kind": "server"}}}
    if task_class is not None:
        task.config = {**task.config, "capability_class": task_class}
    webhook = Webhook(id=str(uuid.uuid4()), project_id=task.project_id, owner_id=task.owner_id,
                      name="Synthetic phase fixture", task_id=task.id)
    db.add(webhook)
    await db.flush()
    service = await ensure_webhook_service_user(db, webhook)
    await db.commit()
    return task, service


async def test_real_scheduled_service_turn_has_phase_agent_tools_and_one_terminal_guard_result(db, monkeypatch):
    from app.tools.registry import TOOL_REGISTRY
    task, service = await _action(db, two_sources=True)
    scheduler = TaskScheduler()
    monkeypatch.setattr(database_module, "async_session_factory", lambda: _single_session(db))
    async def search(params, context):
        source = f"https://wiki.example.test/{params['query'].replace(' ', '-')}"
        return {"state": "ok", "result_count": 1, "evidence": [{"title": params["query"],
                "content": f"Content-bearing source for {params['query']}", "source_url": source,
                "cite_as": f"[source]({source})"}]}
    monkeypatch.setattr(TOOL_REGISTRY["knowledge_search"], "execute", search)
    second = {"content": "", "tool_calls": [{"id": "call-source-two", "function": {
        "name": "knowledge_search", "arguments": '{"query": "pipeline conventions"}'}}]}
    replies = [SEARCH_CALL, second, {"content": UNCITED}, {"content": UNCITED}]
    offered, agents, principals, prompts = [], [], [], []
    async def runtimes(db_, runtime_target_id=None):
        return [{"provider_name": "bedrock", "model": "anthropic.claude-sonnet-4-5"}]
    async def chat(*, runtimes, messages, tools, **kwargs):
        offered.append({tool["function"]["name"] for tool in tools})
        prompts.append("\n".join(str(message.get("content") or "") for message in messages))
        session = (await db.execute(select(Session).where(Session.user_id == service.id))).scalar_one()
        agents.append((session.metadata_["agent_key"], session.metadata_["agent_revision"]))
        principals.append(session.user_id)
        return {"tool_calls": None, "model": "anthropic.claude-sonnet-4-5", **replies.pop(0),
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}, runtimes[0]
    monkeypatch.setattr(engine, "resolve_control_plane_runtimes", runtimes)
    monkeypatch.setattr(engine, "_chat_with_runtime_fallback", chat)
    payload = await scheduler.run_task_now(task.id, trigger_type="webhook", trigger_id="fixture-webhook",
                                          started_by=service.id, run_input={"inbound_alert": {
                                              "event_id": "fixture-event", "alert": {"title": "Synthetic alert"},
                                              "is_test": False}})
    await scheduler._execute_task(task.id, task_run_id=payload["task_run_id"], trigger_type="webhook")
    run = (await db.execute(select(WorkflowRun).where(WorkflowRun.requested_by == task.owner_id))).scalar_one()
    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars().all()
    assert [(event.kind, event.node_id) for event in events].count(("phase_turn", "work")) == 1
    assert any(event.kind == "gate_evaluated" and event.node_id == "verify" for event in events)
    assert run.gate_results["work"]["state"] == "passed"
    assert principals == [service.id] * 4 and agents == [("assistant", 1)] * 4
    assert task.config["prompt"] in prompts[0] and "Synthetic alert" in prompts[0]
    assert "untrusted" in prompts[0].lower()
    assert all({"knowledge_search", "submit_incident_hypothesis"} <= names for names in offered)
    assert all("bash" not in names and "write_workspace_file" not in names for names in offered)
    task_run = await db.get(TaskRun, payload["task_run_id"])
    session = await db.get(Session, task_run.session_id)
    assert session.user_id == service.id and run.requested_by == task.owner_id
    assert session.status != "running" and session.metadata_["run_status"] != "in_progress"
    assert "current_turn_user_message_id" not in session.metadata_
    traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().all()
    assert traces and all(run_marker(trace.context_snapshot_json.get("request_analysis")) for trace in traces)
    assert "inbound alert" in str(traces[0].context_snapshot_json).lower()
    assert len((await db.execute(select(Session).where(Session.user_id == service.id))).scalars().all()) == 1


@pytest.mark.parametrize("held", [True, False])
async def test_held_or_missing_phase_is_refused_before_any_model(db, monkeypatch, held):
    task, service = await _action(db)
    scheduler = TaskScheduler()
    called = []
    async def forbidden(**kwargs):
        called.append(kwargs)
        if False:
            yield None
    monkeypatch.setattr(engine, "run_agent", forbidden)
    async def ready(session):
        if held:
            run = await start_action_run(db, task=task, task_run=None, session=session, alert=None)
            run.status = "paused"
            await db.commit()
    with pytest.raises(WorkflowPhasePreparationError) as exc:
        await scheduler._run_agent_for_task(db, task, task.config["prompt"], on_session_ready=ready,
                                           run_as_user_id=service.id, skip_session_reuse=True)
    assert exc.value.code == ("action_workflow_phase_held" if held else "action_workflow_phase_unavailable")
    assert called == []


async def test_plain_action_never_enters_shared_phase_preparation(db, monkeypatch):
    from app.services.session import turn_prepare
    task, _ = await _bound(db)
    task.dispatch_binding = "task_definition"
    task.config = {"prompt": "Authored plain instruction"}
    await db.commit()
    async def forbidden(*args, **kwargs):
        raise AssertionError("plain Actions retain their existing path")
    monkeypatch.setattr(turn_prepare, "prepare_turn_in_session", forbidden)
    called = []
    async def plain_agent(**kwargs):
        called.append(kwargs)
        if False:
            yield None
    monkeypatch.setattr(engine, "run_agent", plain_agent)
    session, _ = await TaskScheduler()._run_agent_for_task(db, task, task.config["prompt"])
    assert len(called) == 1 and called[0]["user_message"] == task.config["prompt"]
    assert session.user_id == task.owner_id and "agent_key" not in session.metadata_


async def test_actual_execution_principal_without_workspace_membership_cannot_prepare(db, monkeypatch):
    from sqlalchemy import delete

    from app.models import ProjectUserRoleAssignment, UserProject
    task, service = await _action(db)
    await db.execute(delete(UserProject).where(UserProject.user_id == service.id))
    await db.execute(delete(ProjectUserRoleAssignment).where(ProjectUserRoleAssignment.user_id == service.id))
    await db.commit()
    calls = []
    async def forbidden(**kwargs):
        calls.append(kwargs)
        if False:
            yield None
    monkeypatch.setattr(engine, "run_agent", forbidden)
    async def ready(session):
        await start_action_run(db, task=task, task_run=None, session=session, alert=None)
    with pytest.raises(WorkflowPhasePreparationError) as exc:
        await TaskScheduler()._run_agent_for_task(db, task, task.config["prompt"], on_session_ready=ready,
                                                 run_as_user_id=service.id, skip_session_reuse=True)
    assert exc.value.code == "action_workflow_turn_refused"
    assert exc.value.as_metadata()["reason"] in {"project_not_found", "project_not_assigned"}
    assert calls == []


@pytest.mark.parametrize("phase_class", ["change"])
async def test_readonly_action_cannot_raise_its_ceiling_via_first_workflow_phase(db, monkeypatch, tmp_path, phase_class):
    task, service = await _action(db, phase_class=phase_class)
    calls = []
    async def forbidden(**kwargs):
        calls.append(kwargs)
        if False:
            yield None
    monkeypatch.setattr(engine, "run_agent", forbidden)
    async def ready(session):
        run = await start_action_run(db, task=task, task_run=None, session=session, alert=None)
        run.context = {**run.context, "local_path": str(_private_copy(tmp_path))}
        await db.commit()
    with pytest.raises(WorkflowPhasePreparationError) as exc:
        await TaskScheduler()._run_agent_for_task(db, task, task.config["prompt"], on_session_ready=ready,
                                                 run_as_user_id=service.id, skip_session_reuse=True)
    assert exc.value.code == "action_workflow_capability_refused" and calls == []


@pytest.mark.parametrize("phase_class", ["change"])
async def test_explicit_action_ceiling_allows_the_same_prepared_phase(db, monkeypatch, tmp_path, phase_class):
    task, service = await _action(db, phase_class=phase_class, task_class=phase_class)
    calls = []
    async def scripted(**kwargs):
        calls.append(kwargs)
        if False:
            yield None
    monkeypatch.setattr(engine, "run_agent", scripted)
    async def ready(session):
        run = await start_action_run(db, task=task, task_run=None, session=session, alert=None)
        run.context = {**run.context, "local_path": str(_private_copy(tmp_path))}
        await db.commit()
    session, _ = await TaskScheduler()._run_agent_for_task(db, task, task.config["prompt"], on_session_ready=ready,
                                                         run_as_user_id=service.id, skip_session_reuse=True)
    assert len(calls) == 1 and calls[0]["user_id"] == service.id
    assert session.metadata_["declared_run_capability"]["class"] == phase_class


def _private_copy(root):
    import subprocess
    path = root / "copy"
    path.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    return path


@pytest.mark.parametrize("declared,required,allowed", [
    (None, "deliver", False), ("change", "deliver", False), ("deliver", "deliver", True),
])
def test_closed_delivery_ceiling_without_widening_the_published_phase_agent(declared, required, allowed):
    from types import SimpleNamespace

    from app.scheduler.execution.workflow_phase_turn import _require_phase_ceiling

    task = SimpleNamespace(config={} if declared is None else {"capability_class": declared})
    resolution = {"workflow_contract": {"capability_class": required}}
    if allowed:
        _require_phase_ceiling(task, resolution)
    else:
        with pytest.raises(WorkflowPhasePreparationError, match="action_workflow_capability_refused"):
            _require_phase_ceiling(task, resolution)


async def test_phase_move_during_shared_preparation_is_refused_before_model(db, monkeypatch, tmp_path):
    from app.services.session import turn_prepare

    task, service = await _action(db, second_change=True)
    original = turn_prepare.prepare_turn_in_session
    calls = []
    async def move_then_prepare(db_, **kwargs):
        run = (await db_.execute(select(WorkflowRun))).scalar_one()
        run.current_node_id = "work2"
        run.node_state = {**run.node_state, "entry": 2}
        await db_.commit()
        return await original(db_, **kwargs)
    async def forbidden(**kwargs):
        calls.append(kwargs)
        if False:
            yield None
    monkeypatch.setattr(turn_prepare, "prepare_turn_in_session", move_then_prepare)
    monkeypatch.setattr(engine, "run_agent", forbidden)
    async def ready(session):
        run = await start_action_run(db, task=task, task_run=None, session=session, alert=None)
        run.context = {**run.context, "local_path": str(_private_copy(tmp_path))}
        await db.commit()
    with pytest.raises(WorkflowPhasePreparationError, match="action_workflow_phase_held"):
        await TaskScheduler()._run_agent_for_task(db, task, task.config["prompt"], on_session_ready=ready,
                                                 run_as_user_id=service.id, skip_session_reuse=True)
    assert calls == []
    session = (await db.execute(select(Session).where(Session.user_id == service.id))).scalar_one()
    assert session.status == "active" and session.metadata_["run_status"] == "failed"
    assert "current_turn_user_message_id" not in session.metadata_
    assert not (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.kind == "phase_turn"))).first()


@pytest.mark.parametrize("outcome", ["approval", "newer_turn", "exception"])
async def test_phase_root_settlement_and_task_cleanup_preserve_approval_or_newer_turn(db, monkeypatch, outcome):
    from app.services.session.turn_approval_state import CURRENT_TURN_USER_MESSAGE_KEY
    from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

    task, service = await _action(db)
    scheduler = TaskScheduler()
    monkeypatch.setattr(database_module, "async_session_factory", lambda: _single_session(db))
    async def boundary(**kwargs):
        session = await db.get(Session, kwargs["session_id"])
        if outcome == "exception":
            raise RuntimeError("bounded scripted runtime failure")
        metadata = dict(session.metadata_)
        if outcome == "approval":
            session.status = "pending_approval"
            metadata["approval_paused_turns"] = {"fixture-approval": {"owner_user_id": service.id}}
        else:
            session.status = "running"
            metadata[CURRENT_TURN_USER_MESSAGE_KEY] = "newer-turn"
            metadata[ROUTING_RESOLUTION_KEY] = {}
        session.metadata_ = metadata
        await db.commit()
        if False:
            yield None
    monkeypatch.setattr(engine, "run_agent", boundary)
    payload = await scheduler.run_task_now(task.id, trigger_type="webhook", started_by=service.id,
                                          run_input={"inbound_alert": {"alert": {"title": "Synthetic fixture"}}})
    await scheduler._execute_task(task.id, task_run_id=payload["task_run_id"], trigger_type="webhook")
    run = await db.get(TaskRun, payload["task_run_id"])
    session = await db.get(Session, run.session_id)
    await db.refresh(session)
    if outcome == "approval":
        assert session.status == "pending_approval"
        assert session.metadata_["run_status"] == "awaiting_approval"
        assert session.metadata_["approval_paused_turns"]["fixture-approval"]["owner_user_id"] == service.id
        assert CURRENT_TURN_USER_MESSAGE_KEY not in session.metadata_
    elif outcome == "newer_turn":
        assert session.status == "running" and session.metadata_["run_status"] == "in_progress"
        assert session.metadata_[CURRENT_TURN_USER_MESSAGE_KEY] == "newer-turn"
    else:
        assert session.status == "active" and session.metadata_["run_status"] == "failed"
        assert CURRENT_TURN_USER_MESSAGE_KEY not in session.metadata_
        assert run.status == "error"
