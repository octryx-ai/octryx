"""Removing a database is audited and releases its stored password; recent queries read in words."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AuditLog, DatabaseConnector, StoredSecret, User
from app.models.runtime.database_connector import DatabaseQueryToolRun
from app.services.database_tool.lifecycle import recent_query_runs, remove_database
from app.services.database_tool.query_tool_admin import create_database_query_tool, delete_database_query_tool
from app.services.database_tool_service import create_database_connector


@pytest.mark.asyncio
async def test_remove_writes_an_audit_row_and_releases_the_password(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    created = await create_database_connector(db, {
        "name": f"reporting-{uuid.uuid4().hex[:6]}", "db_type": "postgresql", "host": "db.invalid",
        "database": "reporting", "username": "reader", "password": "pw-value",
    })
    connector = await db.get(DatabaseConnector, created["id"])
    secret_ids = [value for key, value in connector.connection_config.items() if key.endswith("_secret_ref")]
    assert secret_ids, "the password is stored as a secret reference"
    tool = await create_database_query_tool(db, {
        "connector_id": connector.id, "tool_name": f"database_tool_open_{uuid.uuid4().hex[:6]}",
        "description": "Open items", "sql_template": "SELECT 1 AS one",
    })
    db.add(DatabaseQueryToolRun(query_tool_id=tool["id"], connector_id=connector.id, tool_name=tool["tool_name"],
                                connector_name=connector.name, db_type="postgresql", status="succeeded",
                                row_count=500, max_rows=500, actor_user_id=admin.id))
    await db.commit()

    recent = await recent_query_runs(db)
    assert recent[0]["database"] == connector.name
    assert (recent[0]["rows"], recent[0]["limit_reached"], recent[0]["who"]) == (500, True, "admin")

    with pytest.raises(HTTPException) as in_use:
        await remove_database(db, connector_id=connector.id, actor_user_id=admin.id)
    assert in_use.value.status_code == 409
    assert in_use.value.detail["query_tools"] == [tool["tool_name"]]
    await delete_database_query_tool(db, tool["id"])

    result = await remove_database(db, connector_id=connector.id, actor_user_id=admin.id)

    assert result["status"] == "deleted"
    assert await db.get(DatabaseConnector, connector.id) is None
    assert (await db.execute(select(StoredSecret).where(StoredSecret.id.in_(secret_ids)))).scalars().all() == []
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "admin.database_connector.deleted",
                                                AuditLog.resource_id == connector.id))
    ).scalar_one()
    assert audit.user_id == admin.id
