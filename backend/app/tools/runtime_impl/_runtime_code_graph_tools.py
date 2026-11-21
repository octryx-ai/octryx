"""Native code graph tools: summary, nodes, neighbors, traces, stats, impact and context bundles."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ._runtime_code_intelligence_execution import (
    _execute_code_graph_affected,
    _execute_code_graph_callees,
    _execute_code_graph_context,
    _execute_code_graph_explore,
    _execute_code_graph_files,
    _execute_code_graph_god_nodes,
    _execute_code_graph_neighbors,
    _execute_code_graph_node,
    _execute_code_graph_stats,
    _execute_code_graph_status,
    _execute_code_graph_trace,
    _execute_graph_code_intelligence,
)


class CodeGraphSummaryTool:
    name = "code_graph_summary"
    description = "Return the repository architecture graph summary and artifact metadata."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_graph_code_intelligence(params, context)


class CodeNodeTool:
    name = "code_node"
    description = "Look up a native code graph node by id, symbol name, path or text query."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_node(params, context)


class CodeNeighborsTool:
    name = "code_neighbors"
    description = "Traverse bounded native code graph neighbors for a node, symbol name, path or query."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_neighbors(params, context)


class CodeTraceTool:
    name = "code_trace"
    description = "Find a bounded shortest path between two native code graph nodes or symbols."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_trace(params, context)


class CodeGraphStatsTool:
    name = "code_graph_stats"
    description = "Return native code graph counts, distributions and top-degree nodes."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_stats(params, context)


class CodeGraphStatusTool:
    name = "code_graph_status"
    description = "Return native code graph readiness, freshness, latest run and row-count metadata."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_status(params, context)


class CodeGodNodesTool:
    name = "code_god_nodes"
    description = "Rank high-degree native code graph nodes that may need review focus."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_god_nodes(params, context)


class CodeAffectedTool:
    name = "code_affected"
    description = "Traverse dependents or dependencies that may be affected by a code graph node."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_affected(params, context)


class CodeImpactTool:
    name = "code_impact"
    description = "Traverse graph-native dependents that may be impacted by a code graph node."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_affected(params, context)


class CodeCalleesTool:
    name = "code_callees"
    description = "Return direct static callees for a native code graph node, symbol, path or query."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_callees(params, context)


class CodeFilesTool:
    name = "code_files"
    description = "List files from the latest native code graph run with optional path and language filters."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_files(params, context)


class CodeContextTool:
    name = "code_context"
    description = "Return a budgeted native code graph context bundle around a node, symbol, path or query."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_context(params, context)


class CodeExploreTool:
    name = "code_explore"
    description = "Return a compact native code graph exploration bundle before broad repository scanning."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_code_graph_explore(params, context)


__all__ = [name for name in vars() if not name.startswith("_")]
