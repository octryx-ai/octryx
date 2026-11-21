"""Managed database connectors and predefined query tools."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.connector_test.failure import connection_success, exception_failure
from app.services.database_tool.admin_rules import (
    _effective_connector_config,
    _ensure_connector_name_available,
    _load_connector,
    _load_connector_with_tools,
    _normalize_database_type,
    _update_connector_config,
    _validate_connector_config,
)
from app.services.database_tool.common import (
    DATABASE_TOOL_PREFIX,
    secret_scope,
    serialize_database_connector,
)
from app.services.database_tool.execution import execute_database_query_tool as execute_database_query_tool_internal
from app.services.database_tool.execution import (
    get_connector_engine,
    resolve_connector_config,
)

from ..models import DatabaseConnector
from ..tools.context import ToolContext


async def list_database_connectors(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(DatabaseConnector)
                .options(selectinload(DatabaseConnector.query_tools))
                .order_by(DatabaseConnector.name.asc())
            )
        )
        .scalars()
        .all()
    )
    from app.services.connector_health.service import serialize_connector_health
    from app.services.database_tool.health import database_health_rows

    # The card shows the stored result of a real check, never a constant "Connected".
    health = await database_health_rows(db)
    return [
        {**serialize_database_connector(connector), "health": serialize_connector_health(health.get(connector.id))}
        for connector in rows
    ]


async def create_database_connector(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Connector name is required")
    db_type = _normalize_database_type(payload.get("db_type") or "postgresql")
    _validate_connector_config(db_type=db_type, config=_effective_connector_config(None, payload))
    await _ensure_connector_name_available(db, name=name)
    connector = DatabaseConnector(
        project_id=str(payload.get("project_id") or "").strip() or None,
        name=name,
        description=str(payload.get("description") or "").strip() or None,
        db_type=db_type,
        is_active=bool(payload.get("is_active", True)),
        connection_config={},
    )
    db.add(connector)
    await db.flush()
    await _update_connector_config(db, connector=connector, payload=payload)
    await db.commit()
    refreshed = await _load_connector_with_tools(db, connector.id)
    return serialize_database_connector(refreshed)


async def update_database_connector(db: AsyncSession, connector_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    connector = await _load_connector(db, connector_id)
    next_name = str(payload.get("name") or connector.name).strip()
    if not next_name:
        raise HTTPException(status_code=400, detail="Connector name is required")
    next_db_type = _normalize_database_type(payload.get("db_type") or connector.db_type)
    _validate_connector_config(db_type=next_db_type, config=_effective_connector_config(connector, payload))
    await _ensure_connector_name_available(db, name=next_name, existing_connector_id=connector.id)
    if "name" in payload:
        connector.name = next_name
    if "description" in payload:
        connector.description = str(payload.get("description") or "").strip() or None
    if "db_type" in payload:
        connector.db_type = next_db_type
    if "project_id" in payload:
        connector.project_id = str(payload.get("project_id") or "").strip() or None
    if "is_active" in payload:
        connector.is_active = bool(payload.get("is_active"))
    await _update_connector_config(db, connector=connector, payload=payload)
    await db.commit()
    refreshed = await _load_connector_with_tools(db, connector.id)
    return serialize_database_connector(refreshed)


async def delete_database_connector(db: AsyncSession, connector_id: str) -> dict[str, Any]:
    connector = await _load_connector(db, connector_id)
    await db.delete(connector)
    await db.commit()
    return {"status": "deleted"}


async def test_database_connector(db: AsyncSession, connector_id: str) -> dict[str, Any]:
    connector = await _load_connector(db, connector_id)
    resolved = await resolve_connector_config(db, connector=connector, secret_scope=secret_scope(connector.id))
    engine = await get_connector_engine(connector, resolved)
    try:
        async with engine.connect() as conn:
            result = await asyncio.wait_for(conn.execute(text("SELECT 1 AS ok")), timeout=10)
            row = result.mappings().first() or {}
        if row.get("ok") != 1:
            return {"ok": False, "summary": "Database probe query returned no row."}
        return connection_success("Database connection succeeded.")
    except Exception as exc:
        # Driver errors can carry hosts, DSNs and credentials: only the class name is kept.
        return exception_failure("Database", exc)


async def execute_database_query_tool(tool_name: str, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    if not tool_name.startswith(DATABASE_TOOL_PREFIX):
        return {"error": f"Unknown database tool: {tool_name}"}
    db = getattr(context, "db", None)
    if db is None:
        return {"error": "Database-backed tools require an active platform database session"}
    return await execute_database_query_tool_internal(
        db,
        tool_name=tool_name,
        params=params or {},
        context=context,
    )
