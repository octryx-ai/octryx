"""DevOps workflows: the workflow run record, its Work item anchor, turn binding and resume."""

from __future__ import annotations

import copy
import uuid

import pytest
from sqlalchemy import select

from app.models import Session, User, WorkflowRun, WorkflowRunEvent, WorkflowRunSession
from app.models.runtime.secure_work import WorkItem
from app.services.execution_profile_service import build_execution_profile
from app.services.workflow_checks.library import CheckResult
from app.services.workflow_routing.workflow_selection import (
    ROUTING_RESOLUTION_KEY,
    workflow_selection_from_resolution,
)
from app.services.workflow_runs.binding import held_resolution, record_phase_turn, run_turn_resolution
from app.services.workflow_runs.records import WorkflowRunError, bind_session, start_run
from app.services.workflow_runs.run_sessions import new_bound_session
from tests.phased_workflow_fixtures import PHASE, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


def _one_phase_definition() -> dict:
    return {
        "execution_kind": "phased",
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "work", "type": "phase", "label": "Collect evidence", "config": copy.deepcopy(PHASE)},
            {"id": "done", "type": "outcome", "label": "Done", "config": {"outcome": "done"}},
        ],
        "edges": [
            {"id": "e1", "source_node_id": "start", "target_node_id": "work"},
            {"id": "e2", "source_node_id": "work", "target_node_id": "done"},
        ],
    }


async def _workflow(db) -> str:
    return await publish_phased(db, _one_phase_definition())


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _item(db) -> WorkItem:
    token = uuid.uuid4().hex[:6]
    item = WorkItem(source_type="jira", source_instance="test", source_key=f"RUN-{token}", title="Anchor item")
    db.add(item)
    await db.flush()
    return item


def _profile(resolution: dict) -> dict:
    return build_execution_profile(
        prompt="go", requested_agent_type="chat", effective_agent_type="chat", execution_strategy="direct",
        execution_strategy_reason="", routing_intent="knowledge", routing_reason="", routing_intent_confidence=None,
        routing_intent_source="", workflow_id=str(resolution.get("workflow_id") or ""),
        workflow_contract=resolution.get("workflow_contract"), workflow_routing_policy_resolution=resolution,
    ).to_metadata()


@pytest.mark.asyncio
async def test_a_run_pins_its_version_anchors_the_work_item_and_governs_its_session(db):
    admin = await _admin(db)
    item = await _item(db)
    workspace_id = await run_workspace(db, admin, item.id)
    run = await start_run(db, user=admin, workflow_key=await _workflow(db),
                          project_id=workspace_id, work_item_id=item.id)
    session = await new_bound_session(db, run, admin)

    assert (run.workflow_kind, run.status, run.ticket_key) == ("phased", "running", item.source_key)
    assert run.workflow_version.startswith("v")
    resolution = await run_turn_resolution(db, session, user_message="What is documented?")
    assert resolution["selection_source"] == "workflow_run"
    assert resolution["workflow_run"]["run_id"] == run.id
    assert (resolution["workflow_run"]["node_id"], resolution["workflow_run"]["kind"]) == ("work", "phased")
    assert workflow_selection_from_resolution(resolution).reason_code == "workflow_run"
    profile = _profile(resolution)
    assert (profile["status"], profile["decision_source"]) == ("allowed", "workflow_run")

    analysis = {ROUTING_RESOLUTION_KEY: resolution}
    failed = [CheckResult("tool_called", "failed", True, "evidence", "not called")]
    await record_phase_turn(db, request_analysis=analysis, session_id=session.id, state="not_verified",
                            results=failed, evidence=None)
    assert run.status == "running" and run.gate_results["work"]["state"] == "not_verified"
    await db.flush()
    turn = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
                                                            WorkflowRunEvent.kind == "phase_turn"))).scalars().one()
    assert turn.detail["failed_checks"] == [{"type": "tool_called", "description": "evidence", "detail": "not called"}]
    passed = [CheckResult("tool_called", "passed", True, "evidence", "")]
    await record_phase_turn(db, request_analysis=analysis, session_id=session.id, state="passed",
                            results=passed, evidence=None)
    assert (run.status, run.outcome) == ("completed", "done")
    assert await run_turn_resolution(db, session, user_message="next") is None


