"""The names a device phase's model calls for its tools (``phase.tools.on_device`` of the run contract)."""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from ...agent_gateway.capability import PLATFORM_MCP_TOOL_PREFIX

# Server tool -> Claude Code's native tool that does the same on the device (read_evidence maps the reads back).
NATIVE_EQUIVALENT = {
    "read_workspace_file": "Read",
    "grep_workspace": "Grep",
    "code_search": "Grep",
    "glob_workspace_files": "Glob",
    "list_workspace_directory": "LS/Glob",
    "write_workspace_file": "Write",
    "edit_workspace_file": "Edit",
    "multi_edit_workspace_file": "MultiEdit/Edit",
    "apply_patch_workspace": "Edit",
    "run_test_suite": "Bash",
    "run_cli_command": "Bash",
    "bash": "Bash",
}


@lru_cache(maxsize=1)
def knowledge_mcp_tools() -> frozenset[str]:
    from ...mcp_knowledge_protocol import build_knowledge_mcp_server
    from ...mcp_registry_tools import served_definitions

    # A phase lists its registry tools in full on the session endpoint (``mcp_session_surface.listed``).
    registry = {str(definition["function"]["name"]) for definition in served_definitions()}
    return frozenset(build_knowledge_mcp_server().code_tool_descriptions()) | registry


def device_tool_names(allow: Iterable[str], deny: Iterable[str] = (), *,
                      mcp_tools: frozenset[str] | None = None) -> list[str]:
    offered = knowledge_mcp_tools() if mcp_tools is None else mcp_tools
    denied = set(deny)
    native: dict[str, list[str]] = {}
    platform: list[str] = []
    for tool in allow:
        if tool in denied:
            continue
        if tool in NATIVE_EQUIVALENT:
            native.setdefault(NATIVE_EQUIVALENT[tool], []).append(tool)
        elif tool in offered:
            platform.append(PLATFORM_MCP_TOOL_PREFIX + tool)
    return [f"{name} ({', '.join(sources)})" for name, sources in native.items()] + platform


__all__ = ["NATIVE_EQUIVALENT", "device_tool_names", "knowledge_mcp_tools"]
