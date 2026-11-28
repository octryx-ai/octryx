"""The fixed tool surface of a governed agent run and its one governed dispatch closure."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...models.json_text import safe_json_dict
from ...tools.context import ToolContext
from .governed_tool import governed_tool_payload

MCP_LIST_TOOL = "list_mcp_server_tools"
MCP_CALL_TOOL = "call_mcp_server_tool"
SKILL_GET_TOOL = "skill_get"
_MAX_TOOL_RESULT_CHARS = 60_000


@dataclass(frozen=True, slots=True)
class AgentToolSurface:
    definitions: tuple[dict[str, Any], ...]
    tool_names: frozenset[str]
    mcp_servers: frozenset[str]
    skills: frozenset[str]


def _refusal(code: str) -> str:
    return json.dumps({"error": code, "tool_execution": {"status": "error", "category": "denied_by_tool_surface"}})


class AgentToolCall:
    def __init__(self, surface: AgentToolSurface, tool_context: ToolContext) -> None:
        self._surface = surface
        self._tool_context = tool_context

    def _narrowing_refusal(self, name: str, arguments: Mapping[str, Any]) -> str | None:
        if name not in self._surface.tool_names:
            return "tool_not_offered"
        if name in (MCP_LIST_TOOL, MCP_CALL_TOOL):
            server = str(arguments.get("server_name") or "").strip().casefold()
            if server not in self._surface.mcp_servers:
                return "mcp_server_not_declared"
        if name == SKILL_GET_TOOL:
            if arguments.get("skill_id") or arguments.get("id") or arguments.get("name") not in self._surface.skills:
                return "skill_not_declared"
        return None

    async def __call__(self, call: dict[str, Any]) -> str:
        function = call.get("function") if isinstance(call, dict) else None
        function = function if isinstance(function, dict) else {}
        name = str(function.get("name") or "").strip()
        raw_arguments = function.get("arguments")
        arguments = safe_json_dict(raw_arguments) if isinstance(raw_arguments, str) else {}
        refusal = self._narrowing_refusal(name, arguments)
        if refusal is not None:
            return _refusal(refusal)
        payload = await governed_tool_payload(name, arguments, self._tool_context, execution_errors=False)
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) > _MAX_TOOL_RESULT_CHARS:
            return json.dumps({"error": "tool_result_too_large", "characters": len(text)})
        return text


__all__ = ["AgentToolCall", "AgentToolSurface"]
