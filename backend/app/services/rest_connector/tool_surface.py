"""The ``rest__`` tools a caller is offered: enabled operations of active definitions they are granted."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import RestApiDefinition, RestApiOperation
from ...tools.definitions.rest_tool_classes import remember_rest_tool
from . import odata
from .authorization import caller_roles, matching_grants, scope_choices
from .common import tool_name_for, write_capability
from .schema import build_parameters_schema


def tool_description(definition: Any, operation: Any) -> str:
    text = (operation.llm_description or operation.summary or "").strip()
    if not text:
        text = f"{operation.method.upper()} {operation.path}"
    if write_capability(operation) is None:
        return f"{text} (REST API {definition.name}, read-only)"
    return f"{text} (REST API {definition.name}; this changes data there and runs after a person's confirmation)"


async def refresh_rest_tool(db: AsyncSession, tool_name: str) -> None:
    from .executor import find_operation

    found = await find_operation(db, tool_name)
    remember_rest_tool(tool_name, write_capability(found[1]) if found is not None else None)


async def list_rest_tool_definitions(db: AsyncSession, context: Any) -> list[dict[str, Any]]:
    from ..mcp_workspace_context import workspace_id_for_context

    rows = (await db.execute(
        select(RestApiDefinition, RestApiOperation)
        .join(RestApiOperation, RestApiOperation.definition_id == RestApiDefinition.id)
        .where(RestApiDefinition.is_active.is_(True), RestApiOperation.enabled.is_(True))
        .order_by(RestApiDefinition.key, RestApiOperation.op_key)
    )).all()
    if not rows:
        return []
    workspace_id = workspace_id_for_context(context) or None
    roles = await caller_roles(db, context, workspace_id)
    definitions: list[dict[str, Any]] = []
    for definition, operation in rows:
        name = tool_name_for(definition.key, operation.llm_name or operation.op_key)
        remember_rest_tool(name, write_capability(operation))
        grants = matching_grants(operation, roles, workspace_id)
        if not grants:
            continue
        paginated = odata.effective_response(definition, operation)[1]["type"] != "none"
        definitions.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool_description(definition, operation),
                "parameters": build_parameters_schema(operation, scope_choices=scope_choices(grants),
                                                      paginated=paginated),
            },
        })
    return definitions


__all__ = ["list_rest_tool_definitions", "refresh_rest_tool", "tool_description"]
