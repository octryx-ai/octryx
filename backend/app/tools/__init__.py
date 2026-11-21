"""Tools package with lazy registry exports to avoid import cycles."""

from __future__ import annotations

from importlib import import_module

from .context import ToolContext

__all__ = [
    "TOOL_REGISTRY",
    "execute_tool",
    "get_tool_definitions",
    "get_all_tools_with_plugins",
    "execute_tool_with_plugins",
    "ToolContext",
]


def __getattr__(name: str):
    if name in {
        "TOOL_REGISTRY",
        "execute_tool",
        "get_tool_definitions",
        "get_all_tools_with_plugins",
        "execute_tool_with_plugins",
    }:
        registry = import_module(".registry", __name__)
        return getattr(registry, name)
    raise AttributeError(name)
