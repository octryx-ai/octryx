"""Registry mapping tool names to connector-owned result compactors.

The engine core stays neutral: it compacts generic mechanics (workspace
files, runtime commands, MCP bridge payloads, workflow capabilities) itself
and consults this registry for everything a connector or tool domain owns.
Which tool names exist and which payload shapes they produce is knowledge of
the module that registers the compactor — not of the engine. Registration is
pull-style at import time, mirroring
``app.agent.loops.control._loop_salvage_hooks``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

ToolResultCompactor = Callable[[dict[str, Any]], dict[str, Any]]

_COMPACTORS: dict[str, ToolResultCompactor] = {}


def register_tool_result_compactor(tool_name_or_prefix: str, handler: ToolResultCompactor) -> None:
    """Register a compactor for an exact tool name or a tool-name prefix."""
    key = str(tool_name_or_prefix or "").strip()
    if key:
        _COMPACTORS[key] = handler


def resolve_tool_result_compactor(tool_name: str) -> ToolResultCompactor | None:
    """Return the compactor for ``tool_name``: exact match first, then longest prefix."""
    name = str(tool_name or "").strip()
    if not name:
        return None
    exact = _COMPACTORS.get(name)
    if exact is not None:
        return exact
    best_key = ""
    best_handler: ToolResultCompactor | None = None
    for key, handler in _COMPACTORS.items():
        if name.startswith(key) and len(key) > len(best_key):
            best_key = key
            best_handler = handler
    return best_handler


def _register_builtin_compactors() -> None:
    from ....tools.code_context_compaction import register_result_compactors as register_code_result_compactors
    from ....tools.connectors.atlassian_result_compaction import (
        register_result_compactors as register_atlassian_result_compactors,
    )
    from ....tools.diagram_result_compaction import register_result_compactors as register_diagram_result_compactors
    from ....tools.knowledge_evidence.result_compaction import (
        register_result_compactors as register_knowledge_result_compactors,
    )

    register_code_result_compactors()
    register_atlassian_result_compactors()
    register_diagram_result_compactors()
    register_knowledge_result_compactors()


_register_builtin_compactors()

__all__ = [
    "ToolResultCompactor",
    "register_tool_result_compactor",
    "resolve_tool_result_compactor",
]
