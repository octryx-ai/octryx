"""Shared helpers for the test_specification_engineering_integration_* modules."""

from __future__ import annotations

import pytest

from app.models.runtime.workflow_handoff import WorkflowHandoff, WorkflowHandoffResponse

SPEC_TEXT = "I can inspect its exact evidence"


async def mcp_status(db, run, user):
    from app.services.mcp_governed_knowledge import McpCaller
    from app.services.mcp_workflow_run_tools import mcp_workflow_run_status

    caller = McpCaller(user_id=user.id, grant_id=None, scopes=("knowledge:read",),
                       bound_project_ids=(run.project_id,), workspace_header=run.project_id)
    result = await mcp_workflow_run_status(db, caller=caller, user=user, workspace_id=run.project_id,
                                           arguments={"run_id": run.id})
    assert result["state"] == "ok", result
    return result["workflow_run"]


@pytest.fixture(autouse=True)
async def tables(db):
    connection = await db.connection()
    await connection.run_sync(lambda bind: [table.create(bind, checkfirst=True) for table in
        (WorkflowHandoff.__table__, WorkflowHandoffResponse.__table__)])


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
