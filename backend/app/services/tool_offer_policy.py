"""The one decision which registry tools a person's turn or session sees: the chat's final tool policies and the session
MCP endpoint (``mcp_registry_tools``) both call ``policy_visible_definitions``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..tools.visibility import filter_tool_definitions_by_visibility
from .tool_access_policy import filter_tool_definitions_for_project_policy


def policy_visible_definitions(
    definitions: list[dict[str, Any]],
    context: Any,
    *,
    confirmed_per_call: Callable[[str], bool] | None = None,
) -> list[dict[str, Any]]:
    from .work_role_model.surfaces import filter_definitions

    config = getattr(context, "project_config", None)
    visible = filter_tool_definitions_by_visibility(definitions, config)
    visible = filter_definitions(visible, getattr(context, "work_role_grant", None))
    return filter_tool_definitions_for_project_policy(visible, config, confirmed_per_call=confirmed_per_call)


__all__ = ["policy_visible_definitions"]
