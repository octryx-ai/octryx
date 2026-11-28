"""The structured-graph tool instances the governed MCP runner calls (``mcp_extra_tools``)."""

from __future__ import annotations

from typing import Any

from ..tools.knowledge_evidence.structured_graph import ConfigVsManualTool, GraphNeighborsTool, OpsChainTool

STRUCTURED_GRAPH_MCP_TOOLS: dict[str, Any] = {
    "graph_neighbors": GraphNeighborsTool(),
    "config_vs_manual": ConfigVsManualTool(),
    "ops_chain": OpsChainTool(),
}


__all__ = ["STRUCTURED_GRAPH_MCP_TOOLS"]
