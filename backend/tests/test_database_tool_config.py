"""Database connector URLs, runtime profiles and secret scopes, and admin validation of connector and query tool configuration."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.models import Project, StoredSecret, User
from app.services.database_tool.common import secret_scope
from app.services.database_tool.connector_engine import connector_url_from_config
from app.services.database_tool.query_tool_admin import create_database_query_tool, update_database_query_tool
from app.services.database_tool.runtime_policy import database_runtime_profile
from app.services.database_tool_service import create_database_connector, update_database_connector
from tests.database_tool_service_support import _create_external_sqlite_db


def test_database_connector_url_preserves_special_character_password():
    url = connector_url_from_config(
        "postgresql",
        {
            "host": "db.example.internal",
            "port": 5432,
            "database": "shop",
            "username": "shop",
            "password": "shop@test12345",
        },
    )

    assert "***" not in url
    assert make_url(url).password == "shop@test12345"


def test_database_runtime_profile_labels_postgres_and_sqlite_boundaries():
    postgres_profile = database_runtime_profile("postgresql")
    sqlite_profile = database_runtime_profile("sqlite")

    assert postgres_profile["enterprise_acceptance"] is True
    assert postgres_profile["acceptance_mode"] == "production_postgres"
    assert sqlite_profile["enterprise_acceptance"] is False
    assert sqlite_profile["acceptance_mode"] == "local_fixture_only"
    assert sqlite_profile["sqlite_boundary"] == "local_or_test_fixture"


@pytest.mark.asyncio
async def test_database_connector_secret_scope_fits_stored_secret_metadata(db):
    connector = await create_database_connector(
        db,
        payload={
            "name": "postgres-secret-scope",
            "db_type": "postgresql",
            "host": "db.example.internal",
            "database": "example",
            "username": "readonly_user",
            "password": "secret-value",
            "is_active": True,
        },
    )

    scope = secret_scope(connector["id"])
    assert len(scope) > 50
    secret = (
        await db.execute(
            select(StoredSecret).where(
                StoredSecret.tool_name == scope,
                StoredSecret.field_name == "password",
            )
        )
    ).scalar_one()

    assert secret.secret_type == scope
    assert connector["secret_status"]["password"] is True
    assert "password" not in connector["public_fields"]
    assert connector["runtime_profile"]["enterprise_acceptance"] is True
    assert connector["runtime_profile"]["acceptance_mode"] == "production_postgres"


@pytest.mark.asyncio
async def test_database_admin_rejects_invalid_connector_config_and_duplicate_names(db, tmp_path):
    external_db = tmp_path / "admin-validation.sqlite"
    _create_external_sqlite_db(str(external_db), primary_tenant_id="tenant-1")

    with pytest.raises(Exception, match="Unsupported database type"):
        await create_database_connector(
            db,
            payload={"name": "invalid-db-type", "db_type": "oracle", "is_active": True},
        )

    with pytest.raises(Exception, match="SQLite connectors require"):
        await create_database_connector(
            db,
            payload={"name": "missing-sqlite-path", "db_type": "sqlite", "is_active": True},
        )

    await create_database_connector(
        db,
        payload={
            "name": "unique-admin-validation",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )

    with pytest.raises(Exception, match="Database connector name already exists"):
        await create_database_connector(
            db,
            payload={
                "name": "unique-admin-validation",
                "db_type": "sqlite",
                "file_path": str(external_db),
                "is_active": True,
            },
        )

    dsn_connector = await create_database_connector(
        db,
        payload={
            "name": "dsn-admin-validation",
            "db_type": "postgresql",
            "dsn": "postgresql://readonly:secret@example.invalid/app",
            "is_active": True,
        },
    )

    with pytest.raises(Exception, match="postgresql connectors require"):
        await update_database_connector(db, dsn_connector["id"], {"clear_dsn": True})


@pytest.mark.asyncio
async def test_database_admin_rejects_unsafe_query_tool_config(db, tmp_path):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project_one = Project(id=str(uuid.uuid4()), name=f"db-admin-one-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    project_two = Project(id=str(uuid.uuid4()), name=f"db-admin-two-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add_all([project_one, project_two])
    await db.commit()
    external_db = tmp_path / "query-admin-validation.sqlite"
    _create_external_sqlite_db(str(external_db), primary_tenant_id=admin_user.id)
    connector = await create_database_connector(
        db,
        payload={
            "project_id": project_one.id,
            "name": "query-admin-validation-sqlite",
            "db_type": "sqlite",
            "file_path": str(external_db),
            "is_active": True,
        },
    )
    tool = await create_database_query_tool(
        db,
        payload={
            "connector_id": connector["id"],
            "tool_name": "database_tool_admin_validation",
            "description": "Valid baseline",
            "sql_template": "select id from orders",
            "parameters_schema": {"type": "object", "properties": {}, "required": []},
            "allowed_roles": ["admin"],
            "project_id": project_one.id,
            "is_active": True,
        },
    )

    with pytest.raises(Exception, match="project_id must match"):
        await create_database_query_tool(
            db,
            payload={
                "connector_id": connector["id"],
                "tool_name": "database_tool_cross_project",
                "description": "Should fail due to connector scope",
                "sql_template": "select id from orders",
                "parameters_schema": {"type": "object", "properties": {}, "required": []},
                "project_id": project_two.id,
                "is_active": True,
            },
        )

    with pytest.raises(Exception, match="Invalid role name"):
        await update_database_query_tool(db, tool["id"], {"allowed_roles": ["admin", "bad role"]})

    with pytest.raises(Exception, match="max_rows must be between"):
        await update_database_query_tool(db, tool["id"], {"max_rows": 0})

    with pytest.raises(Exception, match="timeout_seconds must be between"):
        await update_database_query_tool(db, tool["id"], {"timeout_seconds": 301})

    with pytest.raises(Exception, match="Database query tool name already exists"):
        await create_database_query_tool(
            db,
            payload={
                "connector_id": connector["id"],
                "tool_name": "database_tool_admin_validation",
                "description": "Duplicate name",
                "sql_template": "select id from orders",
                "parameters_schema": {"type": "object", "properties": {}, "required": []},
                "project_id": project_one.id,
                "is_active": True,
            },
        )
