"""Which Custom REST read operations a Workspace can use as a Knowledge source (Knowledge › Sources).

Why on the Knowledge side: the Work intake's discovery
(``/api/v1/secure-work/.../intake/fields``), which needs Secure Work access; a Workspace owner who may configure
Knowledge sources need not have it. This answers the same question for Knowledge,
from the same rows, and nothing more than picking an operation needs.

**Who sees what.**

- a platform admin: every active definition, also one without a connection here (``connection: null``, so the admin
  sees what to add) and every enabled read operation (``usable: false`` without a grant for this Workspace);
- a Workspace owner/admin: only definitions the Workspace can reach (its own connection or the platform's,
  ``connections.connection_for_call``: exactly what a run resolves, ``rest_connection.resolve_rest_connection``) and
  only read operations granted here (a grant for every Workspace or for this one). Another Workspace's own connection
  or grant never shows.

**Never in the answer**: servers, auth scheme, connection URL or config, secret refs, a parameter's fixed value or a
grant's scope values (they may be credentials or narrow another role's data). A parameter the grants inject says so
(``scoped``) instead of showing the value.
"""

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
    """The definitions and read operations this caller may pick for a ``custom_rest`` source of ``project_id``."""
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
