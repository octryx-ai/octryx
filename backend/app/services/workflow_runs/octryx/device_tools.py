"""The names a device phase's model calls for its tools (``phase.tools.on_device`` of the run contract).

A phase's ``tool_policy.allowlist`` names the platform's server tools (``list_workspace_directory``,
``read_workspace_file``, ...). On a device those do not exist: Claude Code reads and edits with its own Read / Grep /
Glob / LS / Write / Edit, and the launcher's ``octryx-knowledge`` MCP server offers only the platform tools
it registers. When the contract showed only
the server names, the model called ``mcp__octryx-knowledge__list_workspace_directory`` and got "No such tool
available". ``allow`` / ``deny`` stay the policy names the gates read; ``on_device`` is what the model calls.
"""

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
    """The tools the launcher's ``octryx-knowledge`` server really registers (built once per process)."""
    from ...mcp_knowledge_protocol import build_knowledge_mcp_server

    return frozenset(build_knowledge_mcp_server().code_tool_descriptions())


def device_tool_names(allow: Iterable[str], deny: Iterable[str] = (), *,
                      mcp_tools: frozenset[str] | None = None) -> list[str]:
    """The allowed tools as the device model calls them: native ones with the policy names they stand for, then
    the knowledge MCP tools the server offers. A server-only tool without either (``analyze_workspace_repository``)
    is left out rather than named as a tool that does not exist."""
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
