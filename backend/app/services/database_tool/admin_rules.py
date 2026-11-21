"""Loaders, normalization and validation shared by the database connector and query tool admin writes."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.database_tool.common import (
    SECRET_FIELDS,
    normalize_connector_config,
    normalize_string_list,
    secret_scope,
)
from app.services.database_tool.runtime_policy import SUPPORTED_DATABASE_TYPES

from ...models import DatabaseConnector, DatabaseQueryTool
from ..secret import set_secret_value

ROLE_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
MAX_DATABASE_TOOL_ROWS = 10_000
MAX_DATABASE_TOOL_TIMEOUT_SECONDS = 300


async def _load_connector(db: AsyncSession, connector_id: str) -> DatabaseConnector:
    connector = await db.get(DatabaseConnector, connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="Database connector not found")
    return connector


async def _load_connector_with_tools(db: AsyncSession, connector_id: str) -> DatabaseConnector:
    result = await db.execute(
        select(DatabaseConnector)
        .options(selectinload(DatabaseConnector.query_tools))
        .where(DatabaseConnector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Database connector not found")
    return connector


async def _load_query_tool(db: AsyncSession, tool_id: str) -> DatabaseQueryTool:
    result = await db.execute(
        select(DatabaseQueryTool)
        .options(selectinload(DatabaseQueryTool.connector))
        .where(DatabaseQueryTool.id == tool_id)
    )
    tool = result.scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=404, detail="Database query tool not found")
    return tool


def _normalize_database_type(value: Any) -> str:
    normalized = str(value or "postgresql").strip().lower()
    if normalized not in SUPPORTED_DATABASE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported database type: {normalized or value}")
    return normalized


def _effective_connector_config(connector: DatabaseConnector | None, payload: dict[str, Any]) -> dict[str, Any]:
    config = dict((connector.connection_config if connector is not None else {}) or {})
    config.update(normalize_connector_config(payload))
    for secret_field in SECRET_FIELDS:
        if payload.get(f"clear_{secret_field}"):
            config.pop(secret_field, None)
            config.pop(f"{secret_field}_secret_ref", None)
        elif str(payload.get(secret_field) or "").strip():
            config[secret_field] = str(payload.get(secret_field) or "").strip()
    return config


def _validate_connector_config(*, db_type: str, config: dict[str, Any]) -> None:
    if db_type == "sqlite":
        if not str(config.get("file_path") or config.get("database") or "").strip():
            raise HTTPException(status_code=400, detail="SQLite connectors require file_path or database")
        return
    if not str(config.get("dsn") or "").strip() and not (
        str(config.get("host") or "").strip() and str(config.get("database") or "").strip()
    ):
        raise HTTPException(
            status_code=400,
            detail=f"{db_type} connectors require either dsn or both host and database",
        )
    if "port" in config:
        try:
            int(config.get("port"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Connector port must be an integer") from exc


def _normalize_database_tool_limit(value: Any, *, field_name: str, default: int, maximum: int) -> int:
    try:
        normalized = int(value if value not in (None, "") else default)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be an integer") from exc
    if normalized < 1 or normalized > maximum:
        raise HTTPException(status_code=400, detail=f"{field_name} must be between 1 and {maximum}")
    return normalized


def _normalize_allowed_roles(raw: Any) -> list[str]:
    roles: list[str] = []
    seen: set[str] = set()
    for role in normalize_string_list(raw):
        normalized = role.strip()
        if not ROLE_NAME_RE.fullmatch(normalized):
            raise HTTPException(status_code=400, detail=f"Invalid role name: {normalized}")
        lowered = normalized.lower()
        if lowered not in seen:
            roles.append(normalized)
            seen.add(lowered)
    return roles


def _validate_query_tool_project_scope(*, connector: DatabaseConnector, project_id: str | None) -> None:
    if connector.project_id and project_id and project_id != connector.project_id:
        raise HTTPException(
            status_code=400,
            detail="Database query tool project_id must match the connector project scope",
        )


async def _ensure_connector_name_available(
    db: AsyncSession, *, name: str, existing_connector_id: str | None = None
) -> None:
    result = await db.execute(select(DatabaseConnector.id).where(DatabaseConnector.name == name))
    row_id = result.scalar_one_or_none()
    if row_id is not None and row_id != existing_connector_id:
        raise HTTPException(status_code=400, detail=f"Database connector name already exists: {name}")


async def _ensure_tool_name_available(db: AsyncSession, *, tool_name: str, existing_tool_id: str | None = None) -> None:
    result = await db.execute(select(DatabaseQueryTool.id).where(DatabaseQueryTool.tool_name == tool_name))
    row_id = result.scalar_one_or_none()
    if row_id is not None and row_id != existing_tool_id:
        raise HTTPException(status_code=400, detail=f"Database query tool name already exists: {tool_name}")


async def _update_connector_config(db: AsyncSession, *, connector: DatabaseConnector, payload: dict[str, Any]) -> None:
    config = dict(connector.connection_config or {})
    config.update(normalize_connector_config(payload))
    for secret_field in SECRET_FIELDS:
        if secret_field not in payload:
            continue
        raw_value = str(payload.get(secret_field) or "").strip()
        if raw_value:
            secret_entry = await set_secret_value(
                db,
                tool_name=secret_scope(connector.id),
                field_name=secret_field,
                project_id=connector.project_id,
                value=raw_value,
            )
            config.pop(secret_field, None)
            config[f"{secret_field}_secret_ref"] = secret_entry.id
        elif payload.get(f"clear_{secret_field}"):
            config.pop(secret_field, None)
            config.pop(f"{secret_field}_secret_ref", None)
    connector.connection_config = config
    await db.flush()
