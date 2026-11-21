"""The one rule for configuring a Knowledge source, whatever its type.

A Workspace owner or admin configures every source type of Knowledge › Sources (Confluence, Jira, ServiceNow,
Kubernetes, Git/Bitbucket, Custom REST) in their own Workspace under the same rules, checked here and nowhere else.
``service.configure_connector`` (create and update) and ``rest_preview.sample_rest_source`` (the dry run) both call
:func:`enforce_source_rules` before anything is read or saved:

- **only a connection granted to this Workspace**: a named connection the source pins or links must be available in
  the Workspace (``named_connections.grants.grant_for``: its own, one shared with it, or ``all``); a Custom REST
  definition must have a connection that serves the Workspace (its own or the platform's, exactly what a run resolves)
  and its list operation a grant for this Workspace. A connection of another Workspace or one the platform keeps to
  itself is refused 403 ``source_connection_not_granted``. This holds for a platform admin too: release the
  connection to the Workspace first, so a source never reads with an account its Workspace was not given;
- **visibility**: a source follows its own ACL, and a Custom REST source defaults to ``restricted``
  (``rest_config``). Widening it to ``workspace`` shows every item to every member past the grants, so only a platform
  admin may (403 ``rest_source_visibility_admin_only``: the code the Knowledge UI already maps);
- the ACL enforce switch is platform admin only (``api/routes/knowledge_source_settings``), and another Workspace is
  the one 404 of ``access/authorization`` before any of this runs.

Why one place: a check in a single route leaves the other source types unchecked, and an unreleased named
connection would surface only as a 409 run-state reason (``connection_not_available``) or not at all until the
first run. Owners configure every type with the same rules, so the rule is kind-agnostic.

Unknown ids (no such connection or definition) are left to the existing configuration refusals (409
``connection_pin_unknown``, ``custom_rest_definition_unavailable``), which say what to fix.
"""

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
    """A source configuration the caller may not make here: a fixed code, the field and a sentence (403), plus
    ``extra`` (the refused connection's ``connection_id`` / ``connection_name`` where the caller may see them)."""

    def __init__(self, code: str, field: str, message: str, extra: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.code, self.field, self.message = code, field, message
        self.extra = dict(extra or {})

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": self.message, **self.extra}


def _connection_facts(row: Any, *, admin: bool, project_id: str) -> dict[str, str]:
    """What the refusal may say about the connection, so the UI links Admin › Connections.

    A platform admin sees every connection: id and name. Anyone else gets no id (the connection is not released to
    their Workspace, so it is not theirs to open), and the name only for a platform connection; another Workspace's
    connection stays unnamed (tenant visibility goes downward only)."""
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
    """The named connection a source reads with and the field that named it; ``default`` is the Workspace's own."""
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
    """A Custom REST source's "connection": a REST connection serving this Workspace and a grant of its list read."""
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
    """Refuse (:class:`SourceRuleRefusedError`) a source configuration the module doc's rule does not allow."""
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
