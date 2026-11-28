"""Diagram tools on the Knowledge MCP: the chat's ``create_diagram``, ``edit_diagram`` and ``append_diagram``."""

from __future__ import annotations

from typing import Any

from ..tools.diagram import AppendDiagramTool, CreateDiagramTool, EditDiagramTool
from .mcp_connector_tools import require_read_only
from .mcp_extra_scope import WorkspaceBoundTool


def _diagram_tools() -> dict[str, Any]:
    served: dict[str, Any] = {}
    for tool in (CreateDiagramTool(), EditDiagramTool(), AppendDiagramTool()):
        require_read_only(tool.name)
        served[tool.name] = WorkspaceBoundTool(tool)
    return served


ARTIFACT_MCP_TOOLS: dict[str, Any] = _diagram_tools()

__all__ = ["ARTIFACT_MCP_TOOLS"]
