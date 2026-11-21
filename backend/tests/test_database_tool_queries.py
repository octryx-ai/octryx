"""Predefined query execution with RLS, SQL template parameter checks, bounded audit previews and refused comments and non-SELECT queries."""

import sqlite3
import uuid

import pytest
from sqlalchemy import select

from app.models import DatabaseQueryToolRun, User
from app.services.database_tool.query_tool_admin import create_database_query_tool
from app.services.database_tool_service import create_database_connector, execute_database_query_tool
from app.tools.context import ToolContext
from tests.database_tool_service_support import _create_external_sqlite_db


@pytest.mark.asyncio
async def test_database_tool_executes_predefined_query_with_rls(db, tmp_path):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    external_db = tmp_path / "orders.sqlite"
    _create_external_sqlite_db(str(external_db), primary_tenant_id=admin_user.id)

    connector = await create_database_connector(
        db,
        payload={
            "name": "orders-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )
    tool = await create_database_query_tool(
        db,
        payload={
            "connector_id": connector["id"],
            "tool_name": "database_tool_orders_by_status",
            "description": "Read tenant-scoped orders by status",
            "sql_template": "select id, tenant_id, role_name, team_name, status from orders where status = :status",
            "parameters_schema": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
            },
            "row_level_security_rules": ["tenant_id = $user.id", "role_name in $roles"],
            "allowed_roles": ["admin"],
            "max_rows": 20,
            "timeout_seconds": 10,
            "is_active": True,
        },
    )

    context = ToolContext(
        user_id=admin_user.id,
        project_ids=[],
        roles=["admin"],
        session_id=str(uuid.uuid4()),
        project_config={},
        db=db,
    )

    result = await execute_database_query_tool(tool["tool_name"], {"status": "open"}, context)

    assert result["row_count"] == 1
    assert result["rows"][0]["tenant_id"] == admin_user.id
    assert result["rows"][0]["status"] == "open"
    assert result["runtime_profile"]["enterprise_acceptance"] is False
    assert result["runtime_profile"]["acceptance_mode"] == "local_fixture_only"
    assert result["query_run"]["status"] == "succeeded"
    query_run = await db.get(DatabaseQueryToolRun, result["query_run"]["id"])
    assert query_run is not None
    assert query_run.tool_name == tool["tool_name"]
    assert query_run.connector_id == connector["id"]
    assert query_run.status == "succeeded"
    assert query_run.row_count == 1
    assert query_run.applied_rls_rules == ["tenant_id = $user.id", "role_name in $roles"]
    assert query_run.evidence_json["row_preview_count"] == 1
    assert query_run.evidence_json["row_preview_truncated"] is False
    assert query_run.evidence_json["row_preview"][0]["status"] == "open"


@pytest.mark.asyncio
async def test_database_tool_rejects_undeclared_sql_template_parameters(db, tmp_path):
    external_db = tmp_path / "undeclared-params.sqlite"
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    _create_external_sqlite_db(str(external_db), primary_tenant_id=admin_user.id)
    connector = await create_database_connector(
        db,
        payload={
            "name": "undeclared-params-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )

    with pytest.raises(Exception, match="undeclared parameters"):
        await create_database_query_tool(
            db,
            payload={
                "connector_id": connector["id"],
                "tool_name": "database_tool_undeclared_status",
                "description": "Should fail because status is not declared",
                "sql_template": "select id from orders where status = :status",
                "parameters_schema": {"type": "object", "properties": {}, "required": []},
                "is_active": True,
            },
        )


@pytest.mark.asyncio
async def test_database_tool_audit_bounds_row_preview_without_truncating_result(db, tmp_path):
    external_db = tmp_path / "audit-preview.sqlite"
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    _create_external_sqlite_db(str(external_db), primary_tenant_id=admin_user.id)
    conn = sqlite3.connect(str(external_db))
    try:
        for index in range(8):
            conn.execute(
                "insert into orders (tenant_id, role_name, team_name, status) values (?, ?, ?, ?)",
                (admin_user.id, "admin", "ops", f"preview-{index}"),
            )
        conn.commit()
    finally:
        conn.close()
    connector = await create_database_connector(
        db,
        payload={
            "name": "audit-preview-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )
    tool = await create_database_query_tool(
        db,
        payload={
            "connector_id": connector["id"],
            "tool_name": "database_tool_audit_preview",
            "description": "Read rows to verify bounded audit preview",
            "sql_template": "select id, tenant_id, role_name, team_name, status from orders",
            "parameters_schema": {"type": "object", "properties": {}, "required": []},
            "max_rows": 20,
            "is_active": True,
        },
    )
    context = ToolContext(
        user_id=admin_user.id,
        project_ids=[],
        roles=["admin"],
        session_id=str(uuid.uuid4()),
        project_config={},
        db=db,
    )

    result = await execute_database_query_tool(tool["tool_name"], {}, context)

    assert result["row_count"] == 11
    query_run = await db.get(DatabaseQueryToolRun, result["query_run"]["id"])
    assert query_run is not None
    assert query_run.row_count == 11
    assert len(result["rows"]) == 11
    assert len(query_run.evidence_json["row_preview"]) == 5
    assert query_run.evidence_json["row_preview_count"] == 5
    assert query_run.evidence_json["row_preview_truncated"] is True


@pytest.mark.asyncio
async def test_database_tool_rejects_sql_comments_and_invalid_parameter_schema(db, tmp_path):
    external_db = tmp_path / "invalid-template-schema.sqlite"
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    _create_external_sqlite_db(str(external_db), primary_tenant_id=admin_user.id)
    connector = await create_database_connector(
        db,
        payload={
            "name": "invalid-template-schema-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )

    with pytest.raises(Exception, match="SQL comments are not allowed"):
        await create_database_query_tool(
            db,
            payload={
                "connector_id": connector["id"],
                "tool_name": "database_tool_commented",
                "description": "Should fail because comments can hide unsafe SQL",
                "sql_template": "select id from orders -- comment",
                "parameters_schema": {"type": "object", "properties": {}, "required": []},
                "is_active": True,
            },
        )

    with pytest.raises(Exception, match="unsupported type"):
        await create_database_query_tool(
            db,
            payload={
                "connector_id": connector["id"],
                "tool_name": "database_tool_bad_schema",
                "description": "Should fail because nested objects are not accepted",
                "sql_template": "select id from orders",
                "parameters_schema": {
                    "type": "object",
                    "properties": {"filters": {"type": "object"}},
                    "required": [],
                },
                "is_active": True,
            },
        )


@pytest.mark.asyncio
async def test_database_tool_rejects_non_select_queries(db, tmp_path):
    external_db = tmp_path / "invalid.sqlite"
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    _create_external_sqlite_db(str(external_db), primary_tenant_id=admin_user.id)
    connector = await create_database_connector(
        db,
        payload={
            "name": "invalid-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )

    with pytest.raises(Exception):
        await create_database_query_tool(
            db,
            payload={
                "connector_id": connector["id"],
                "tool_name": "database_tool_invalid",
                "description": "Should fail",
                "sql_template": "delete from orders",
                "parameters_schema": {"type": "object", "properties": {}, "required": []},
                "is_active": True,
            },
        )
