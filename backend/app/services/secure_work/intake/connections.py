"""The connections of a work source a Workspace can use (named connections, intake overview)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.named_connections.workspace_routes import workspace_routes

from ....models import BuiltInToolConfig, WorkItemSyncConfig
from ...named_connections.contract import DEFAULT_CONNECTION_NAME
from ...named_connections.descriptors import descriptor_of
from ...named_connections.linked_use import (
    USE_TICKETS,
    LinkedConnectionRefusedError,
    deviation_refusal,
    resolve_linked,
)
from ...named_connections.resolver import connection_config, with_secrets
from ...tool_config import merge_tool_configs_into_project_config
from ...tool_config.connection_fields import global_config_for_scope

SCOPE_WORKSPACE = "workspace"
SCOPE_GLOBAL = "global"


async def default_connection_config(db: AsyncSession, project_id: str | None, tool: str) -> dict[str, Any]:
    project_config = await merge_tool_configs_into_project_config(db, project_id, {})
    if project_id:
        global_config = await merge_tool_configs_into_project_config(db, None, {})
        return {**global_config_for_scope(tool, global_config, project_config), **project_config}
    return project_config


async def _own_entry_usable(db: AsyncSession, project_id: str, tool: str) -> bool:
    descriptor = descriptor_of(tool)
    row = (
        await db.execute(
            select(BuiltInToolConfig).where(
                BuiltInToolConfig.tool_name == tool,
                BuiltInToolConfig.project_id == project_id,
                BuiltInToolConfig.is_active.is_(True),
            )
        )
    ).scalars().first()
    return bool(row is not None and descriptor is not None and descriptor.usable(dict(row.config or {})))


async def workspace_connections(db: AsyncSession, project_id: str, tool: str) -> list[dict[str, Any]]:
    descriptor = descriptor_of(tool)
    if descriptor is None:
        return []
    listed: list[dict[str, Any]] = []
    routes = await workspace_routes(db, project_id, [tool], secrets=False)
    if descriptor.usable(await default_connection_config(db, project_id, tool)):
        scope = SCOPE_WORKSPACE if await _own_entry_usable(db, project_id, tool) else SCOPE_GLOBAL
        entry = {"id": DEFAULT_CONNECTION_NAME, "name": DEFAULT_CONNECTION_NAME, "scope": scope,
                 "bound_scopes": [], "default": True}
        default = routes.default_of(tool)
        if default is not None:  # the connection that is the default connection here
            entry["aliases"] = [default.id]
        listed.append(entry)
    for connection in routes.of(tool):
        listed.append({"id": connection.id, "name": connection.name, "scope": connection.scope,
                       "bound_scopes": sorted(connection.bound_scopes), "default": False})
    return listed


CODE_CONNECTION_NOT_FOUND = "intake_connection_not_found"
CODE_WORKSPACE_REQUIRED = "intake_workspace_required"


def refused(code: str, field: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"state": "needs_configuration", "code": code, "field": field,
                                                  "message": message})


def require_intake_workspace(project_id: str | None) -> str:
    if not project_id:
        raise refused(CODE_WORKSPACE_REQUIRED, "project_id", "An intake belongs to one Workspace.")
    return project_id


def named_intake_connection(project_id: str | None, connection_id: object) -> str:
    require_intake_workspace(project_id)
    wanted = connection_id.strip() if isinstance(connection_id, str) else ""
    if not wanted:
        raise refused(CODE_CONNECTION_NOT_FOUND, "connection_id",
                      "Pick one of this Workspace's connections (Workspace → Connectors).")
    return wanted


async def require_intake_connection(
    db: AsyncSession, project_id: str | None, tool: str, connection_id: object
) -> dict[str, Any]:
    project_id = require_intake_workspace(project_id)
    wanted = connection_id.strip() if isinstance(connection_id, str) else ""
    found = next((entry for entry in await workspace_connections(db, project_id, tool)
                  if wanted == entry["id"] or wanted in entry.get("aliases", ())), None)
    if found is None:
        raise refused(CODE_CONNECTION_NOT_FOUND, "connection_id",
                      "Pick one of this Workspace's connections (Workspace → Connectors).")
    return found


def _key_field(tool: str) -> str:
    from .registry import source_for

    source = source_for(tool)
    return str(getattr(source, "key_field", None) or "")


def connection_refused(error: LinkedConnectionRefusedError) -> HTTPException:
    return HTTPException(status_code=409, detail=error.detail())


async def intake_connection_config(db: AsyncSession, row: WorkItemSyncConfig, tool: str) -> dict[str, Any] | None:
    keys = (row.filters_json or {}).get(_key_field(tool)) or ()
    return await connection_config_of(db, row.project_id, tool, row.connection_id, keys=keys)


async def connection_config_of(
    db: AsyncSession, project_id: str | None, tool: str, connection_id: str | None, *, keys: Any = (),
) -> dict[str, Any] | None:
    base = await default_connection_config(db, project_id, tool)
    routes = await workspace_routes(db, project_id, [tool], secrets=False)
    try:
        linked = await resolve_linked(db, project_id or "", tool, connection_id, routes)
        refused = deviation_refusal(linked.grant, USE_TICKETS, tool, keys) if linked is not None else None
    except LinkedConnectionRefusedError as error:
        raise connection_refused(error) from None
    if refused is not None:
        raise connection_refused(refused)
    if linked is None:
        return None
    target = await with_secrets(db, linked.target) if linked.target is not None else None
    return connection_config(base, tool, routes, target)


async def connection_row_id(db: AsyncSession, row: WorkItemSyncConfig, tool: str) -> str | None:
    if not row.project_id:
        return None
    routes = await workspace_routes(db, row.project_id, [tool], secrets=False)
    wanted = str(row.connection_id or DEFAULT_CONNECTION_NAME)
    if wanted == DEFAULT_CONNECTION_NAME:
        default = routes.default_of(tool)
        return default.id if default is not None else None
    return wanted


async def connection_name(db: AsyncSession, row: WorkItemSyncConfig, tool: str) -> str:
    wanted = str(row.connection_id or DEFAULT_CONNECTION_NAME)
    if not row.project_id or wanted == DEFAULT_CONNECTION_NAME:
        return wanted
    listed = await workspace_connections(db, row.project_id, tool)
    if any(wanted in entry.get("aliases", ()) for entry in listed):
        return DEFAULT_CONNECTION_NAME
    return next((entry["name"] for entry in listed if entry["id"] == wanted), wanted)


__all__ = [
    "CODE_CONNECTION_NOT_FOUND",
    "CODE_WORKSPACE_REQUIRED",
    "connection_config_of",
    "connection_name",
    "connection_refused",
    "connection_row_id",
    "default_connection_config",
    "intake_connection_config",
    "named_intake_connection",
    "require_intake_connection",
    "require_intake_workspace",
    "workspace_connections",
]
