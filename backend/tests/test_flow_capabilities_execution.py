"""The workflow capability tool falls back to the person's question, runs the published flow with an audit, prefers the active session's project and respects the project tool policy."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, OrchestratorAgentRun, Session
from app.services.flow_capabilities import _capability_initial_input, execute_flow_capability_tool
from app.services.flow_definitions import publish_flow_definition_version
from app.tools.context import ToolContext
from app.tools.registry import execute_tool_with_plugins
from tests.flow_capabilities_support import _admin_user, _make_draft_flow, _tool_context
from tests.knowledge_evidence_seed_support import seed_workspace


def test_workflow_capability_initial_input_falls_back_to_current_person_question():
    context = ToolContext(
        user_id="admin",
        project_ids=[],
        roles=[],
        session_id="session-capability",
        project_config={},
        current_user_message="Who is Alice Example?",
    )

    initial_input = _capability_initial_input(
        {},
        context=context,
        capability={"tool_name": "run_flow_person_source_evidence_research", "name": "Person research"},
    )

    assert initial_input["request"] == "Who is Alice Example?"
    assert initial_input["subject_hint"] == "Alice Example"


@pytest.mark.asyncio
async def test_workflow_capability_tool_runs_published_flow_and_audits(db):
    admin_user = await _admin_user(db)
    _, version = _make_draft_flow(db, created_by=admin_user.id)
    await publish_flow_definition_version(db, version_id=version.id, current_user=admin_user)

    workspace_id = await seed_workspace(db)  # the run starts in the caller's Workspace
    result = await execute_flow_capability_tool(
        db,
        tool_name="run_flow_person_research",
        params={"request": {"person": "Alice Example"}},
        context=_tool_context(db, project_id=workspace_id, user_id=admin_user.id),
    )

    assert result["workflow_capability"]["version_id"] == version.id
    assert result["flow_run"]["status"] == "completed"
    assert result["result"]["final"] == {"result": {"result": {"person": "Alice Example"}}}
    assert await db.get(Session, "session-capability") is not None
    audit_actions = [row.action for row in (await db.execute(select(AuditLog))).scalars().all()]
    assert "workflow.capability_run_started" in audit_actions
    assert "workflow.capability_run_completed" in audit_actions


@pytest.mark.asyncio
async def test_workflow_capability_uses_active_session_project_before_user_project_list(db):
    admin_user = await _admin_user(db)
    _, version = _make_draft_flow(db, created_by=admin_user.id)
    await publish_flow_definition_version(db, version_id=version.id, current_user=admin_user)
    active_project, first_project = await seed_workspace(db), await seed_workspace(db)
    db.add(
        Session(
            id="session-active-project",
            user_id=admin_user.id,
            project_id=active_project,
            agent_type="admin",
            status="active",
        )
    )
    await db.flush()
    context = ToolContext(
        user_id=admin_user.id,
        project_ids=[first_project, active_project],
        roles=[],
        session_id="session-active-project",
        project_config={},
        db=db,
        capability_type="admin",
    )

    result = await execute_flow_capability_tool(
        db,
        tool_name="run_flow_person_research",
        params={"request": {"person": "Alice Example"}},
        context=context,
    )

    run = await db.get(OrchestratorAgentRun, result["flow_run"]["id"])
    assert run is not None
    assert run.project_id == active_project


@pytest.mark.asyncio
async def test_workflow_capability_respects_project_tool_policy(db):
    admin_user = await _admin_user(db)
    _, version = _make_draft_flow(db, created_by=admin_user.id)
    await publish_flow_definition_version(db, version_id=version.id, current_user=admin_user)
    context = _tool_context(db)
    context.project_config = {"tool_policy": {"deny_patterns": ["run_flow_*"]}}

    result = await execute_tool_with_plugins("run_flow_person_research", {"request": {"person": "Ada"}}, context)

    assert result["error"] == "Denied by a project tool visibility deny pattern."
    assert result["policy"] == "project_tool_policy"
