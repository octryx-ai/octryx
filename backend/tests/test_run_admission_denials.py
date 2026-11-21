"""Run admission: every run path refuses an archived or retired item with a typed ``denied`` reason."""

from __future__ import annotations

import copy
import uuid

import pytest
from sqlalchemy import select

from app.models import FlowDefinition, Project, Task
from app.scheduler.execution.action_admission import AGENT_AND_WORKFLOW, ActionAdmissionError, admit_agent_turn
from app.services.execution_profile_status import _derive_profile_status_and_source
from app.services.mcp_governed_knowledge import McpCaller
from app.services.mcp_workflow_tools import mcp_workflow_select
from app.services.run_admission.action_config import action_config_refusal
from app.services.workflow_routing.explicit_selection import resolve_explicit_workflow_selection
from app.services.workflow_runs.records import WorkflowRunError, new_chat_session, start_run
from app.tools.context import ToolContext
from app.tools.workflow_tools import SelectWorkflowTool
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace

pytestmark = pytest.mark.asyncio


async def _project(db) -> Project:
    project = Project(id=str(uuid.uuid4()), name=f"denials-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add(project)
    await db.commit()
    return project


async def test_an_archived_phased_workflow_is_denied_on_every_selection_path(db):
    key = await publish_phased(db, copy.deepcopy(phased_definition()))
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    flow.status, flow.is_active = "archived", False
    await db.commit()

    resolution = await resolve_explicit_workflow_selection(db, workflow_key=key)
    assert (resolution["status"], resolution["denial"]) == ("workflow_archived", "workflow_archived")
    status, source, _reason = _derive_profile_status_and_source(
        prompt="hello", agent_type_explicit=False, workflow_routing_policy_resolution=resolution,
        routing_intent_source="policy", routing_reason="")
    assert (status, source) == ("denied", "workflow_archived")
    # The model's select_workflow tool.
    tool = await SelectWorkflowTool().execute({"workflow_key": key}, ToolContext(
        user_id="u", project_ids=[], roles=["admin"], session_id="s", project_config={}, db=db,
        run_capability=None, turn_context_snapshot={}))
    assert (tool["status"], tool["reason"]) == ("denied", "workflow_archived")
    # octryx workflow_select.
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    caller = McpCaller(user_id=member_id, grant_id="mcp", scopes=("workflow:read",), workspace_header=workspace_id,
                       session_key=str(uuid.uuid4()))
    answer = await mcp_workflow_select(db, caller=caller, user=await fetch_user(db, member_id),
                                       workspace_id=workspace_id, arguments={"workflow_key": key})
    assert (answer["state"], answer["reason"]) == ("denied", "workflow_archived")
    # A workflow run of an archived key.
    admin = await admin_user(db)
    with pytest.raises(WorkflowRunError) as refused:
        run_workspace_id = await run_workspace(db, admin)
        await start_run(db, user=admin, workflow_key=key,
                        project_id=run_workspace_id, session=await new_chat_session(db, admin, run_workspace_id))
    assert refused.value.code == "workflow_archived"
    # A key nobody ever published stays unknown (not "archived").
    unknown = await resolve_explicit_workflow_selection(db, workflow_key="never-existed")
    assert unknown["status"] == "unknown_key"


async def test_an_action_runs_either_a_workflow_or_an_agent_never_both(db):
    admin, project = await admin_user(db), await _project(db)
    both = {"agent_definition_id": str(uuid.uuid4()), "workflow_run": {"workflow_key": "feature-delivery-tdd"}}
    assert (await action_config_refusal(db, both))["code"] == "action_agent_and_workflow"
    assert await action_config_refusal(db, {"workflow_run": {"workflow_key": "feature-delivery-tdd"}}) is None
    with pytest.raises(ActionAdmissionError) as refused:
        await admit_agent_turn(db, Task(dispatch_binding="task_definition", task_type="agent_run", config=both, owner_id=admin.id, project_id=project.id))
    assert refused.value.code == AGENT_AND_WORKFLOW


async def test_saving_an_action_with_both_is_refused_by_the_api(client, auth_headers, db):
    project = await _project(db)
    saved = await client.post("/api/v1/tasks", headers=auth_headers, json={
        "project_id": project.id, "name": "Both", "task_type": "agent_run", "agent_type": "diagnosis",
        "dispatch_binding": "task_definition",
        "config": {"agent_definition_id": str(uuid.uuid4()), "workflow_run": {"workflow_key": "x"}}})
    assert saved.status_code == 422 and saved.json()["detail"]["code"] == "action_agent_and_workflow"


async def test_the_rest_api_requires_an_explicit_dispatch_binding(client, auth_headers, db):
    project = await _project(db)
    body = {"project_id": project.id, "name": "Bound", "task_type": "agent_run", "agent_type": "diagnosis",
            "config": {"prompt": "Summarize"}}
    missing = await client.post("/api/v1/tasks", headers=auth_headers, json=body)
    assert missing.status_code == 422
    unknown = await client.post("/api/v1/tasks", headers=auth_headers, json={**body, "dispatch_binding": "worker"})
    assert unknown.status_code == 422
    bound = await client.post("/api/v1/tasks", headers=auth_headers, json={**body, "dispatch_binding": "agent_definition"})
    assert bound.status_code == 422 and bound.json()["detail"]["code"] == "dispatch_binding_agent_required"
    created = await client.post("/api/v1/tasks", headers=auth_headers,
                                json={**body, "dispatch_binding": "task_definition"})
    assert created.status_code == 200, created.text
    assert created.json()["dispatch_binding"] == "task_definition"
