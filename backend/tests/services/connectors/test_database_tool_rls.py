"""Row-level security rules: invalid rules, fail-closed missing context, group and identity group attributes and registry dispatch."""

import sqlite3
import uuid

import pytest

from app.models import DatabaseQueryToolRun, IdentityGroup, Team, TeamMember, UserGroup
from app.services.database_tool.query_tool_admin import create_database_query_tool
from app.services.database_tool_service import create_database_connector, execute_database_query_tool
from app.tools.context import ToolContext
from app.tools.registry import execute_tool_with_plugins
from tests.services.connectors.database_tool_service_support import _create_external_sqlite_db


@pytest.mark.asyncio
async def test_database_tool_rejects_invalid_rls_rules(db, tmp_path, auth_user):
    external_db = tmp_path / "invalid-rls.sqlite"
    _create_external_sqlite_db(str(external_db), primary_tenant_id=auth_user.id)
    connector = await create_database_connector(
        db,
        payload={
            "name": "invalid-rls-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )

    with pytest.raises(Exception, match="RLS rule must be"):
        await create_database_query_tool(
            db,
            payload={
                "connector_id": connector["id"],
                "tool_name": "database_tool_invalid_rls_shape",
                "description": "Should fail because RLS is not a supported token comparison",
                "sql_template": "select id from orders",
                "parameters_schema": {"type": "object", "properties": {}, "required": []},
                "row_level_security_rules": ["tenant_id = 'literal'"],
                "is_active": True,
            },
        )

    with pytest.raises(Exception, match="Unsupported RLS token"):
        await create_database_query_tool(
            db,
            payload={
                "connector_id": connector["id"],
                "tool_name": "database_tool_invalid_rls_token",
                "description": "Should fail because the token is not supported",
                "sql_template": "select id from orders",
                "parameters_schema": {"type": "object", "properties": {}, "required": []},
                "row_level_security_rules": ["tenant_id = $unknown.token"],
                "is_active": True,
            },
        )


@pytest.mark.asyncio
async def test_database_tool_rls_fails_closed_for_missing_context(db, tmp_path, auth_user):
    external_db = tmp_path / "missing-rls-context.sqlite"
    _create_external_sqlite_db(str(external_db), primary_tenant_id=auth_user.id)
    connector = await create_database_connector(
        db,
        payload={
            "name": "missing-rls-context-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )
    user_tool = await create_database_query_tool(
        db,
        payload={
            "connector_id": connector["id"],
            "tool_name": "database_tool_missing_user_context",
            "description": "Requires a known platform user",
            "sql_template": "select id, tenant_id from orders",
            "parameters_schema": {"type": "object", "properties": {}, "required": []},
            "row_level_security_rules": ["tenant_id = $user.id"],
            "is_active": True,
        },
    )
    role_tool = await create_database_query_tool(
        db,
        payload={
            "connector_id": connector["id"],
            "tool_name": "database_tool_missing_role_context",
            "description": "Requires at least one role value",
            "sql_template": "select id, role_name from orders",
            "parameters_schema": {"type": "object", "properties": {}, "required": []},
            "row_level_security_rules": ["role_name in $roles"],
            "is_active": True,
        },
    )

    missing_user_context = ToolContext(
        user_id=str(uuid.uuid4()),
        project_ids=[],
        roles=["admin"],
        session_id=str(uuid.uuid4()),
        project_config={},
        db=db,
    )
    missing_user_result = await execute_database_query_tool(user_tool["tool_name"], {}, missing_user_context)
    assert missing_user_result["error"] == "Database tool validation failed: RLS context user was not found"
    assert missing_user_result["query_run"]["failure_category"] == "validation_failed"

    missing_role_context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=[],
        session_id=str(uuid.uuid4()),
        project_config={},
        db=db,
    )
    missing_role_result = await execute_database_query_tool(role_tool["tool_name"], {}, missing_role_context)
    assert missing_role_result["error"] == "Database tool validation failed: RLS context token $roles has no values"
    failed_role_run = await db.get(DatabaseQueryToolRun, missing_role_result["query_run"]["id"])
    assert failed_role_run is not None
    assert failed_role_run.status == "failed"
    assert failed_role_run.error == "RLS context token $roles has no values"


@pytest.mark.asyncio
async def test_database_tool_supports_group_rls_and_registry_dispatch(db, tmp_path, auth_user):
    team = Team(name=f"ops-{uuid.uuid4().hex[:6]}", description="Ops", created_by=auth_user.id)
    db.add(team)
    await db.flush()
    db.add(TeamMember(team_id=team.id, user_id=auth_user.id, role="member"))
    await db.commit()
    external_db = tmp_path / "groups.sqlite"
    _create_external_sqlite_db(str(external_db), primary_tenant_id=auth_user.id, primary_team=team.name)

    connector = await create_database_connector(
        db,
        payload={
            "name": "group-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )
    await create_database_query_tool(
        db,
        payload={
            "connector_id": connector["id"],
            "tool_name": "database_tool_orders_by_team",
            "description": "Read team-scoped orders",
            "sql_template": "select id, tenant_id, role_name, team_name, status from orders",
            "parameters_schema": {"type": "object", "properties": {}, "required": []},
            "row_level_security_rules": ["team_name in $groups"],
            "max_rows": 20,
            "timeout_seconds": 10,
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

    result = await execute_tool_with_plugins("database_tool_orders_by_team", {}, context)

    assert "error" not in result
    assert result["row_count"] == 2
    assert {row["team_name"] for row in result["rows"]} == {team.name}


@pytest.mark.asyncio
async def test_database_tool_supports_identity_group_rls_attributes(db, tmp_path, auth_user):
    group_one = IdentityGroup(
        name=f"tenant-{uuid.uuid4().hex[:6]}",
        description="Tenant scoped operators",
        is_active=True,
        rls_attributes_json=[{"key": "tenantid", "value": "tenant-11"}],
    )
    group_two = IdentityGroup(
        name=f"tenant-{uuid.uuid4().hex[:6]}",
        description="Additional tenant scope",
        is_active=True,
        rls_attributes_json=[{"key": "tenantid", "value": "tenant-12"}],
    )
    db.add_all([group_one, group_two])
    await db.flush()
    db.add(UserGroup(user_id=auth_user.id, group_id=group_one.id))
    db.add(UserGroup(user_id=auth_user.id, group_id=group_two.id))
    await db.commit()

    external_db = tmp_path / "tenant-attributes.sqlite"
    _create_external_sqlite_db(str(external_db), primary_tenant_id="tenant-11")
    conn = sqlite3.connect(str(external_db))
    try:
        conn.execute(
            "insert into orders (tenant_id, role_name, team_name, status) values (?, ?, ?, ?)",
            ("tenant-12", "admin", "ops", "open"),
        )
        conn.commit()
    finally:
        conn.close()
    connector = await create_database_connector(
        db,
        payload={
            "name": "tenant-attribute-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )
    await create_database_query_tool(
        db,
        payload={
            "connector_id": connector["id"],
            "tool_name": "database_tool_orders_by_group_tenant",
            "description": "Read tenant-scoped orders from identity group RLS attributes",
            "sql_template": "select id, tenant_id, role_name, team_name, status from orders",
            "parameters_schema": {"type": "object", "properties": {}, "required": []},
            "row_level_security_rules": ["tenant_id in $group.rls.tenantid"],
            "max_rows": 20,
            "timeout_seconds": 10,
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

    result = await execute_tool_with_plugins("database_tool_orders_by_group_tenant", {}, context)

    assert "error" not in result
    assert result["row_count"] == 3
    assert {row["tenant_id"] for row in result["rows"]} == {"tenant-11", "tenant-12"}
