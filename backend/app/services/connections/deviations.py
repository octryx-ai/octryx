"""A Workspace's view of its connections and its deviations.

``GET /api/v1/workspaces/{ws}/connections`` → ``{connections: [{id, name, type, state, effective, deviation,
can_edit}]}``: only the connections available in the Workspace, each through ``config_effective.effective``.

The base a deviation narrows, per use, in this Workspace:

- ``knowledge`` / ``tickets``: the linked Knowledge source / intake of this Workspace (enabled, scope, schedule;
  tickets also write-back), else off with the connection's ``bound_scopes`` as the scope (``None``: unrestricted);
- ``agent_tools``: the connection's level.

``PUT …/deviation`` stores a deviation that is narrower in every field (``422 deviation_not_narrower`` with
``field`` otherwise) and returns ``{effective, deviation}``; ``DELETE`` resets it (``deviation: null``). Both are
for the Workspace's admins and platform admins (``can_edit``) and are audited.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectionDeviation, ConnectorNamedConnection
from ...time_utils import utc_now
from ..admin.governance.admin_config_audit_service import record_admin_config_audit
from ..config_effective import CONNECTION_RULES, DeviationNotNarrowerError, check_deviation, effective
from ..named_connections.descriptors import descriptor_of
from . import schedules, store
from .catalog import SCOPE_KEYS, uses_of
from .contract import USE_AGENT_TOOLS, USE_KNOWLEDGE, USE_TICKETS, not_found
from .rights import Viewer
from .uses_read import intake_entry, intake_rows, knowledge_rows, knowledge_scope, write_back_of
from .views import presented_state, subject_of

AUDIT_DEVIATION_SET = "admin.connection.deviation_set"
AUDIT_DEVIATION_RESET = "admin.connection.deviation_reset"
SCOPED_USES = (USE_KNOWLEDGE, USE_TICKETS)


def _bound(row: ConnectorNamedConnection) -> dict[str, list[str]] | None:
    key = SCOPE_KEYS.get(str(row.tool_name))
    return {key: list(row.bound_scopes)} if key and row.bound_scopes else None


async def base_of(db: AsyncSession, row: ConnectorNamedConnection, workspace_id: str) -> dict[str, Any]:
    """The connection's values in ``workspace_id`` before any deviation (see the module doc)."""
    tool, kinds, base = str(row.tool_name), uses_of(str(row.tool_name)), {}
    if USE_KNOWLEDGE in kinds:
        source = next((item for item in (await knowledge_rows(db, [row.id]))[row.id]
                       if item.project_id == workspace_id), None)
        base[USE_KNOWLEDGE] = {
            "enabled": bool(source and source.state == "active"),
            "scope": (knowledge_scope(tool, source) if source else None) or _bound(row),
            **(schedules.from_knowledge(bool(source.schedule_enabled), source.schedule_interval_minutes) if source
               else {"schedule": "manual", "schedule_cron": None}),
        }
    if USE_TICKETS in kinds:
        intake = next((item for item in (await intake_rows(db, [row.id]))[row.id]
                       if item.project_id == workspace_id), None)
        entry = intake_entry(tool, intake, {}) if intake else None
        base[USE_TICKETS] = {
            "enabled": bool(entry and entry["enabled"]),
            "scope": (entry["scope"] if entry else None) or _bound(row),
            "schedule": entry["schedule"] if entry else "manual",
            "schedule_cron": entry["schedule_cron"] if entry else None,
            "write_back": await write_back_of(db, workspace_id) if intake else {"enabled": False, "transitions": []},
        }
    if USE_AGENT_TOOLS in kinds:
        base[USE_AGENT_TOOLS] = {"level": row.agent_tools_level}
    return base


def _canonical(row: ConnectorNamedConnection, fields: Any) -> Any:
    """Scope keys in the binding's case; a scope must use the type's scope key."""
    if not isinstance(fields, dict):
        return fields
    key, descriptor = SCOPE_KEYS.get(str(row.tool_name)), descriptor_of(row.tool_name)
    result = dict(fields)
    for use in SCOPED_USES:
        values = result.get(use)
        if not isinstance(values, dict) or "scope" not in values:
            continue
        scope = values["scope"]
        if key is None or not isinstance(scope, dict) or set(scope) != {key} or not isinstance(scope[key], list):
            raise DeviationNotNarrowerError(f"{use}.scope", f"{use}.scope must be {{{key!r}: [...]}}.")
        canonical = [descriptor.binding.canonical(item) if isinstance(item, str) else item for item in scope[key]]
        result[use] = {**values, "scope": {key: canonical}}
    return result


