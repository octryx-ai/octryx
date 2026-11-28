"""A workflow run starts only in a Workspace: every live entry path answers ``needs_configuration`` /
``workspace_required`` at its public boundary, before anything is written."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models import Project, Task, User, WorkflowRun
from app.models.runtime.secure_work import WorkItem
from tests.chat_phased_workflow_start_support import fakes  # noqa: F401
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.policy_engine_support import bearer
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("scripted_pool")]


@pytest.fixture(autouse=True)
def _no_workspace_to_default_to(monkeypatch):
    # A chat that names no Workspace starts in the person's default one; these starts have none to default to.
    import app.web.routers.chat_upload_send as chat_upload_send

    async def as_requested(_db, *, user, project_id, active_workspace_ids=None):
        return str(project_id or "").strip()

    monkeypatch.setattr(chat_upload_send, "new_chat_workspace", as_requested)

DEFINITION = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "go", "type": "user_confirmation", "label": "Go on?",
               "config": {"subject": "advance", "decider": "requester"}},
              {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
    "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "go"},
              {"id": "r0", "source_node_id": "go", "target_node_id": "done", "when": "confirmed"}],
}
TYPED = ("needs_configuration", "workspace_required")


def _typed(answer: dict) -> tuple[str, str]:
    return answer.get("state"), answer.get("reason")


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _item(db, project_id: str | None) -> WorkItem:
    item = WorkItem(project_id=project_id, source_type="platform", source_instance="platform",
                    source_key=f"WR-{uuid.uuid4().hex[:6]}", title="Checkout fails")
    db.add(item)
    await db.flush()
    return item


@pytest.mark.parametrize("caller", ["admin", "member"])
@pytest.mark.parametrize("case", ["no_workspace", "item_without_workspace", "item_without_workspace_and_project"])
async def test_the_rest_start_without_a_workspace_is_typed_for_every_caller_scope(client, db, auth_headers, caller,
                                                                                    case):
    key = await publish_phased(db, DEFINITION)
    workspace_id = await seed_workspace(db)
    headers = auth_headers if caller == "admin" else bearer(await seed_member(db, workspace_id=workspace_id))
    body: dict = {"workflow_key": key}
    if case != "no_workspace":
        body["work_item_id"] = (await _item(db, None)).id
    if case == "item_without_workspace_and_project":
        body["project_id"] = workspace_id
    await db.commit()
    runs = await _count(db, WorkflowRun)
    response = await client.post("/api/v1/workflow-runs", json=body, headers=headers)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert _typed(detail) == TYPED and detail["code"] == "workspace_required"
    assert "Choose a Workspace" in detail["message"]
    assert await _count(db, WorkflowRun) == runs


async def test_a_foreign_work_item_keeps_its_scope_refusal_not_a_workspace_hint(client, db):
    key = await publish_phased(db, DEFINITION)
    mine, foreign = await seed_workspace(db), await seed_workspace(db)
    member = await seed_member(db, workspace_id=mine)
    item = await _item(db, foreign)
    await db.commit()
    response = await client.post("/api/v1/workflow-runs", json={"workflow_key": key, "work_item_id": item.id},
                                 headers=bearer(member))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "work_item_scope" and "state" not in response.json()["detail"]


async def test_a_rest_start_in_a_workspace_still_starts(client, db, auth_headers):
    admin = await admin_user(db)
    workspace_id = await seed_workspace(db)
    from tests.phased_workflow_fixtures import join_workspace

    await join_workspace(db, admin, workspace_id)
    key = await publish_phased(db, DEFINITION)
    item = await _item(db, workspace_id)
    await db.commit()
    response = await client.post("/api/v1/workflow-runs", json={"workflow_key": key, "work_item_id": item.id},
                                 headers=auth_headers)
    assert response.status_code == 200, response.text
    assert (await db.get(WorkflowRun, response.json()["run"]["id"])).project_id == workspace_id


async def test_a_bug_fix_start_in_the_own_private_workspace_is_refused_typed(client, db):
    from app.models import Session
    from app.services.auth import create_access_token
    from app.services.project.private_workspace import ensure_private_workspace
    from tests.devices.device_support import user_named
    from tests.policy_engine_support import grant_role

    owner = await user_named(db, f"dev-{uuid.uuid4().hex[:6]}")
    await db.commit()
    await grant_role(db, owner.id, "developer")
    private = await ensure_private_workspace(db, owner)
    await db.commit()
    runs, sessions = await _count(db, WorkflowRun), await _count(db, Session)

    response = await client.post(
        "/api/v1/workflow-runs", json={"workflow_key": "bug-fix-reproduction", "project_id": private.id},
        headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "private_workspace_has_no_work"
    assert (await _count(db, WorkflowRun), await _count(db, Session)) == (runs, sessions)


@pytest.mark.committed_db
async def test_the_chat_start_card_answer_and_its_retry_are_refused_typed_and_create_nothing(
        client, db, auth_headers, fakes):  # noqa: F811
    from tests.chat_phased_workflow_start_support import _answer, _record, _send

    state = fakes("spec-writing")
    items = await _count(db, WorkItem)
    session_id = await _send(client, auth_headers, project_id="", workflow_key="spec-writing")
    record = await _record(db, session_id)
    assert record["phased"] and record["start"]["project_id"] is None
    for _attempt in ("allow", "allow again"):
        response = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply")
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert _typed(detail) == TYPED and "Choose a Workspace" in detail["message"]
    assert state["started"] == [] and state["jira_calls"] == []
    assert (await _record(db, session_id))["started"] is None
    assert await _count(db, WorkItem) == items


@pytest.mark.committed_db
async def test_a_chat_start_allowed_on_the_approval_route_records_the_typed_refusal(
        client, db, auth_headers, fakes):  # noqa: F811
    from tests.chat_phased_workflow_start_support import _approval, _record, _send, _settle

    state = fakes("spec-writing")
    items = await _count(db, WorkItem)
    session_id = await _send(client, auth_headers, project_id="", workflow_key="spec-writing")
    approval = await _approval(db, session_id)
    response = await client.post(f"/api/v1/approvals/{approval.id}/approve", json={}, headers=auth_headers)
    assert response.status_code == 200, response.text
    await _settle(session_id)
    started = (await _record(db, session_id))["started"]
    assert _typed(started) == TYPED, started
    assert "Choose a Workspace" in started["error"] and "Press Start again" not in started["error"]
    assert "work_item_id" not in started
    view = (await client.get(f"/chat/api/bootstrap?session_id={session_id}", headers=auth_headers)).json()
    assert _typed(view["selectedSession"]["workflowProposal"]["started"]) == TYPED
    assert state["started"] == [] and state["jira_calls"] == []
    assert await _count(db, WorkItem) == items


@pytest.mark.committed_db
async def test_mcp_workflow_select_without_a_workspace_answers_needs_configuration(db, monkeypatch):
    from tests.mcp_claude_code_parity_support import SCOPES, _native
    from tests.mcp_native_support import mcp_call, native_token

    _native(db, monkeypatch)
    member = await seed_member(db, workspace_id=await seed_workspace(db))
    await db.commit()
    token = await native_token(db, user_id=member, scopes=list(SCOPES))
    answer = await mcp_call(token, "workflow_select", {"workflow_key": "spec-writing", "work_item": "WR-1"})
    assert _typed(answer) == TYPED, answer
    assert "Workspace" in answer["error"]


def _workflow_action(project_id: str | None) -> dict:
    return {"name": f"ws-required-{uuid.uuid4().hex[:6]}", "task_type": "agent_run", "agent_type": "diagnosis",
            "project_id": project_id, "dispatch_binding": "workflow_run",
            "config": {"prompt": "Analyse the alert.", "workflow_run": {
                "workflow_key": "incident-analysis", "runtime_target": {"kind": "server"}}}}


async def test_the_panel_refuses_an_action_without_a_workspace_typed(client, db, auth_headers):
    tasks = await _count(db, Task)
    response = await client.post("/admin/chat/api/panel/tasks", json=_workflow_action(None), headers=auth_headers)
    assert response.status_code == 422, response.text
    assert _typed(response.json()["detail"]) == TYPED
    assert await _count(db, Task) == tasks


async def test_an_imported_workflow_action_without_a_target_workspace_is_refused_typed(db):
    from fastapi import HTTPException

    from app.services.export_package import create_export_package, import_package

    admin = await admin_user(db)
    project = Project(name=f"ws-required-{uuid.uuid4().hex[:6]}")
    db.add(project)
    await db.flush()
    task = Task(id=str(uuid.uuid4()), owner_id=admin.id, **_workflow_action(project.id))
    db.add(task)
    await db.commit()
    package = await create_export_package(db, current_user=admin, package_type="task", entity_id=task.id)
    with pytest.raises(HTTPException) as refused:
        await import_package(db, current_user=admin, package_id=package["id"], target_project_id=None,
                             name_override="ws-required-imported")
    assert refused.value.status_code == 422 and _typed(refused.value.detail) == TYPED


async def _stored_action(db) -> Task:
    from app.services.admin.task import _admin_task_management as admin_tasks

    admin = await admin_user(db)
    project = Project(name=f"ws-required-{uuid.uuid4().hex[:6]}")
    db.add(project)
    await db.flush()
    saved = await admin_tasks.create_task(db, user_id=admin.id, payload=_workflow_action(project.id))
    return await db.get(Task, saved["id"])


async def test_run_now_of_an_action_without_its_workspace_answers_needs_configuration(client, db, auth_headers):
    from app.models import TaskRun

    task = await _stored_action(db)
    task.project_id = None  # the stored row lost its Workspace: nothing may be queued for it
    await db.commit()
    runs = await _count(db, TaskRun)
    response = await client.post(f"/admin/chat/api/panel/tasks/{task.id}/run", headers=auth_headers)
    assert response.status_code == 409, response.text
    assert _typed(response.json()["detail"]) == TYPED
    assert await _count(db, TaskRun) == runs


async def test_a_queued_workflow_action_that_lost_its_workspace_records_the_typed_refusal(db, monkeypatch):
    from tests.scheduler.test_action_runtime_admission import _run

    task = await _stored_action(db)
    await db.commit()

    async def drop_workspace():
        task.project_id = None
        await db.commit()

    run, entry, calls = await _run(db, monkeypatch, task, after_enqueue=drop_workspace)
    assert calls == [] and run.session_id is None
    assert (run.status, run.error) == ("error", "workspace_required")
    assert _typed(run.output["action_admission_refusal"]) == TYPED
    assert entry.completed_at is not None


async def test_an_action_run_start_without_a_workspace_is_refused_before_any_lookup(db):
    from types import SimpleNamespace

    from app.services.workflow_runs.automation import start_action_run
    from app.services.workflow_runs.records import WorkflowRunError, new_chat_session

    admin = await admin_user(db)
    task = SimpleNamespace(id=str(uuid.uuid4()), project_id=None, owner_id=str(uuid.uuid4()),
                           config={"workflow_run": {"workflow_key": "no-such-workflow"}})
    with pytest.raises(WorkflowRunError) as refused:
        await start_action_run(db, task=task, task_run=None, session=await new_chat_session(db, admin, None),
                               alert=None)
    assert (refused.value.state, refused.value.code) == TYPED


@pytest.mark.committed_db
@pytest.mark.parametrize("route", ["api", "channel"])
async def test_an_approval_that_resumes_a_start_reports_the_typed_start_outcome_beside_its_own(
        client, db, auth_headers, fakes, route):  # noqa: F811
    from app.services.channel_router_runtime.approval_commands import handle_approval_command
    from tests.chat_phased_workflow_start_support import _approval, _send, _settle
    from tests.mcp_native_support import session_factory

    state = fakes("spec-writing")
    session_id = await _send(client, auth_headers, project_id="", workflow_key="spec-writing")
    approval = await _approval(db, session_id)
    if route == "api":
        response = await client.post(f"/api/v1/approvals/{approval.id}/approve", json={}, headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "approved"
        start = body["workflow_start"]
        assert (start["state"], start["reason"], start["run_id"]) == (*TYPED, None)
        assert "Choose a Workspace" in start["message"]
    else:
        admin = await admin_user(db)
        reply = await handle_approval_command(db, f"approve {approval.id}", admin.id,
                                              session_factory=session_factory(db))
        assert reply.startswith("✓ Approved:")
        assert "did not start (needs_configuration: workspace_required)" in reply and "Choose a Workspace" in reply
    await _settle(session_id)
    assert state["started"] == []


@pytest.mark.committed_db
async def test_a_rejected_or_started_start_reports_its_own_outcome(client, db, auth_headers, fakes):  # noqa: F811
    from tests.chat_phased_workflow_start_support import _approval, _send, _workspace

    fakes("spec-writing")
    denied_session = await _send(client, auth_headers, project_id="", workflow_key="spec-writing")
    denied = await client.post(f"/api/v1/approvals/{(await _approval(db, denied_session)).id}/reject", json={},
                               headers=auth_headers)
    assert denied.status_code == 200 and denied.json()["status"] == "rejected"
    assert denied.json()["workflow_start"] is None

    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id, workflow_key="spec-writing")
    started = await client.post(f"/api/v1/approvals/{(await _approval(db, session_id)).id}/approve", json={},
                                headers=auth_headers)
    assert started.status_code == 200, started.text
    start = started.json()["workflow_start"]
    assert start["state"] == "started" and start["run_id"] and start["reason"] is None


@pytest.mark.parametrize("caller", ["admin", "member"])
@pytest.mark.parametrize("with_item", [False, True])
async def test_an_unknown_workspace_id_is_refused_typed_before_anything_is_written(client, db, auth_headers, caller,
                                                                                     with_item):
    from app.models import Session as ChatSession

    key = await publish_phased(db, DEFINITION)
    workspace_id = await seed_workspace(db)
    headers = auth_headers if caller == "admin" else bearer(await seed_member(db, workspace_id=workspace_id))
    body: dict = {"workflow_key": key, "project_id": str(uuid.uuid4())}
    if with_item:
        body["work_item_id"] = (await _item(db, None)).id
    await db.commit()
    sessions, runs = await _count(db, ChatSession), await _count(db, WorkflowRun)
    response = await client.post("/api/v1/workflow-runs", json=body, headers=headers)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert _typed(detail) == TYPED
    if not with_item:  # the named Workspace is checked; an item without a Workspace is refused before
        assert "does not exist" in detail["message"]
    assert (await _count(db, ChatSession), await _count(db, WorkflowRun)) == (sessions, runs)


async def test_an_inactive_workspace_is_refused_as_needs_configuration_before_anything_is_written(
        client, db, auth_headers):
    from app.models import Session as ChatSession

    key = await publish_phased(db, DEFINITION)
    workspace_id = await seed_workspace(db)
    (await db.get(Project, workspace_id)).is_active = False
    await db.commit()
    sessions = await _count(db, ChatSession)
    response = await client.post("/api/v1/workflow-runs", json={"workflow_key": key, "project_id": workspace_id},
                                 headers=auth_headers)
    assert response.status_code == 409
    assert _typed(response.json()["detail"]) == ("needs_configuration", "workspace_inactive")
    assert await _count(db, ChatSession) == sessions


async def test_an_unknown_work_item_is_not_found_before_anything_is_written(client, db, auth_headers):
    from app.models import Session as ChatSession

    key = await publish_phased(db, DEFINITION)
    sessions = await _count(db, ChatSession)
    response = await client.post("/api/v1/workflow-runs", json={"workflow_key": key, "work_item_id": "missing"},
                                 headers=auth_headers)
    assert response.status_code == 404 and response.json()["detail"]["code"] == "unknown_work_item"
    assert await _count(db, ChatSession) == sessions


@pytest.mark.parametrize("caller", ["admin", "member"])
async def test_a_session_for_an_unknown_or_foreign_workspace_is_never_written(client, db, auth_headers, caller):
    from app.models import Session as ChatSession

    mine, foreign = await seed_workspace(db), await seed_workspace(db)
    headers = auth_headers if caller == "admin" else bearer(await seed_member(db, workspace_id=mine))
    await db.commit()
    sessions = await _count(db, ChatSession)
    unknown = await client.post("/api/v1/sessions", json={"project_id": str(uuid.uuid4())}, headers=headers)
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "project_not_found"
    if caller == "member":
        refused = await client.post("/api/v1/sessions", json={"project_id": foreign}, headers=headers)
        assert refused.json()["detail"] == unknown.json()["detail"] and refused.status_code == 404, refused.text
    assert await _count(db, ChatSession) == sessions
    created = await client.post("/api/v1/sessions", json={"project_id": mine}, headers=headers)
    assert created.status_code == 200, created.text


async def test_a_chat_turn_for_an_unknown_workspace_writes_no_session_even_for_an_admin(client, db, auth_headers):
    from app.models import Session as ChatSession

    sessions = await _count(db, ChatSession)
    response = await client.post("/chat/api/send", json={"prompt": "Hello", "project_id": str(uuid.uuid4()),
                                                         "session_id": ""}, headers=auth_headers)
    assert response.status_code == 404, response.text
    assert "project_not_found" in response.text or "does not exist" in response.text
    assert await _count(db, ChatSession) == sessions


@pytest.mark.parametrize("caller", ["admin", "member"])
async def test_an_unknown_workspace_next_to_a_visible_item_is_needs_configuration(client, db, auth_headers, caller):
    from app.models import Session as ChatSession

    key = await publish_phased(db, DEFINITION)
    workspace_id = await seed_workspace(db)
    headers = auth_headers if caller == "admin" else bearer(await seed_member(db, workspace_id=workspace_id))
    item = await _item(db, workspace_id)  # a scoped item the caller may see
    await db.commit()
    sessions, runs = await _count(db, ChatSession), await _count(db, WorkflowRun)
    response = await client.post("/api/v1/workflow-runs", json={
        "workflow_key": key, "work_item_id": item.id, "project_id": str(uuid.uuid4())}, headers=headers)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert _typed(detail) == TYPED and "does not exist" in detail["message"]
    assert (await _count(db, ChatSession), await _count(db, WorkflowRun)) == (sessions, runs)


async def test_a_foreign_item_next_to_an_unknown_workspace_keeps_the_scope_refusal(client, db):
    key = await publish_phased(db, DEFINITION)
    mine, foreign = await seed_workspace(db), await seed_workspace(db)
    member = await seed_member(db, workspace_id=mine)
    item = await _item(db, foreign)
    await db.commit()
    response = await client.post("/api/v1/workflow-runs", json={
        "workflow_key": key, "work_item_id": item.id, "project_id": str(uuid.uuid4())}, headers=bearer(member))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "work_item_scope" and "state" not in response.json()["detail"]


@pytest.mark.parametrize("caller", ["admin", "member"])
async def test_a_visible_item_of_another_existing_workspace_is_a_scope_refusal(client, db, auth_headers, caller):
    key = await publish_phased(db, DEFINITION)
    first, second = await seed_workspace(db), await seed_workspace(db)
    if caller == "admin":
        headers = auth_headers
    else:
        member = await seed_member(db, workspace_id=first)
        from tests.phased_workflow_fixtures import join_workspace

        await join_workspace(db, await db.get(User, member), second, role="member")
        headers = bearer(member)
    item = await _item(db, first)
    await db.commit()
    response = await client.post("/api/v1/workflow-runs", json={
        "workflow_key": key, "work_item_id": item.id, "project_id": second}, headers=headers)
    assert response.status_code == 403 and response.json()["detail"]["code"] == "work_item_scope"


@pytest.mark.parametrize("caller", ["admin", "member"])
@pytest.mark.parametrize("blank", ["", "   "])
async def test_an_empty_workspace_id_on_session_create_is_stored_as_no_workspace(client, db, auth_headers, caller,
                                                                                   blank):
    from app.models import Session as ChatSession

    headers = auth_headers if caller == "admin" else bearer(await seed_member(db, workspace_id=await seed_workspace(db)))
    await db.commit()
    response = await client.post("/api/v1/sessions", json={"project_id": blank}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["project_id"] is None
    stored = await db.get(ChatSession, response.json()["id"])
    assert stored.project_id is None


@pytest.mark.parametrize("caller", ["admin", "member"])
async def test_a_blank_workspace_id_on_a_start_is_absent_and_a_required_one_is_refused(client, db, auth_headers,
                                                                                         caller):
    from app.models import Task

    key = await publish_phased(db, DEFINITION)
    headers = auth_headers if caller == "admin" else bearer(await seed_member(db, workspace_id=await seed_workspace(db)))
    await db.commit()
    started = await client.post("/api/v1/workflow-runs", json={"workflow_key": key, "project_id": ""}, headers=headers)
    assert started.status_code == 409 and _typed(started.json()["detail"]) == TYPED  # blank = no Workspace
    tasks = await _count(db, Task)
    task = {"name": "x", "task_type": "agent_run", "agent_type": "diagnosis", "dispatch_binding": "task_definition"}
    refused = await client.post("/api/v1/tasks", json={**task, "project_id": " "}, headers=headers)
    assert refused.status_code == 422 and "project_id" in refused.text, refused.text
    unknown = await client.post("/api/v1/tasks", json={**task, "project_id": str(uuid.uuid4())}, headers=headers)
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "project_not_found"
    assert await _count(db, Task) == tasks
