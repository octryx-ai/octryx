"""The extra Knowledge MCP tool tables (Claude Code parity), free of server and runner imports. Free of those imports so
the two runners can merge them without an import cycle."""

from __future__ import annotations

from typing import Any

from .mcp_artifact_tools import ARTIFACT_MCP_TOOLS
from .mcp_connector_tools import CONNECTOR_MCP_TOOLS
from .mcp_extra_knowledge import mcp_knowledge_feedback, mcp_knowledge_sources
from .mcp_structured_graph_tools import STRUCTURED_GRAPH_MCP_TOOLS
from .mcp_web_tools import WEB_MCP_TOOLS

READ_SCOPE = "knowledge:read"
WRITE_SCOPE = "knowledge:write"

EXTRA_GOVERNED_MCP_TOOLS: dict[str, tuple[Any, str]] = {
    name: (tool, READ_SCOPE)
    for name, tool in {
        **CONNECTOR_MCP_TOOLS, **ARTIFACT_MCP_TOOLS, **WEB_MCP_TOOLS, **STRUCTURED_GRAPH_MCP_TOOLS
    }.items()
}
EXTRA_HANDLER_MCP_TOOLS: dict[str, tuple[Any, str]] = {
    "knowledge_sources": (mcp_knowledge_sources, READ_SCOPE),
    "knowledge_feedback": (mcp_knowledge_feedback, WRITE_SCOPE),
}
EXTRA_MCP_EVIDENCE_TOOLS = frozenset(
    {*CONNECTOR_MCP_TOOLS, *WEB_MCP_TOOLS, *STRUCTURED_GRAPH_MCP_TOOLS, "knowledge_sources"}
)

__all__ = ["EXTRA_GOVERNED_MCP_TOOLS", "EXTRA_HANDLER_MCP_TOOLS", "EXTRA_MCP_EVIDENCE_TOOLS"]