def _refused(error: DeviationNotNarrowerError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": error.code, "message": str(error), "field": error.field})


async def _available_row(db: AsyncSession, connection_id: str, workspace_id: str) -> ConnectorNamedConnection:
    row = await store.get_row(db, connection_id)
    if row is None:
        raise not_found()
    ws = (await store.workspaces_of(db, [row.id]))[row.id]
    if not effective(subject_of(row, ws), workspace_id, {}, None, CONNECTION_RULES).available:
        raise not_found()
    return row


async def _view(db: AsyncSession, row: ConnectorNamedConnection, workspace_id: str,
                stored: ConnectionDeviation | None) -> dict[str, Any]:
    ws = (await store.workspaces_of(db, [row.id]))[row.id]
    base = await base_of(db, row, workspace_id)
    result = effective(subject_of(row, ws), workspace_id, base,
                       dict(stored.fields or {}) if stored else None, CONNECTION_RULES)
    # ``base``: the widest the Workspace may use (the global connection's values here); the narrowing page offers
    # exactly these spaces, projects and levels.
    return {"effective": result.effective, "deviation": result.deviation, "base": base}


async def workspace_list(db: AsyncSession, viewer: Viewer, workspace_id: str) -> dict[str, Any]:
    rows = await store.list_rows(db)
    ws = await store.workspaces_of(db, [row.id for row in rows])
    listed = []
    for row in rows:
        if not effective(subject_of(row, ws[row.id]), workspace_id, {}, None, CONNECTION_RULES).available:
            continue
        view = await _view(db, row, workspace_id, await store.deviation_of(db, row.id, workspace_id))
        listed.append({"id": row.id, "name": row.name, "type": row.tool_name, "state": presented_state(row),
                       **view, "can_edit": viewer.can_edit_workspace(workspace_id)})
    return {"connections": listed}


async def set_deviation(db: AsyncSession, viewer: Viewer, workspace_id: str, connection_id: str,
                        fields: Any) -> dict[str, Any]:
    row = await _available_row(db, connection_id, workspace_id)
    try:
        canonical = _canonical(row, fields)
        check_deviation(await base_of(db, row, workspace_id), canonical, CONNECTION_RULES)
    except DeviationNotNarrowerError as error:
        raise _refused(error) from None
    stored = await store.deviation_of(db, row.id, workspace_id)
    before = dict(stored.fields or {}) if stored else None
    if stored is None:
        stored = ConnectionDeviation(connection_id=row.id, workspace_id=workspace_id)
        db.add(stored)
    stored.fields, stored.updated_by, stored.updated_at = canonical, viewer.user_id, utc_now()
    await db.flush()
    _audit(db, viewer, AUDIT_DEVIATION_SET, row, workspace_id, before, canonical)
    return await _view(db, row, workspace_id, stored)


async def reset_deviation(db: AsyncSession, viewer: Viewer, workspace_id: str, connection_id: str) -> dict[str, Any]:
    row = await _available_row(db, connection_id, workspace_id)
    stored = await store.deviation_of(db, row.id, workspace_id)
    if stored is not None:
        _audit(db, viewer, AUDIT_DEVIATION_RESET, row, workspace_id, dict(stored.fields or {}), None)
        await db.delete(stored)
        await db.flush()
    return await _view(db, row, workspace_id, None)


def _audit(db, viewer: Viewer, action: str, row: ConnectorNamedConnection, workspace_id: str, before, after) -> None:
    record_admin_config_audit(db, actor_user_id=viewer.user_id, action=action, resource_type="connection_deviation",
                              resource_id=f"{row.id}:{workspace_id}", before=before, after=after,
                              details={"connection_type": row.tool_name, "connection_name": row.name,
                                       "workspace_id": workspace_id})


__all__ = ["base_of", "reset_deviation", "set_deviation", "workspace_list"]
