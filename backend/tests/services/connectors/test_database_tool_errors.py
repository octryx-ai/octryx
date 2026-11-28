"""Unknown and invalid runtime parameters are refused, and execution errors are redacted and persisted."""

import uuid

import pytest

from app.models import DatabaseQueryToolRun
from app.services.database_tool import execution as database_tool_execution
from app.services.database_tool.query_tool_admin import create_database_query_tool
from app.services.database_tool_service import create_database_connector, execute_database_query_tool
from app.tools.context import ToolContext
from tests.services.connectors.database_tool_service_support import _create_external_sqlite_db


@pytest.mark.asyncio
async def test_database_tool_rejects_unknown_and_invalid_runtime_parameters(db, tmp_path, auth_user):
    external_db = tmp_path / "runtime-params.sqlite"
    _create_external_sqlite_db(str(external_db), primary_tenant_id=auth_user.id)
    connector = await create_database_connector(
        db,
        payload={
            "name": "runtime-params-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )
    tool = await create_database_query_tool(
        db,
        payload={
            "connector_id": connector["id"],
            "tool_name": "database_tool_runtime_params",
            "description": "Read tenant-scoped orders by status",
            "sql_template": "select id, tenant_id, status from orders where status = :status",
            "parameters_schema": {
                "type": "object",
                "properties": {"status": {"type": "string", "enum": ["open", "closed"]}},
                "required": ["status"],
            },
            "row_level_security_rules": ["tenant_id = $user.id"],
            "allowed_roles": ["admin"],
            "is_active": True,
        },
    )
    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id=str(uuid.uuid4()),
        project_config={},
        db=db,
    )

    unknown_result = await execute_database_query_tool(tool["tool_name"], {"status": "open", "sql": "select 1"}, context)
    assert unknown_result["error"] == "Database tool validation failed: Unknown parameters: sql"
    assert unknown_result["query_run"]["status"] == "failed"

    invalid_type_result = await execute_database_query_tool(tool["tool_name"], {"status": 1}, context)
    assert invalid_type_result["error"] == "Database tool validation failed: Invalid parameter types: status"
    assert invalid_type_result["query_run"]["failure_category"] == "validation_failed"

    invalid_enum_result = await execute_database_query_tool(tool["tool_name"], {"status": "pending"}, context)
    assert invalid_enum_result["error"] == "Database tool validation failed: Invalid parameter types: status"
    failed_run = await db.get(DatabaseQueryToolRun, invalid_enum_result["query_run"]["id"])
    assert failed_run is not None
    assert failed_run.status == "failed"
    assert failed_run.error == "Invalid parameter types: status"


@pytest.mark.asyncio
async def test_database_tool_execution_errors_are_redacted_and_persisted(db, tmp_path, monkeypatch, auth_user):
    external_db = tmp_path / "redacted-error.sqlite"
    _create_external_sqlite_db(str(external_db), primary_tenant_id=auth_user.id)
    connector = await create_database_connector(
        db,
        payload={
            "name": "redacted-error-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )
    tool = await create_database_query_tool(
        db,
        payload={
            "connector_id": connector["id"],
            "tool_name": "database_tool_redacted_error",
            "description": "Forces a provider error with credential-shaped text",
            "sql_template": "select id from orders",
            "parameters_schema": {"type": "object", "properties": {}, "required": []},
            "is_active": True,
        },
    )

    async def failing_engine(_connector, _resolved_config):
        raise RuntimeError(
            "connection failed for postgresql://admin:supersecret@example.invalid/app "
            "password=supersecret token=abc1" + "23456789"
        )

    monkeypatch.setattr(database_tool_execution, "get_connector_engine", failing_engine)
    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id=str(uuid.uuid4()),
        project_config={},
        db=db,
    )

    result = await execute_database_query_tool(tool["tool_name"], {}, context)

    assert "supersecret" not in result["error"]
    assert ("abc1" + "23456789") not in result["error"]
    assert "example.invalid" not in result["error"]
    assert "database_tool_execution_failed error_type=RuntimeError" in result["error"]
    query_run = await db.get(DatabaseQueryToolRun, result["query_run"]["id"])
    assert query_run is not None
    assert query_run.status == "failed"
    assert query_run.failure_category == "query_execution_failed"
    assert query_run.error is not None
    assert "supersecret" not in query_run.error
    assert ("abc1" + "23456789") not in query_run.error
    assert query_run.error == "database_tool_execution_failed error_type=RuntimeError"
    assert query_run.evidence_json["failure_category"] == "query_execution_failed"
