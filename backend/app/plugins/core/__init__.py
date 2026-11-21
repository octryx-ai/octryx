"""Canonical core plugin infrastructure."""

from .base import BasePlugin, ChannelPlugin, PluginMetadata, PluginToolDefinition
from .manager import (
    PLUGIN_INSTANCES,
    disable_plugin,
    enable_plugin,
    execute_plugin_tool,
    get_all_discovered_plugins,
    get_all_tool_names,
    get_loaded_plugins,
    get_plugin_tools,
    is_plugin_discovered,
    is_plugin_enabled,
    load_plugins,
    reload_plugins,
)
from .registry import PluginRegistry

__all__ = [
    "BasePlugin",
    "ChannelPlugin",
    "PluginMetadata",
    "PluginToolDefinition",
    "PluginRegistry",
    "PLUGIN_INSTANCES",
    "disable_plugin",
    "enable_plugin",
    "execute_plugin_tool",
    "get_all_discovered_plugins",
    "get_all_tool_names",
    "get_loaded_plugins",
    "get_plugin_tools",
    "is_plugin_discovered",
    "is_plugin_enabled",
    "load_plugins",
    "reload_plugins",
]
