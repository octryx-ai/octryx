"""Which Custom REST read operations a Workspace can use as a Knowledge source (Knowledge › Sources)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models import RestApiDefinition, RestApiOperation
from ....rest_connector.authorization import Grant, grants_of
from ....rest_connector.common import is_read_operation
from ....rest_connector.connections import connection_for_call
from ....rest_connector.schema import declared_parameters


def _grants_here(operation: RestApiOperation, project_id: str) -> list[Grant]:
    return [grant for grant in grants_of(operation) if grant.workspace_id in (None, project_id)]


def _parameters(operation: RestApiOperation, grants: list[Grant]) -> list[dict[str, Any]]:
    injected = {name for grant in grants for name in grant.scope}
    return [{"name": name, "in": param["in"], "required": param["required"], "description": param["description"],
             "hidden": param["hidden"], "fixed": param["fixed"] is not None, "scoped": name in injected}
            for name, param in declared_parameters(operation).items()]


def _operation(operation: RestApiOperation, project_id: str) -> dict[str, Any]:
    grants = _grants_here(operation, project_id)
    params = _parameters(operation, grants)
    return {
        "op_key": operation.op_key,
        "name": operation.llm_name or operation.op_key,
        "method": operation.method,
        "path": operation.path,
        "summary": operation.summary,
        "parameters": params,
        # Result mapping hints: where the records are and which fields the admin keeps.
        "records_path": operation.records_path,
        "response_fields": list(operation.response_select or []),
        "paginated": str((operation.pagination or {}).get("type") or "none") != "none",
        # A read with exactly one path parameter can serve as the detail operation (``rest_connection._detail_param``).
        "detail_candidate": sum(1 for param in params if param["in"] == "path") == 1,
        "roles": sorted({grant.role for grant in grants}),
        "scoped_roles": sorted({grant.role for grant in grants if grant.scoped}),
        "role_required": any(grant.scoped for grant in grants),
        "usable": bool(grants),
    }


async def _reads(db: AsyncSession, definition: RestApiDefinition, project_id: str) -> list[dict[str, Any]]:
    rows = (await db.execute(select(RestApiOperation).where(
        RestApiOperation.definition_id == definition.id, RestApiOperation.enabled.is_(True))
        .order_by(RestApiOperation.op_key))).scalars().all()
    return [_operation(row, project_id) for row in rows if is_read_operation(row.method, bool(row.read_only))]


async def rest_source_catalog(db: AsyncSession, project_id: str, *, platform_admin: bool) -> dict[str, Any]:
    definitions = (await db.execute(select(RestApiDefinition).where(RestApiDefinition.is_active.is_(True))
                                    .order_by(RestApiDefinition.key))).scalars().all()
    listed = []
    for definition in definitions:
        connection = await connection_for_call(db, definition.id, project_id)
        if connection is None and not platform_admin:
            continue
        operations = await _reads(db, definition, project_id)
        if not platform_admin:
            operations = [operation for operation in operations if operation["usable"]]
            if not operations:
                continue
        listed.append({
            "key": definition.key,
            "name": definition.name,
            "description": definition.description,
            "connection": None if connection is None else ("workspace" if connection.scope_key == project_id
                                                           else "global"),
            "operations": operations,
        })
    return {"workspace_id": project_id, "definitions": listed}


__all__ = ["rest_source_catalog"]
