"""Admin CRUD of predefined database query tools and their dynamic tool definitions."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.database_tool.admin_rules import (
    MAX_DATABASE_TOOL_ROWS,
    MAX_DATABASE_TOOL_TIMEOUT_SECONDS,
    _ensure_tool_name_available,
    _load_connector,
    _load_query_tool,
    _normalize_allowed_roles,
    _normalize_database_tool_limit,
    _validate_query_tool_project_scope,
)
from app.services.database_tool.common import (
    normalize_parameter_schema,
    normalize_rls_rules,
    serialize_database_query_tool,
    tool_visible_to_context,
    validate_sql_template,
    validate_tool_name,
)

from ...models import DatabaseConnector, DatabaseQueryTool
from ...tools.context import ToolContext


async def list_database_query_tools(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(DatabaseQueryTool)
                .options(selectinload(DatabaseQueryTool.connector))
                .order_by(DatabaseQueryTool.tool_name.asc())
            )
        )
        .scalars()
        .all()
    )
    return [serialize_database_query_tool(tool) for tool in rows]


async def create_database_query_tool(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    connector_id = str(payload.get("connector_id") or "").strip()
    if not connector_id:
        raise HTTPException(status_code=400, detail="connector_id is required")
    connector = await _load_connector(db, connector_id)
    parameters_schema = normalize_parameter_schema(payload.get("parameters_schema"), strict=True)
    tool_name = validate_tool_name(str(payload.get("tool_name") or ""))
    await _ensure_tool_name_available(db, tool_name=tool_name)
    project_id = str(payload.get("project_id") or "").strip() or connector.project_id
    _validate_query_tool_project_scope(connector=connector, project_id=project_id)
    tool = DatabaseQueryTool(
        connector_id=connector.id,
        project_id=project_id,
        tool_name=tool_name,
        display_name=str(payload.get("display_name") or "").strip() or None,
        description=str(payload.get("description") or "").strip(),
        sql_template=validate_sql_template(str(payload.get("sql_template") or ""), parameters_schema),
        parameters_schema=parameters_schema,
        row_level_security_rules=normalize_rls_rules(payload.get("row_level_security_rules"), strict=True),
        allowed_roles=_normalize_allowed_roles(payload.get("allowed_roles")),
        max_rows=_normalize_database_tool_limit(
            payload.get("max_rows"), field_name="max_rows", default=100, maximum=MAX_DATABASE_TOOL_ROWS
        ),
        timeout_seconds=_normalize_database_tool_limit(
            payload.get("timeout_seconds"),
            field_name="timeout_seconds",
            default=30,
            maximum=MAX_DATABASE_TOOL_TIMEOUT_SECONDS,
        ),
        is_active=bool(payload.get("is_active", True)),
    )
    db.add(tool)
    await db.commit()
    refreshed = await _load_query_tool(db, tool.id)
    return serialize_database_query_tool(refreshed)


async def update_database_query_tool(db: AsyncSession, tool_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    tool = await _load_query_tool(db, tool_id)
    connector = tool.connector
    if "connector_id" in payload:
        connector = await _load_connector(db, str(payload.get("connector_id") or ""))
        tool.connector_id = connector.id
        if "project_id" not in payload and not tool.project_id:
            tool.project_id = connector.project_id
    if "project_id" in payload:
        tool.project_id = str(payload.get("project_id") or "").strip() or None
    _validate_query_tool_project_scope(connector=connector, project_id=tool.project_id)
    if "tool_name" in payload:
        tool_name = validate_tool_name(str(payload.get("tool_name") or tool.tool_name))
        await _ensure_tool_name_available(db, tool_name=tool_name, existing_tool_id=tool.id)
        tool.tool_name = tool_name
    if "display_name" in payload:
        tool.display_name = str(payload.get("display_name") or "").strip() or None
    if "description" in payload:
        tool.description = str(payload.get("description") or "").strip()
    if "parameters_schema" in payload:
        tool.parameters_schema = normalize_parameter_schema(payload.get("parameters_schema"), strict=True)
        validate_sql_template(tool.sql_template, tool.parameters_schema)
    if "sql_template" in payload:
        effective_schema = normalize_parameter_schema(tool.parameters_schema, strict=True)
        tool.sql_template = validate_sql_template(
            str(payload.get("sql_template") or tool.sql_template), effective_schema
        )
    if "row_level_security_rules" in payload:
        tool.row_level_security_rules = normalize_rls_rules(payload.get("row_level_security_rules"), strict=True)
    if "allowed_roles" in payload:
        tool.allowed_roles = _normalize_allowed_roles(payload.get("allowed_roles"))
    if "max_rows" in payload:
        tool.max_rows = _normalize_database_tool_limit(
            payload.get("max_rows"),
            field_name="max_rows",
            default=int(tool.max_rows or 100),
            maximum=MAX_DATABASE_TOOL_ROWS,
        )
    if "timeout_seconds" in payload:
        tool.timeout_seconds = _normalize_database_tool_limit(
            payload.get("timeout_seconds"),
            field_name="timeout_seconds",
            default=int(tool.timeout_seconds or 30),
            maximum=MAX_DATABASE_TOOL_TIMEOUT_SECONDS,
        )
    if "is_active" in payload:
        tool.is_active = bool(payload.get("is_active"))
    await db.commit()
    refreshed = await _load_query_tool(db, tool.id)
    return serialize_database_query_tool(refreshed)


async def delete_database_query_tool(db: AsyncSession, tool_id: str) -> dict[str, Any]:
    tool = await _load_query_tool(db, tool_id)
    await db.delete(tool)
    await db.commit()
    return {"status": "deleted"}


async def list_dynamic_database_tool_definitions(db: AsyncSession, context: ToolContext) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(DatabaseQueryTool)
                .options(selectinload(DatabaseQueryTool.connector))
                .join(DatabaseConnector)
                .where(
                    DatabaseQueryTool.is_active.is_(True),
                    DatabaseConnector.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    definitions: list[dict[str, Any]] = []
    for tool in rows:
        if not tool_visible_to_context(tool, context):
            continue
        schema = normalize_parameter_schema(tool.parameters_schema)
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": tool.tool_name,
                    "description": tool.description
                    or (
                        f"Execute the predefined database query tool {tool.tool_name}. "
                        "This tool runs only the registered query template."
                    ),
                    "parameters": schema,
                },
            }
        )
    return definitions
