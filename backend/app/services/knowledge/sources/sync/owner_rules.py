"""The one rule for configuring a Knowledge source, whatever its type, checked here and nowhere else."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .....models import ConnectorNamedConnection
from ....admin.governance.admin_access_service import is_global_admin
from ....named_connections.contract import DEFAULT_CONNECTION_NAME
from ....named_connections.grants import grant_for
from ....rest_connector.authorization import grants_of
from ....rest_connector.connections import connection_for_call
from ....secure_work.custom_rest.listing import definition_by_key, operation_of
from .config import ConnectorConfig

CODE_CONNECTION_NOT_GRANTED = "source_connection_not_granted"
CODE_VISIBILITY_ADMIN_ONLY = "rest_source_visibility_admin_only"
VISIBILITY_WORKSPACE = "workspace"


class SourceRuleRefusedError(Exception):
    def __init__(self, code: str, field: str, message: str, extra: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.code, self.field, self.message = code, field, message
        self.extra = dict(extra or {})

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": self.message, **self.extra}


def _connection_facts(row: Any, *, admin: bool, project_id: str) -> dict[str, str]:
    # Visibility goes downward only: no id unless the connection is released here, another Workspace's stays unnamed.
    if row is None:
        return {}
    if admin:
        return {"connection_id": str(row.id), "connection_name": str(row.name or "")}
    owner = getattr(row, "owner_workspace_id", None) or getattr(row, "project_id", None)
    if owner is None or owner == project_id:  # the platform's own connection, or this Workspace's
        return {"connection_name": str(row.name or "")}
    return {}


def _not_granted(field: str, facts: dict[str, str] | None = None) -> SourceRuleRefusedError:
    return SourceRuleRefusedError(CODE_CONNECTION_NOT_GRANTED, field,
                                  "This connection is not released to this Workspace. A platform admin can release "
                                  "it (Connections), then configure the source again.", facts)


def _named_connection_id(config: ConnectorConfig) -> tuple[str, str] | None:
    if config.connection_id:
        return config.connection_id, "connection_id"
    pin = (config.scope or {}).get("connection_id")
    if isinstance(pin, str) and pin and pin != DEFAULT_CONNECTION_NAME:
        return pin, "connection_id"
    return None


async def _require_named_grant(db: AsyncSession, project_id: str, config: ConnectorConfig, admin: bool) -> None:
    named = _named_connection_id(config)
    if named is None:
        return
    connection_id, field = named
    row = await db.get(ConnectorNamedConnection, connection_id)
    if row is not None and await grant_for(db, row, project_id) is None:
        raise _not_granted(field, _connection_facts(row, admin=admin, project_id=project_id))


async def _require_rest_grant(db: AsyncSession, project_id: str, scope: dict[str, Any], admin: bool) -> None:
    key = scope.get("definition")
    if not isinstance(key, str) or not key:
        return
    definition = await definition_by_key(db, key)
    if definition is None:
        return
    connection = await connection_for_call(db, definition.id, project_id)
    if connection is None:
        raise _not_granted("scope.definition")
    operation = await operation_of(db, definition, str(scope.get("operation") or ""))
    if operation is not None and not any(grant.workspace_id in (None, project_id) for grant in grants_of(operation)):
        raise _not_granted("scope.operation", _connection_facts(connection, admin=admin, project_id=project_id))


async def _require_admin_for_workspace_visibility(scope: dict[str, Any], admin: bool) -> None:
    if scope.get("visibility") == VISIBILITY_WORKSPACE and not admin:
        raise SourceRuleRefusedError(CODE_VISIBILITY_ADMIN_ONLY, "scope.visibility",
                                     "Only a platform admin can make a source visible to the whole Workspace.")


async def enforce_source_rules(db: AsyncSession, *, project_id: str, config: ConnectorConfig, actor_id: str) -> None:
    scope = dict(config.scope or {})
    admin = await is_global_admin(db, actor_id)
    await _require_named_grant(db, project_id, config, admin)
    await _require_rest_grant(db, project_id, scope, admin)
    await _require_admin_for_workspace_visibility(scope, admin)


__all__ = [
    "CODE_CONNECTION_NOT_GRANTED",
    "CODE_VISIBILITY_ADMIN_ONLY",
    "SourceRuleRefusedError",
    "enforce_source_rules",
]
