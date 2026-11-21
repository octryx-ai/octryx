"""The extra Knowledge MCP tool tables (Claude Code parity), free of server and runner imports.

``mcp_governed_knowledge`` and ``mcp_parity_dispatch`` merge these tables into their own, so this
module imports neither of them (no import cycle):

- ``EXTRA_GOVERNED_MCP_TOOLS``: chat tool classes for ``run_governed_mcp_tool`` (connector reads,
  diagrams, governed web search and fetch, the structured graph), all ``knowledge:read``;
- ``EXTRA_HANDLER_MCP_TOOLS``: platform handlers for ``run_parity_mcp_tool`` (``knowledge_sources``
  with ``knowledge:read``, ``knowledge_feedback`` with ``knowledge:write``);
- ``EXTRA_MCP_EVIDENCE_TOOLS``: the evidence tools a workflow contract may require that MCP
  serves, for ``mcp_workflow_tools.MCP_EVIDENCE_TOOLS``.
"""

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
