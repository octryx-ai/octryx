"""The connections of a work source a Workspace can use (named connections, intake overview).

A Workspace's connections of one connector are its **default** entry (the connector's tool config: the
Workspace entry over the global one, the credential unit never mixed) when that entry has a target, and
its **named** connections (the Workspace's own, then the global ones the Workspace does not override),
as the one resolver (``named_connections.resolver``) lists them. Only ids, names, scopes and bound keys
are returned; never a URL, a config value or a secret.

An intake reads through exactly the connection it names (``WorkItemSyncConfig.connection_id``):

- :func:`require_intake_connection` at setup (``intake/setup.save_intake``): the id must be one of the Workspace's
  connections of the source (422 ``intake_connection_not_found`` otherwise); an intake without a Workspace is refused.
  The source's store takes the named id as is (:func:`named_intake_connection`: a Workspace and an id, never a
  default);
- :func:`intake_connection_config` at run time: the connection's effective config (the resolver's
  ``connection_config``: a named connection's own unit with the allowlist narrowed to its bound keys; the
  default entry without the keys a named connection binds), or ``None`` when the named connection is gone
  (the run is blocked, never moved to another connection).

The connection is read through the connections available in the Workspace
(``named_connections/linked_use.py``): the default connection's id (``named_connections/unbound_default.py``) is
the default connection (it is listed as the default entry's alias); a disabled or unavailable connection, a
``tickets`` deviation that turns the use off or a filter key outside the deviation's scope refuse the run with 409
``needs_configuration`` and a fixed code. An intake naming ``default`` (or nothing) reads the default connection.
"""

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
    """The Workspace's effective default entry of ``tool`` (its own unit, else the global one)."""
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
    """``[{id, name, scope, bound_scopes, default}]``: the default entry (when usable), then named ones."""
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
    """The connection id an intake names; 422 when there is no Workspace or no id (no connection is assumed)."""
    require_intake_workspace(project_id)
    wanted = connection_id.strip() if isinstance(connection_id, str) else ""
    if not wanted:
        raise refused(CODE_CONNECTION_NOT_FOUND, "connection_id",
                      "Pick one of this Workspace's connections (Workspace → Connectors).")
    return wanted


async def require_intake_connection(
    db: AsyncSession, project_id: str | None, tool: str, connection_id: object
) -> dict[str, Any]:
    """The Workspace connection an intake names; 422 when there is no Workspace or no such connection."""
    project_id = require_intake_workspace(project_id)
    wanted = connection_id.strip() if isinstance(connection_id, str) else ""
    found = next((entry for entry in await workspace_connections(db, project_id, tool)
                  if wanted == entry["id"] or wanted in entry.get("aliases", ())), None)
    if found is None:
        raise refused(CODE_CONNECTION_NOT_FOUND, "connection_id",
                      "Pick one of this Workspace's connections (Workspace → Connectors).")
    return found


def _key_field(tool: str) -> str:
    """The filter key whose values bind the intake to a connection's scope: its source's ``key_field``."""
    from .registry import source_for

    source = source_for(tool)
    return str(getattr(source, "key_field", None) or "")


def connection_refused(error: LinkedConnectionRefusedError) -> HTTPException:
    return HTTPException(status_code=409, detail=error.detail())


async def intake_connection_config(db: AsyncSession, row: WorkItemSyncConfig, tool: str) -> dict[str, Any] | None:
    """The effective config of the intake's connection; ``None`` when its named connection is gone.

    Raises 409 (``needs_configuration``) when the connection or the Workspace's ``tickets`` deviation refuses the
    intake (see the module doc)."""
    keys = (row.filters_json or {}).get(_key_field(tool)) or ()
    return await connection_config_of(db, row.project_id, tool, row.connection_id, keys=keys)


async def connection_config_of(
    db: AsyncSession, project_id: str | None, tool: str, connection_id: str | None, *, keys: Any = (),
) -> dict[str, Any] | None:
    """The effective config of one Workspace connection (``None``/``default``: the default entry)."""
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
    """The connection row the intake reads through (its own id, or the default connection's); ``None`` for the
    default entry."""
    if not row.project_id:
        return None
    routes = await workspace_routes(db, row.project_id, [tool], secrets=False)
    wanted = str(row.connection_id or DEFAULT_CONNECTION_NAME)
    if wanted == DEFAULT_CONNECTION_NAME:
        default = routes.default_of(tool)
        return default.id if default is not None else None
    return wanted


async def connection_name(db: AsyncSession, row: WorkItemSyncConfig, tool: str) -> str:
    """The display name of the intake's connection (its id when it is gone)."""
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
