"""A connector step runs in its task's Workspace: a Workspace-scoped tool (knowledge_search) finds it, although the
step's session is the task run and no chat session."""

from __future__ import annotations

import pytest

from app.scheduler.execution._step_connector_execution import execute_connector_action
from tests.phased_workflow_fixtures import admin_user, run_workspace
from tests.step_executor_support import make_step, make_task, make_task_run


async def _search(db, project_id):
    admin = await admin_user(db)
    step = make_step(step_type="connector_fetch", connector_action="knowledge_search")
    step.connector_params = {"query": "shipping"}
    return await execute_connector_action(
        step=step, context={}, db=db, task=make_task(project_id=project_id, owner_id=admin.id),
        task_run=make_task_run(), render_template_params=lambda params, _context: params)


@pytest.mark.asyncio
async def test_knowledge_search_in_a_connector_step_searches_the_tasks_workspace(db):
    workspace_id = await run_workspace(db, await admin_user(db))
    result = await _search(db, workspace_id)
    assert result.get("state") in ("ok", "no_sources", "needs_configuration", "projection_pending"), result
    assert result.get("workspace_id", workspace_id) == workspace_id


@pytest.mark.asyncio
async def test_a_task_without_a_workspace_still_has_none_in_scope(db):
    result = await _search(db, None)
    assert result["state"] == "not_found"
