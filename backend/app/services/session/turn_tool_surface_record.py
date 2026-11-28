"""The tool surface a turn ran with, as session state."""

from __future__ import annotations

from typing import Any

TOOL_SURFACE_SOURCE_METADATA_KEY = "tool_surface_source"
TOOL_SURFACE_SET_METADATA_KEY = "tool_surface_set"

TOOL_SURFACE_SELECTED_DEFINITION = "selected_definition"
TOOL_SURFACE_SELECTED_WORKFLOW = "selected_workflow"
TOOL_SURFACE_AGENT_DEFINITION = "agent_definition"
TOOL_SURFACE_WORKSPACE_POLICY = "workspace_policy"
TOOL_SURFACE_GOVERNED_DEFAULT = "governed_default"
# The agent declares No tools (text only): the turn offers nothing, whatever else is selected.
TOOL_SURFACE_AGENT_NO_TOOLS = "agent_no_tools"
# A phase turn of a workflow run whose phase declares no tool_policy allow rules: fail closed, never a family surface.
TOOL_SURFACE_PHASE_WITHOUT_POLICY = "phase_without_tool_policy"
TOOL_SURFACE_SOURCES = (
    TOOL_SURFACE_AGENT_NO_TOOLS,
    TOOL_SURFACE_PHASE_WITHOUT_POLICY,
    TOOL_SURFACE_SELECTED_DEFINITION,
    TOOL_SURFACE_SELECTED_WORKFLOW,
    TOOL_SURFACE_AGENT_DEFINITION,
    TOOL_SURFACE_WORKSPACE_POLICY,
    TOOL_SURFACE_GOVERNED_DEFAULT,
)


def record_tool_surface_metadata(metadata: dict[str, Any], *, source: str, surface_set: str) -> None:
    metadata[TOOL_SURFACE_SOURCE_METADATA_KEY] = source
    metadata[TOOL_SURFACE_SET_METADATA_KEY] = surface_set or None


__all__ = [
    "TOOL_SURFACE_AGENT_DEFINITION",
    "TOOL_SURFACE_AGENT_NO_TOOLS",
    "TOOL_SURFACE_GOVERNED_DEFAULT",
    "TOOL_SURFACE_PHASE_WITHOUT_POLICY",
    "TOOL_SURFACE_SELECTED_DEFINITION",
    "TOOL_SURFACE_SELECTED_WORKFLOW",
    "TOOL_SURFACE_SET_METADATA_KEY",
    "TOOL_SURFACE_SOURCES",
    "TOOL_SURFACE_SOURCE_METADATA_KEY",
    "TOOL_SURFACE_WORKSPACE_POLICY",
    "record_tool_surface_metadata",
]
