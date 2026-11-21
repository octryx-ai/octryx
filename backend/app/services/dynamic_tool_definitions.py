from __future__ import annotations

from typing import Any

from ..tools.context import ToolContext


async def list_runtime_dynamic_tool_definitions(db: Any, tool_context: ToolContext) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    try:
        from app.services.database_tool.query_tool_admin import list_dynamic_database_tool_definitions

        definitions.extend(await list_dynamic_database_tool_definitions(db, tool_context))
    except Exception:
        definitions = []
    try:
        from .rest_connector.tool_surface import list_rest_tool_definitions

        definitions.extend(await list_rest_tool_definitions(db, tool_context))
    except Exception:
        pass
    try:
        from .flow_capabilities import list_flow_tool_definitions

        definitions.extend(await list_flow_tool_definitions(db, tool_context))
    except Exception:
        pass
    return definitions
