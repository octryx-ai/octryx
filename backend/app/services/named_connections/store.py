"""Read named connections and resolve their secrets, bound to the connection they belong to.

A secret ref of a named connection resolves only through the secret store's scope check for exactly
this connector, this scope (Workspace or global) and the field ``<field>#<connection id>``
(``contract.named_secret_field``). A ref copied from the default entry, another named connection or
another Workspace resolves to nothing, so a connection without its own secret has no credential and
fails closed; it never borrows one.

Every row is a connection: the runtime reads the ones available in a Workspace through
``grants.py`` / ``workspace_routes.py``; :func:`list_rows` and :func:`get_row` read one exact scope for the
named-connection admin views, :func:`list_platform_connections` the ones every Workspace and the platform scope
may use.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection
from ...models.runtime.named_connection import GLOBAL_SCOPE_KEY
from ..secret import get_secret_value, normalize_secret_ref, secret_ref_field_name
from .contract import NamedConnection, named_secret_field, scope_key, secret_fields


def scope_key_of(project_id: str | None) -> str:
    return project_id or GLOBAL_SCOPE_KEY


def to_value(row: ConnectorNamedConnection) -> NamedConnection:
    tool = str(row.tool_name)
    return NamedConnection(
        id=str(row.id),
        tool_name=tool,
        project_id=row.project_id,
        name=str(row.name),
        config=dict(row.config or {}),
        bound_scopes=frozenset(scope_key(tool, key) for key in row.bound_scopes or ()),
    )


async def list_rows(db: AsyncSession, tool_name: str, project_id: str | None) -> list[ConnectorNamedConnection]:
    """The named connections of one connector in exactly one scope (a Workspace, or global), by name."""
    result = await db.execute(
        select(ConnectorNamedConnection)
        .where(
            ConnectorNamedConnection.tool_name == tool_name,
            ConnectorNamedConnection.scope_key == scope_key_of(project_id),
        )
        .order_by(ConnectorNamedConnection.name)
    )
    return list(result.scalars().all())


async def list_platform_connections(db: AsyncSession, tool_name: str) -> list[ConnectorNamedConnection]:
    """The connections of ``tool_name`` available everywhere (``available_in`` ``all``), by name."""
    rows = await list_rows(db, tool_name, None)
    return [row for row in rows if str(row.available_in or "all") == "all"]


async def list_named_connections(db: AsyncSession, tool_name: str, project_id: str | None) -> list[NamedConnection]:
    return [to_value(row) for row in await list_rows(db, tool_name, project_id)]


async def get_row(
    db: AsyncSession, tool_name: str, project_id: str | None, connection_id: str
) -> ConnectorNamedConnection | None:
    row = await db.get(ConnectorNamedConnection, str(connection_id or ""))
    if row is None or row.tool_name != tool_name or row.scope_key != scope_key_of(project_id):
        return None
    return row


def public_config(connection: NamedConnection) -> dict:
    """The connection's fields without any secret value or secret ref."""
    secrets = secret_fields(connection.tool_name)
    # a stored row never holds a secret value; ignore one if it did
    return {
        key: value
        for key, value in connection.config.items()
        if not key.endswith("_secret_ref") and key not in secrets
    }


async def resolved_config(db: AsyncSession, connection: NamedConnection) -> dict:
    """The connection's fields with each secret resolved for this connection only; refs removed."""
    config = public_config(connection)
    for field in secret_fields(connection.tool_name):
        secret_id = normalize_secret_ref(connection.config.get(secret_ref_field_name(field)))
        if not secret_id:
            continue
        value = await get_secret_value(
            db,
            secret_id=secret_id,
            expected_tool_name=connection.tool_name,
            expected_field_name=named_secret_field(field, connection.id),
            expected_project_id=connection.project_id,
        )
        if value is not None:
            config[field] = value
    return config


__all__ = [
    "get_row",
    "list_named_connections",
    "list_platform_connections",
    "list_rows",
    "public_config",
    "resolved_config",
    "scope_key_of",
    "to_value",
]
