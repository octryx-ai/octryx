"""The "connection" of a Custom REST Knowledge source: its definition, operations and acting role, resolved per run."""

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
    return isinstance(connection, RestSourceConnection) and connection.definition.key == scope.get("definition")


__all__ = ["RestSourceConnection", "resolve_rest_connection", "rest_scope_within"]
