"""Connections of a custom REST definition: base URL and the technical account, per Workspace or platform-wide."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, RestApiConnection, RestApiDefinition
from ...models.runtime.rest_connector import GLOBAL_CONNECTION_SCOPE
from ..secret import resolve_secret_refs, set_secret_value
from ..secret.release import ExcludedHolder, config_secret_refs, release_unreferenced_secrets
from .auth import REQUIRED_FIELDS, REQUIRED_SECRETS, SECRET_FIELDS
from .common import secret_scope

PUBLIC_FIELDS = ("username", "client_id", "token_url", "scope", "audience")


def validate_base_url(raw: object) -> str:
    url = str(raw or "").strip().rstrip("/")
    try:
        parts = urlsplit(url)
    except ValueError:
        parts = None
    if parts is None or parts.scheme not in {"https", "http"} or not parts.hostname:
        raise HTTPException(status_code=400, detail="base_url must be an http(s) URL with a host")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise HTTPException(status_code=400, detail="base_url may not carry credentials, a query or a fragment")
    return url


def serialize_connection(connection: RestApiConnection, definition: RestApiDefinition | None = None) -> dict[str, Any]:
    config = dict(connection.config or {})
    scheme = str(((definition.auth if definition else None) or {}).get("scheme") or "none")
    needed = (*REQUIRED_FIELDS.get(scheme, ()), *REQUIRED_SECRETS.get(scheme, ()))
    return {
        "id": connection.id,
        "definition_id": connection.definition_id,
        "project_id": connection.project_id,
        "owner": "workspace" if connection.project_id else "platform",
        "name": connection.name,
        "base_url": connection.base_url,
        "is_active": bool(connection.is_active),
        "fields": {name: config.get(name) for name in PUBLIC_FIELDS if config.get(name)},
        "secret_status": {name: bool(config.get(f"{name}_secret_ref")) for name in SECRET_FIELDS},
        "missing_for_auth": [name for name in needed
                             if not (config.get(name) or config.get(f"{name}_secret_ref"))],
    }


async def _definition(db: AsyncSession, definition_id: str) -> RestApiDefinition:
    definition = await db.get(RestApiDefinition, definition_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="REST API definition not found")
    return definition


async def _connection(db: AsyncSession, definition_id: str, connection_id: str) -> RestApiConnection:
    connection = await db.get(RestApiConnection, connection_id)
    if connection is None or connection.definition_id != definition_id:
        raise HTTPException(status_code=404, detail="REST API connection not found")
    return connection


async def _apply_fields(db: AsyncSession, connection: RestApiConnection, payload: dict[str, Any]) -> None:
    config = dict(connection.config or {})
    for name in PUBLIC_FIELDS:
        if name in payload:
            value = str(payload.get(name) or "").strip()
            if value:
                config[name] = value
            else:
                config.pop(name, None)
    for name in SECRET_FIELDS:
        value = str(payload.get(name) or "").strip()
        if value:
            entry = await set_secret_value(db, tool_name=secret_scope(connection.id), field_name=name,
                                           project_id=connection.project_id, value=value)
            config[f"{name}_secret_ref"] = entry.id
        elif payload.get(f"clear_{name}"):
            config.pop(f"{name}_secret_ref", None)
        config.pop(name, None)  # a value never lands in the row
    connection.config = config


async def list_connections(db: AsyncSession, definition_id: str) -> list[dict[str, Any]]:
    definition = await _definition(db, definition_id)
    rows = (await db.execute(
        select(RestApiConnection).where(RestApiConnection.definition_id == definition_id)
        .order_by(RestApiConnection.scope_key)
    )).scalars().all()
    return [serialize_connection(row, definition) for row in rows]


async def create_connection(db: AsyncSession, definition_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    definition = await _definition(db, definition_id)
    project_id = str(payload.get("project_id") or "").strip() or None
    if project_id and await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    scope_key = project_id or GLOBAL_CONNECTION_SCOPE
    taken = (await db.execute(select(RestApiConnection.id).where(
        RestApiConnection.definition_id == definition_id, RestApiConnection.scope_key == scope_key))).scalar()
    if taken:
        raise HTTPException(status_code=409, detail="This definition already has a connection in that scope")
    connection = RestApiConnection(
        definition_id=definition_id,
        project_id=project_id,
        scope_key=scope_key,
        name=str(payload.get("name") or ("Platform" if not project_id else "Workspace")).strip()[:64],
        base_url=validate_base_url(payload.get("base_url") or next(iter(definition.servers or []), "")),
        config={},
        is_active=bool(payload.get("is_active", True)),
    )
    db.add(connection)
    await db.flush()
    await _apply_fields(db, connection, payload)
    await db.commit()
    return serialize_connection(connection, definition)


async def update_connection(
    db: AsyncSession, definition_id: str, connection_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    definition = await _definition(db, definition_id)
    connection = await _connection(db, definition_id, connection_id)
    if "name" in payload:
        connection.name = str(payload.get("name") or connection.name).strip()[:64]
    if "base_url" in payload:
        connection.base_url = validate_base_url(payload.get("base_url"))
    if "is_active" in payload:
        connection.is_active = bool(payload.get("is_active"))
    await _apply_fields(db, connection, payload)
    await db.commit()
    return serialize_connection(connection, definition)


async def delete_connection(db: AsyncSession, definition_id: str, connection_id: str) -> dict[str, Any]:
    connection = await _connection(db, definition_id, connection_id)
    secret_ids = config_secret_refs(dict(connection.config or {}))
    await db.delete(connection)
    await db.flush()
    released = await release_unreferenced_secrets(
        db, secret_ids, excluded=ExcludedHolder(RestApiConnection.__tablename__, connection.id)
    )
    await db.commit()
    return {"status": "deleted", "stored_entries": released.to_payload()}


async def connection_for_call(
    db: AsyncSession, definition_id: str, workspace_id: str | None
) -> RestApiConnection | None:
    rows = (await db.execute(
        select(RestApiConnection).where(
            RestApiConnection.definition_id == definition_id,
            RestApiConnection.is_active.is_(True),
            RestApiConnection.scope_key.in_([key for key in (workspace_id, GLOBAL_CONNECTION_SCOPE) if key]),
        )
    )).scalars().all()
    by_scope = {row.scope_key: row for row in rows}
    return by_scope.get(workspace_id or "") or by_scope.get(GLOBAL_CONNECTION_SCOPE)


async def resolved_config(db: AsyncSession, connection: RestApiConnection) -> dict[str, Any]:
    config = dict(connection.config or {})
    resolved = await resolve_secret_refs(db, config, tool_name=secret_scope(connection.id),
                                         project_id=connection.project_id, purpose="rest_connector.call")
    return {key: value for key, value in resolved.items() if not key.endswith("_secret_ref")}


__all__ = [
    "PUBLIC_FIELDS",
    "connection_for_call",
    "create_connection",
    "delete_connection",
    "list_connections",
    "resolved_config",
    "serialize_connection",
    "update_connection",
    "validate_base_url",
]
