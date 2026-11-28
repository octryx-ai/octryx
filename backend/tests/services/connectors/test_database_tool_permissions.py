from __future__ import annotations

import uuid

import pytest

from app.models import Project, User
from app.services.database_tool.query_tool_admin import create_database_query_tool
from app.services.database_tool_service import create_database_connector, execute_database_query_tool
from app.tools.context import ToolContext
from tests.services.connectors.database_tool_service_support import _create_external_sqlite_db


def _context(db, user_id: str, project_ids: list[str], roles: list[str]) -> ToolContext:
    return ToolContext(
        user_id=user_id,
        project_ids=project_ids,
        roles=roles,
        session_id=str(uuid.uuid4()),
        project_config={},
        db=db,
    )


async def _seed_matrix_tool(db, project_id: str, external_db) -> tuple[dict, dict]:
    connector = await create_database_connector(
        db,
        payload={
            "project_id": project_id,
            "name": "enterprise-matrix-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )
    tool = await create_database_query_tool(
        db,
        payload={
            "connector_id": connector["id"],
            "tool_name": "database_tool_enterprise_matrix",
            "description": "Enterprise matrix query",
            "sql_template": "select id, tenant_id, status from orders where status = :status",
            "parameters_schema": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
            },
            "row_level_security_rules": ["tenant_id = $user.id"],
            "allowed_roles": ["analyst"],
            "project_id": project_id,
            "max_rows": 1,
            "timeout_seconds": 10,
            "is_active": True,
        },
    )
    return connector, tool


async def _seed_hidden_tools(db, project_id: str, external_db, connector_id: str) -> tuple[dict, dict]:
    inactive_connector = await create_database_connector(
        db,
        payload={
            "project_id": project_id,
            "name": "enterprise-matrix-inactive-connector",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": False,
        },
    )
    inactive_connector_tool = await create_database_query_tool(
        db,
        payload={
            "connector_id": inactive_connector["id"],
            "tool_name": "database_tool_inactive_connector_matrix",
            "description": "Should be hidden because connector is inactive",
            "sql_template": "select id from orders",
            "parameters_schema": {"type": "object", "properties": {}, "required": []},
            "project_id": project_id,
            "is_active": True,
        },
    )
    inactive_tool = await create_database_query_tool(
        db,
        payload={
            "connector_id": connector_id,
            "tool_name": "database_tool_inactive_tool_matrix",
            "description": "Should be hidden because tool is inactive",
            "sql_template": "select id from orders",
            "parameters_schema": {"type": "object", "properties": {}, "required": []},
            "project_id": project_id,
            "is_active": False,
        },
    )
    return inactive_connector_tool, inactive_tool


@pytest.mark.asyncio
async def test_database_query_tool_enterprise_permission_matrix(db, tmp_path, auth_user):
    other_user = User(
        username=f"db-matrix-{uuid.uuid4().hex[:8]}",
        email=f"db-matrix-{uuid.uuid4().hex[:8]}@example.invalid",
        password_hash="x",
    )
    project = Project(id=str(uuid.uuid4()), name=f"db-matrix-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    other_project = Project(id=str(uuid.uuid4()), name=f"db-matrix-other-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add_all([other_user, project, other_project])
    await db.commit()
    external_db = tmp_path / "enterprise-matrix.sqlite"
    _create_external_sqlite_db(str(external_db), primary_tenant_id=auth_user.id)
    connector, tool = await _seed_matrix_tool(db, project.id, external_db)
    inactive_connector_tool, inactive_tool = await _seed_hidden_tools(db, project.id, external_db, connector["id"])

    allowed_context = _context(db, auth_user.id, [project.id], ["analyst"])

    allowed_result = await execute_database_query_tool(tool["tool_name"], {"status": "open"}, allowed_context)
    assert allowed_result["row_count"] == 1
    assert allowed_result["max_rows"] == 1
    assert allowed_result["query_run"]["status"] == "succeeded"

    missing_param_result = await execute_database_query_tool(tool["tool_name"], {}, allowed_context)
    assert missing_param_result["error"] == "Database tool validation failed: Missing required parameters: status"
    assert missing_param_result["query_run"]["failure_category"] == "validation_failed"

    role_denied_context = _context(db, auth_user.id, [project.id], ["viewer"])
    role_denied_result = await execute_database_query_tool(tool["tool_name"], {"status": "open"}, role_denied_context)
    assert role_denied_result == {"error": f"Tool '{tool['tool_name']}' is not available for the current user context"}

    project_denied_context = _context(db, auth_user.id, [other_project.id], ["analyst"])
    project_denied_result = await execute_database_query_tool(
        tool["tool_name"], {"status": "open"}, project_denied_context
    )
    assert project_denied_result == {"error": f"Tool '{tool['tool_name']}' is not available for the current user context"}

    rls_miss_context = _context(db, other_user.id, [project.id], ["analyst"])
    rls_miss_result = await execute_database_query_tool(tool["tool_name"], {"status": "open"}, rls_miss_context)
    assert rls_miss_result["row_count"] == 0
    assert rls_miss_result["query_run"]["status"] == "succeeded"

    inactive_connector_result = await execute_database_query_tool(
        inactive_connector_tool["tool_name"], {}, allowed_context
    )
    assert inactive_connector_result == {"error": f"Unknown database tool: {inactive_connector_tool['tool_name']}"}

    inactive_tool_result = await execute_database_query_tool(inactive_tool["tool_name"], {}, allowed_context)
    assert inactive_tool_result == {"error": f"Unknown database tool: {inactive_tool['tool_name']}"}
