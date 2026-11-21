"""The "connection" of a Custom REST Knowledge source: its definition, operations and acting role, resolved per run.

A ``custom_rest`` source reads through no tool configuration: its connection is the REST definition the Workspace has
a connection for (its own, else the platform's), exactly as the Work intake resolves it
(``secure_work/custom_rest/listing.resolve_list`` and ``acting_role``, reused here). Resolving at save and again at
every run means a definition that was deactivated, an operation that was disabled, or a grant that was withdrawn
refuses the next run with a fixed reason instead of reading with whatever is left.

Checked beyond the Work intake, because a Knowledge source also reads one record's content:

- a ``detail_operation`` must be an enabled read of the same definition that the acting role holds a grant of, and
  its id parameter must be decidable (``detail_param``, or the operation's only path parameter);
- an ``updated_since_param`` must be a parameter the list operation declares (an undeclared one would be refused by
  the executor on every incremental run).

The intake's refusal codes (``custom_rest_role_required`` ...) are fixed strings and become the run's reason as is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .....models import RestApiDefinition, RestApiOperation
from .....models.project.knowledge_source_sync import CONNECTOR_KIND_CUSTOM_REST
from ....rest_connector.authorization import matching_grants
from ....rest_connector.common import is_read_operation
from ....rest_connector.schema import declared_parameters
from ....secure_work.custom_rest.listing import (
    CODE_NOT_A_READ,
    CODE_OPERATION_UNAVAILABLE,
    CODE_ROLE_NOT_GRANTED,
    acting_role,
    operation_of,
    resolve_list,
)
from ....secure_work.servicenow.source import IntakeSourceError
from .contract import ConnectorError

CODE_DETAIL_PARAM_REQUIRED = "custom_rest_detail_param_required"
CODE_SINCE_PARAM_UNKNOWN = "custom_rest_since_param_unknown"
MAX_REASON_CHARS = 40


@dataclass(frozen=True)
class RestSourceConnection:
    """What one run reads with: the definition, its list (and detail) operation and the one role it acts as."""

    definition: RestApiDefinition
    operation: RestApiOperation
    role: str
    detail: RestApiOperation | None = None
    detail_param: str | None = None
    kind: str = CONNECTOR_KIND_CUSTOM_REST


def _refused(code: str) -> ConnectorError:
    return ConnectorError(code[:MAX_REASON_CHARS])


def _detail_param(operation: RestApiOperation, configured: str | None) -> str:
    declared = declared_parameters(operation)
    if configured:
        if configured not in declared:
            raise _refused(CODE_DETAIL_PARAM_REQUIRED)
        return configured
    path_params = [name for name, param in declared.items() if param["in"] == "path"]
    if len(path_params) != 1:
        raise _refused(CODE_DETAIL_PARAM_REQUIRED)
    return path_params[0]


async def _detail(db: AsyncSession, definition: RestApiDefinition, scope: dict[str, Any], role: str,
                  project_id: str) -> tuple[RestApiOperation | None, str | None]:
    name = scope.get("detail_operation")
    if not name:
        return None, None
    operation = await operation_of(db, definition, str(name))
    if operation is None:
        raise _refused(CODE_OPERATION_UNAVAILABLE)
    if not is_read_operation(operation.method, bool(operation.read_only)):
        raise _refused(CODE_NOT_A_READ)
    if not matching_grants(operation, frozenset({role.lower()}), project_id):
        raise _refused(CODE_ROLE_NOT_GRANTED)
    return operation, _detail_param(operation, scope.get("detail_param"))


async def resolve_rest_connection(db: AsyncSession, project_id: str, scope: dict[str, Any]) -> RestSourceConnection:
    """The source's definition, operations and acting role, or :class:`ConnectorError` with a fixed reason."""
    try:
        definition, operation = await resolve_list(db, project_id, str(scope.get("definition") or ""),
                                                   str(scope.get("operation") or ""))
        role = acting_role(operation, scope.get("role"), project_id)
    except IntakeSourceError as error:
        raise _refused(error.code) from None
    since = scope.get("updated_since_param")
    if since and since not in declared_parameters(operation):
        raise _refused(CODE_SINCE_PARAM_UNKNOWN)
    detail, detail_param = await _detail(db, definition, scope, role, project_id)
    return RestSourceConnection(definition=definition, operation=operation, role=role, detail=detail,
                                detail_param=detail_param)


def rest_scope_within(scope: dict[str, Any], connection: object) -> bool:
    """The connection was resolved for exactly this definition (the grants, not an allowlist, scope the data)."""
    return isinstance(connection, RestSourceConnection) and connection.definition.key == scope.get("definition")


__all__ = ["RestSourceConnection", "resolve_rest_connection", "rest_scope_within"]
