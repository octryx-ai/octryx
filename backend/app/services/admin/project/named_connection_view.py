"""The admin view of named connections, per Workspace or global.

Per connection: its stable, server-generated ``id`` (what other config references: a Knowledge
connector's ``connection_id``, run reports, audit), name, bound scopes, the unit's non-secret fields,
which secrets are stored (booleans), the last test of the saved connection, and who uses it
(``usage.py``: Workspaces and Knowledge connectors, with the keys each one reads through it). Never a
secret value or a ``*_secret_ref``.

Every list carries the connector's ``descriptor`` (``ConnectorDescriptor.public``: binding, fields with
secrets flagged, form kind, test), so the one UI component renders any connector type.

A Workspace's list also carries ``inherited``: the global connections, read-only, with the keys each
serves in this Workspace and the keys a Workspace connection overrides. The global list carries
``workspace_connections``: every active Workspace's own connections, read-only (``named_connection_workspaces.py``).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.named_connections.workspace_routes import effective_of

from ....models import ConnectorNamedConnection, Project
from ...named_connections.contract import DEFAULT_CONNECTION_NAME, NamedConnectionError, require_connector
from ...named_connections.descriptors import DESCRIPTORS, descriptor_of
from ...named_connections.store import list_rows, to_value
from ...named_connections.usage import connection_usage
from ...tool_config import get_tool_config
from .named_connection_unit import public_fields, secret_status
from .named_connection_workspaces import workspace_connections

LAST_TEST_SUMMARY_CHARS = 300


async def require_scope(db: AsyncSession, connector: str, project_id: str | None) -> str:
    """The canonical connector name; 404 for an unsupported connector or an unknown Workspace."""
    try:
        tool = require_connector(connector)
    except NamedConnectionError:
        raise HTTPException(status_code=404, detail="Unknown connector for named connections") from None
    if project_id is not None:
        found = (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="Project not found")
    return tool


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def last_test_record(result: dict[str, Any], at: Any) -> dict[str, Any]:
    """What is kept of a test of the saved connection: ok, time and the test's fixed summary (truncated)."""
    summary = str(result.get("summary") or "").strip()[:LAST_TEST_SUMMARY_CHARS]
    return {"ok": bool(result.get("ok")), "at": _iso(at), "summary": summary}


def _last_test(row: ConnectorNamedConnection) -> dict[str, Any] | None:
    value = row.last_test
    if not isinstance(value, dict):
        return None
    return {"ok": value.get("ok") is True, "at": value.get("at"), "summary": str(value.get("summary") or "")}


def serialize(row: ConnectorNamedConnection, usage: dict[str, list] | None = None) -> dict[str, Any]:
    """One connection: id, names, scopes, non-secret fields, secret presence, last test, usage. Never a secret."""
    tool, config = str(row.tool_name), dict(row.config or {})
    view = {
        "id": row.id,
        "name": row.name,
        "connector_name": tool,
        "scope": "global" if row.project_id is None else "workspace",
        "bound_scopes": list(row.bound_scopes or []),
        "fields": public_fields(tool, config),
        "secret_status": secret_status(tool, config),
        "last_test": _last_test(row),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }
    if usage is not None:
        view["usage"] = usage
    return view


async def usage_of_row(db: AsyncSession, row: ConnectorNamedConnection) -> dict[str, list]:
    usage = await connection_usage(db, str(row.tool_name), row.project_id, [row.id])
    return usage[row.id]


async def _inherited(db: AsyncSession, tool: str, project_id: str, own: list) -> list[dict[str, Any]]:
    """The global connections as this Workspace sees them: read-only, with served and overridden keys."""
    global_rows = await list_rows(db, tool, None)
    effective = effective_of([to_value(row) for row in own], [to_value(row) for row in global_rows])
    served = {connection.id: keys for _, connection, keys in effective}
    inherited = []
    for row in global_rows:
        view = serialize(row)
        keys = served.get(row.id, frozenset())
        view["served_here"] = sorted(keys)
        view["overridden_here"] = sorted(set(view["bound_scopes"]) - keys)
        view["read_only"] = True
        inherited.append(view)
    return inherited


async def list_named(db: AsyncSession, *, connector: str, project_id: str | None) -> dict[str, Any]:
    tool = await require_scope(db, connector, project_id)
    entry = await get_tool_config(db, tool, project_id)
    default_config = dict(entry.config or {}) if entry else {}
    rows = await list_rows(db, tool, project_id)
    usage = await connection_usage(db, tool, project_id, [row.id for row in rows])
    listed: dict[str, Any] = {
        "connector_name": tool,
        "descriptor": descriptor_of(tool).public(),
        "scope": "global" if project_id is None else "workspace",
        "default": {
            "id": DEFAULT_CONNECTION_NAME,
            "name": DEFAULT_CONNECTION_NAME,
            "configured": entry is not None,
            "active": bool(entry and entry.is_active),
            "fields": public_fields(tool, default_config),
            "secret_status": secret_status(tool, default_config),
        },
        "connections": [serialize(row, usage[row.id]) for row in rows],
    }
    if project_id is not None:
        listed["inherited"] = await _inherited(db, tool, project_id, rows)
    else:
        listed["workspace_connections"] = await workspace_connections(db, tool)
    return listed


def list_descriptors() -> dict[str, Any]:
    """Every connector type with named connections and what its form needs (the UI's only source for them)."""
    return {"connectors": [descriptor.public() for descriptor in DESCRIPTORS.values()]}


__all__ = ["last_test_record", "list_descriptors", "list_named", "require_scope", "serialize", "usage_of_row"]
