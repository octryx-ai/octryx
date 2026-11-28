"""Loop limits and budgets pause a run; continue +k, change the plan or abort."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Session, WorkflowRunDecision
from app.models.runtime.secure_work import WorkItem
from app.services.inbox.service import personal_inbox
from app.services.observability.overview_read_model import _waiting_items
from app.services.workflow_runs.binding import run_turn_resolution
from app.time_utils import utc_now
from tests.phased_workflow_fixtures import admin_user, phase_turn, phased_definition, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


async def _turn(db, session_id: str, tools: list[str]):
    session = await db.get(Session, session_id)
    resolution = await run_turn_resolution(db, session, user_message="Work on it.")
    assert resolution["status"] == "matched", resolution
    await phase_turn(db, session_id, resolution, tools)


async def _start_body(db, key: str, item: WorkItem | None = None) -> dict:
    workspace_id = await run_workspace(db, await admin_user(db), item.id if item else None)
    return {"workflow_key": key, "project_id": workspace_id, **({"work_item_id": item.id} if item else {})}


async def _view(client, headers, run_id: str) -> dict:
    return (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=headers)).json()["run"]


@pytest.mark.asyncio
async def test_a_loop_pauses_at_n_and_resumes_with_k_more_iterations(client, auth_headers, db):
    key = await publish_phased(db, phased_definition(max_iterations=1))
    assert (await client.put("/api/v1/workflow-runs/limits", headers=auth_headers,
                             json={"loop_ceiling": 2})).status_code == 200
    started = (await client.post("/api/v1/workflow-runs", headers=auth_headers, json=await _start_body(db, key))).json()
    run_id, session_id = started["run"]["id"], started["session_id"]

    await _turn(db, session_id, ["knowledge_search"])
    await _turn(db, session_id, ["knowledge_search"])
    paused = await _view(client, auth_headers, run_id)
    assert (paused["status"], paused["pause_reason"]) == ("paused", "loop_limit")
    assert paused["pause"]["detail"].startswith("'Rework' reached its limit: the work went back 1 of 1 times. Next:")
    keys = {action["key"]: action for action in paused["actions"]}
    assert keys["continue"]["input"] == {"name": "k", "kind": "number", "min": 1, "max": 1, "default": 1,
                                         "label": "More iterations"}
    assert {"change_plan", "abort"} <= set(keys)
    session = await db.get(Session, session_id)
    held = await run_turn_resolution(db, session, user_message="Go on.")
    assert held["status"] == "held"

    beyond = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                               json={"action": "continue", "k": 2})
    assert beyond.status_code == 422 and beyond.json()["detail"]["code"] == "beyond_ceiling"
    resumed = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                json={"action": "continue", "k": 1})
    assert resumed.status_code == 200, resumed.text
    run = resumed.json()["run"]
    assert (run["status"], run["current_node"]["id"], run["node_state"]["iteration"]) == ("running", "work", 3)
    assert run["loops"] == [{"edge_id": "rework", "title": "Rework", "used": 2, "limit": 2}]

    await _turn(db, session_id, ["knowledge_search", "knowledge_read"])
    done = await _view(client, auth_headers, run_id)
    assert (done["status"], done["outcome"]) == ("completed", "done")
    decisions = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == run_id))).scalars()
    assert [(item.kind, item.action, item.payload["k"]) for item in decisions] == [("pause", "continue", 1)]


@pytest.mark.asyncio
async def test_the_work_item_overrides_n_within_the_ceiling(client, auth_headers, db):
    key = await publish_phased(db, phased_definition(max_iterations=2))
    item = WorkItem(source_type="jira", source_instance="test", source_key=f"LIM-{uuid.uuid4().hex[:6]}", title="x")
    db.add(item)
    await db.flush()
    saved = await client.put(f"/api/v1/workflow-runs/work-items/{item.id}/limits", headers=auth_headers,
                             json={"loop_limit": 50})
    assert saved.status_code == 200 and saved.json()["run_limits"] == {"loop_limit": 50}
    bad = await client.put(f"/api/v1/workflow-runs/work-items/{item.id}/limits", headers=auth_headers,
                           json={"loop_limit": 0})
    assert bad.status_code == 422
    run = (await client.post("/api/v1/workflow-runs", headers=auth_headers,
                             json=await _start_body(db, key, item))).json()["run"]
    assert run["loops"][0]["limit"] == 10  # min(50, the default platform ceiling of 10)
    assert run["limits"]["work_item_loop_limit"] == 50


@pytest.mark.asyncio
async def test_a_budget_pauses_the_run_and_more_budget_lets_the_phase_result_count(client, auth_headers, db):
    definition = phased_definition()
    definition["budget"] = {"tool_calls": 2}
    key = await publish_phased(db, definition)
    started = (await client.post("/api/v1/workflow-runs", headers=auth_headers, json=await _start_body(db, key))).json()
    run_id, session_id = started["run"]["id"], started["session_id"]
    await _turn(db, session_id, ["knowledge_search", "knowledge_read"])
    paused = await _view(client, auth_headers, run_id)
    assert (paused["status"], paused["pause_reason"], paused["budget_usage"]["tool_calls"]) == (
        "paused", "budget_limit", 2)
    resumed = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                json={"action": "continue", "k": 1})
    run = resumed.json()["run"]
    assert run["limits"]["budget"]["tool_calls"] == 4
    assert (run["status"], run["outcome"]) == ("completed", "done")


@pytest.mark.asyncio
async def test_change_plan_restarts_the_plan_phase_and_abort_stops_the_run(client, auth_headers, db):
    key = await publish_phased(db, phased_definition(max_iterations=1))
    started = (await client.post("/api/v1/workflow-runs", headers=auth_headers, json=await _start_body(db, key))).json()
    run_id, session_id = started["run"]["id"], started["session_id"]
    for _ in range(2):
        await _turn(db, session_id, ["knowledge_search"])
    changed = (await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                 json={"action": "change_plan"})).json()["run"]
    assert (changed["status"], changed["current_node"]["id"]) == ("running", "work")
    assert changed["loops"][0]["used"] == 0

    admin = await admin_user(db)
    attention = [item["title"] for item in await _waiting_items(db, utc_now(), admin.id)]
    assert not any("paused" in title for title in attention)
    for _ in range(2):
        await _turn(db, session_id, ["knowledge_search"])
    attention = [item["title"] for item in await _waiting_items(db, utc_now(), admin.id)]
    assert any("workflow run(s) paused" in title for title in attention)
    inbox = await personal_inbox(db, admin)
    assert any(item["kind"] == "workflow_run_paused" and item["id"] == run_id for item in inbox["waiting"])

    unexplained = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                    json={"action": "abort"})
    assert unexplained.status_code == 422 and unexplained.json()["detail"]["code"] == "stop_reason_required"
    aborted = (await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                 json={"action": "abort", "reason": "Wrong repository"})).json()["run"]
    assert (aborted["status"], aborted["outcome"], aborted["actions"]) == ("stopped", "stopped", [])
    assert aborted["stop"]["reason"] == "Wrong repository" and aborted["stop"]["via"] == "abort"
    again = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                              json={"action": "abort", "reason": "again"})
    assert again.status_code == 404 or again.status_code == 409


@pytest.mark.asyncio
async def test_only_a_platform_admin_changes_the_ceiling(client, auth_headers, db):
    limits = (await client.get("/api/v1/workflow-runs/limits", headers=auth_headers)).json()
    assert (limits["loop_ceiling"], limits["editable"]) == (10, True)
    refused = await client.put("/api/v1/workflow-runs/limits", headers=auth_headers, json={"loop_ceiling": 0})
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_a_story_without_its_own_budget_runs_on_its_epics_budget(client, auth_headers, db):
    from app.models import WorkflowRun
    from app.services.workflow_runs.octryx.model_guard import run_budget

    key = await publish_phased(db, phased_definition())
    tag = uuid.uuid4().hex[:6]
    epic = WorkItem(source_type="jira", source_instance="test", source_key=f"CAF-{tag}", title="epic")
    db.add(epic)
    await db.flush()
    workspace_id = await run_workspace(db, await admin_user(db), epic.id)
    put = await client.put(f"/api/v1/workflow-runs/work-items/{epic.id}/limits", headers=auth_headers,
                           json={"budget": {"cost_usd": 15}})
    assert put.status_code == 200
    story = WorkItem(source_type="jira", source_instance="test", source_key=f"CAF-{tag}-1", title="story",
                     parent_key=epic.source_key, epic_key=epic.source_key, project_id=workspace_id)
    own = WorkItem(source_type="jira", source_instance="test", source_key=f"CAF-{tag}-2", title="own",
                   epic_key=epic.source_key, run_limits={"budget": {"cost_usd": 5, "tool_calls": 9}},
                   project_id=workspace_id)
    db.add_all([story, own])
    await db.flush()

    async def budget_of(item) -> float:
        run = (await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                 json={"workflow_key": key, "work_item_id": item.id})).json()["run"]
        return run_budget(await db.get(WorkflowRun, run["id"]))

    assert await budget_of(story) == 15.0  # not the 4 $ default
    assert await budget_of(own) == 5.0


@pytest.mark.asyncio
async def test_the_limits_put_is_a_patch(client, auth_headers, db):
    item = WorkItem(source_type="jira", source_instance="test", source_key=f"PAT-{uuid.uuid4().hex[:6]}", title="x")
    db.add(item)
    await db.flush()
    url = f"/api/v1/workflow-runs/work-items/{item.id}/limits"
    await client.put(url, headers=auth_headers, json={"loop_limit": 5, "budget": {"cost_usd": 15, "tool_calls": 50}})
    kept = (await client.put(url, headers=auth_headers, json={"budget": {"tool_calls": 80}})).json()["run_limits"]
    assert kept == {"loop_limit": 5, "budget": {"cost_usd": 15.0, "tool_calls": 80.0}}
    cleared = (await client.put(url, headers=auth_headers,
                                json={"loop_limit": None, "budget": {"tool_calls": None}})).json()["run_limits"]
    assert cleared == {"budget": {"cost_usd": 15.0}}
    assert (await client.put(url, headers=auth_headers, json={"budget": {"cost_usd": -1}})).status_code == 422
