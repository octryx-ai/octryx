"""Diagram tools on the Knowledge MCP: the chat's ``create_diagram``, ``edit_diagram`` and ``append_diagram``.

All three chat classes (``tools/diagram.py``) are pure payload producers: they repair and validate
the model's ``<mxCell>`` elements and return the complete draw.io XML (``diagram_xml``, ``format:
drawio``). None writes a file or a session artifact, so the MCP call needs no session workspace; the
call is attached to the grant's MCP auto session like every governed MCP tool, and the client gets
exactly the payload the chat gets. Their metadata is ``risk: read`` without state mutation.

Office files are deliberately **not** offered here: the raw Office tools write into a session workspace an MCP
connection does not have.
"""

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