@pytest.mark.asyncio
async def test_a_run_resumes_in_a_new_session_and_the_old_one_is_released(db):
    admin = await _admin(db)
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=await _workflow(db), project_id=workspace_id)
    first = await new_bound_session(db, run, admin)
    second = Session(user_id=admin.id, status="active", metadata_={})
    db.add(second)
    await db.flush()
    await bind_session(db, run, second, actor_id=admin.id)

    assert await run_turn_resolution(db, first, user_message="x") is None
    assert (await run_turn_resolution(db, second, user_message="x"))["workflow_run"]["run_id"] == run.id
    bindings = (await db.execute(select(WorkflowRunSession).where(WorkflowRunSession.run_id == run.id))).scalars()
    assert sorted((item.session_id == second.id, item.active) for item in bindings) == [(False, False), (True, True)]


@pytest.mark.asyncio
async def test_a_workflow_without_done_criteria_or_unknown_cannot_run(db):
    admin = await _admin(db)
    with pytest.raises(WorkflowRunError) as unknown:
        workspace_id = await run_workspace(db, admin)
        await start_run(db, user=admin, workflow_key="no-such-workflow", project_id=workspace_id)
    assert unknown.value.code == "unknown_workflow"


def test_a_held_run_turn_never_runs():
    run = WorkflowRun(id="run-1", workflow_key="w", workflow_kind="phased", current_node_id="confirm")
    profile = _profile(held_resolution(run, profile_status="needs_clarification", reason="Waiting for you."))
    assert (profile["status"], profile["decision_source"], profile["reason"]) == (
        "needs_clarification", "workflow_run", "Waiting for you.")


@pytest.mark.asyncio
async def test_the_run_api_starts_shows_and_resumes_a_run(client, auth_headers, db):
    item = await _item(db)
    key = await _workflow(db)
    await run_workspace(db, await _admin(db), item.id)
    started = await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                json={"workflow_key": key, "work_item_id": item.id})
    assert started.status_code == 200, started.text
    body = started.json()
    run_id, session_id = body["run"]["id"], body["session_id"]
    assert body["run"]["work_item"]["key"] == item.source_key
    assert body["run"]["phase_position"] == {"index": 1, "total": 1}
    assert [action["key"] for action in body["run"]["actions"]] == ["change_runtime", "abort", "resume_in_new_session"]

    banner = (await client.get(f"/api/v1/workflow-runs/by-session/{session_id}", headers=auth_headers)).json()
    assert banner["run"]["id"] == run_id
    resumed = await client.post(f"/api/v1/workflow-runs/{run_id}/sessions", headers=auth_headers, json={})
    assert resumed.status_code == 200 and resumed.json()["session_id"] != session_id
    events = (await client.get(f"/api/v1/workflow-runs/{run_id}/events", headers=auth_headers)).json()["events"]
    assert [event["kind"] for event in events][:2] == ["run_started", "session_bound"]
    listed = (await client.get(f"/api/v1/workflow-runs?work_item_id={item.id}", headers=auth_headers)).json()
    assert [row["id"] for row in listed["runs"]] == [run_id]
    assert listed["runs"][0]["session_id"] == resumed.json()["session_id"]
    startable = (await client.get("/api/v1/workflow-runs/startable", headers=auth_headers)).json()["workflows"]
    keys = {item["key"] for item in startable}
    assert key in keys and "spring-boot-4-upgrade" not in keys
    refused = await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                json={"workflow_key": "spring-boot-4-upgrade", "project_id": item.project_id})
    assert refused.status_code in (404, 422)
