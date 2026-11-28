"""Plugin manager - discovers, loads, and manages plugins."""

import importlib
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any

from app.services.error_facts import error_text

from ...tools.definitions import (
    ToolDefinitionMetadata,
    clear_plugin_tool_metadata,
    register_plugin_tool_metadata,
)
from ...tools.results import safe_tool_error_message
from .base import BasePlugin

log = logging.getLogger(__name__)

PLUGINS_DIR = Path(__file__).resolve().parents[1]
PLUGIN_PACKAGE = "app.plugins"
PLUGIN_STATE_FILE = PLUGINS_DIR / "plugin_state.json"

ENABLED_PLUGINS: dict[str, bool] = {}
PLUGIN_INSTANCES: dict[str, BasePlugin] = {}
_BRIDGE_OWNED_PLUGIN_IDS = frozenset({"mcp"})
_VALID_PLUGIN_TOOL_RISKS = frozenset({"read", "write", "admin"})

# Modules considered safe for plugins to import (deny-list approach).
# Plugins cannot import anything outside this set to limit attack surface.
_ALLOWED_PLUGIN_IMPORTS: frozenset[str] = frozenset({
    "json", "math", "random", "re", "time", "datetime", "uuid",
    "collections", "itertools", "functools", "operator", "typing",
    "pathlib", "urllib.parse", "hashlib", "base64",
    "logging", "warnings",
})


def _load_plugin_state() -> dict[str, bool]:
    if PLUGIN_STATE_FILE.exists():
        try:
            with open(PLUGIN_STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.warning("Failed to load plugin state: %s", error_text("plugin_state_load_failed", e))
    return {}


def _save_plugin_state(state: dict[str, bool]) -> None:
    try:
        PLUGIN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PLUGIN_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.error("Failed to save plugin state: %s", error_text("plugin_state_save_failed", e))


def discover_plugins() -> list[type[BasePlugin]]:
    plugins = []

    for path in PLUGINS_DIR.iterdir():
        if path.name.startswith("_") or path.name.startswith("."):
            continue
        if path.is_dir():
            plugin_file = path / "__init__.py"
            if plugin_file.exists():
                module_name = f"{PLUGIN_PACKAGE}.{path.name}"
                plugins.extend(_load_plugin_module(module_name, plugin_file))

        elif path.suffix == ".py" and path.stem != "__init__":
            module_name = f"{PLUGIN_PACKAGE}.{path.stem}"
            try:
                module = importlib.import_module(module_name)
                for item_name in dir(module):
                    item = getattr(module, item_name)
                    if isinstance(item, type) and issubclass(item, BasePlugin) and item is not BasePlugin:
                        plugins.append(item)
                        log.info(f"Discovered plugin: {item.__name__}")
            except Exception as e:
                log.error("Failed to load plugin module %s: %s", path, error_text("plugin_module_load_failed", e))

    return plugins


def _load_plugin_module(module_name: str, file_path: Path) -> list[type[BasePlugin]]:
    # Snapshot sys.modules before loading to detect pollution afterward
    pre_modules = set(sys.modules.keys())
    plugins = []
    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Check for dangerous import pollution
            post_modules = set(sys.modules.keys())
            new_modules = post_modules - pre_modules
            dangerous = [m for m in new_modules if _is_dangerous_module(m)]
            if dangerous:
                log.warning(
                    f"Plugin {module_name} imported dangerous modules: {dangerous}. "
                    f"These are ignored but indicate a security concern."
                )

            for item_name in dir(module):
                item = getattr(module, item_name)
                if isinstance(item, type) and issubclass(item, BasePlugin) and item is not BasePlugin:
                    plugins.append(item)
                    log.info(f"Discovered plugin: {item.__name__}")
    except Exception as e:
        log.error("Failed to load plugin from %s: %s", file_path, error_text("plugin_load_failed", e))
    return plugins


def _is_dangerous_module(module_name: str) -> bool:
    if module_name in _ALLOWED_PLUGIN_IMPORTS:
        return False
    # Block top-level dangerous packages
    top_level = module_name.split(".")[0]
    dangerous_toplevel = {
        "os", "subprocess", "socket", "urllib", "http", "ftplib", "telnetlib",
        "poplib", "imaplib", "smtplib", "xmlrpc", "multiprocessing", "ctypes",
        "resource", "sys", "importlib", "pkgutil", "runpy",
        "sqlite3", "dbm", "anydbm", "commands", "pickle", "marshal",
    }
    return top_level in dangerous_toplevel


def load_plugins() -> dict[str, BasePlugin]:
    """Load and instantiate all discovered plugins."""
    global PLUGIN_INSTANCES, ENABLED_PLUGINS

    ENABLED_PLUGINS = _load_plugin_state()
    PLUGIN_INSTANCES.clear()
    plugin_classes = discover_plugins()

    for plugin_cls in plugin_classes:
        try:
            instance = plugin_cls()
            plugin_id = instance.metadata.id

            if ENABLED_PLUGINS.get(plugin_id, True):
                instance.on_load()
                PLUGIN_INSTANCES[plugin_id] = instance
                log.info(f"Loaded plugin: {plugin_id} v{instance.metadata.version}")
            else:
                log.info(f"Plugin {plugin_id} is disabled")
        except Exception as e:
            log.error(
                "Failed to instantiate plugin %s: %s", plugin_cls.__name__, error_text("plugin_instantiate_failed", e)
            )

    return PLUGIN_INSTANCES


def get_plugin_tools() -> list[dict[str, Any]]:
    """Get tool definitions from all loaded plugins."""
    tools = []
    refresh_plugin_tool_metadata()
    for plugin, tool_def, metadata in iter_governed_plugin_tools():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool_def.name,
                    "description": tool_def.description,
                    "parameters": tool_def.parameters,
                },
                "metadata": {
                    "owner_type": metadata.owner_type,
                    "source": metadata.source,
                    "risk": metadata.risk,
                    "required_config": metadata.required_config,
                    "scopes": list(metadata.scopes),
                    "mutates_state": metadata.mutates_state,
                    "filesystem_access": metadata.filesystem_access,
                    "network_access": metadata.network_access,
                    "audit_required": metadata.audit_required,
                },
            }
        )
    return tools


def get_all_tool_names() -> list[str]:
    """Get list of all tool names from plugins."""
    return get_model_visible_plugin_tool_names()


def iter_model_visible_plugins():
    for plugin in PLUGIN_INSTANCES.values():
        plugin_id = str(getattr(getattr(plugin, "metadata", None), "id", "") or "").strip().lower()
        if plugin_id in _BRIDGE_OWNED_PLUGIN_IDS:
            continue
        yield plugin


def _plugin_id(plugin: BasePlugin) -> str:
    return str(getattr(getattr(plugin, "metadata", None), "id", "") or "").strip().lower()


def _plugin_tool_definition_metadata(plugin: BasePlugin, tool_def: Any) -> ToolDefinitionMetadata | None:
    risk = str(getattr(tool_def, "risk", "") or "").strip().lower()
    if risk not in _VALID_PLUGIN_TOOL_RISKS:
        return None
    plugin_id = _plugin_id(plugin)
    if not plugin_id:
        return None
    scopes = tuple(
        str(scope or "").strip()
        for scope in (getattr(tool_def, "scopes", ()) or ())
        if str(scope or "").strip()
    )
    if not scopes:
        scopes = (f"plugin:{plugin_id}",)
    mutates_state = bool(getattr(tool_def, "mutates_state", risk in {"write", "admin"}))
    audit_required = bool(getattr(tool_def, "audit_required", risk in {"write", "admin"}))
    return ToolDefinitionMetadata(
        is_core=False,
        owner_type="plugin",
        source="plugin",
        risk=risk,
        approval_required=risk in {"write", "admin"},
        required_config=str(getattr(tool_def, "required_config", "") or f"plugin:{plugin_id}"),
        scopes=scopes,
        mutates_state=mutates_state,
        filesystem_access=str(getattr(tool_def, "filesystem_access", "none") or "none"),
        network_access=str(getattr(tool_def, "network_access", "none") or "none"),
        audit_required=audit_required,
    )


def iter_governed_plugin_tools():
    for plugin in iter_model_visible_plugins():
        for tool_def in plugin.get_tools():
            metadata = _plugin_tool_definition_metadata(plugin, tool_def)
            if metadata is None:
                continue
            yield plugin, tool_def, metadata


def refresh_plugin_tool_metadata() -> None:
    clear_plugin_tool_metadata()
    for _, tool_def, metadata in iter_governed_plugin_tools():
        register_plugin_tool_metadata(str(tool_def.name), metadata)


def get_model_visible_plugin_tool_names() -> list[str]:
    refresh_plugin_tool_metadata()
    return [str(tool_def.name) for _, tool_def, _ in iter_governed_plugin_tools()]


async def execute_plugin_tool(tool_name: str, params: dict, context: Any) -> dict:
    """Execute a plugin tool by name."""
    refresh_plugin_tool_metadata()
    for plugin, tool_def, _ in iter_governed_plugin_tools():
        if tool_def.name == tool_name:
            plugin_id = _plugin_id(plugin)
            try:
                result = await plugin.execute(params, context)
                return result
            except Exception as e:
                safe_error = safe_tool_error_message(e)
                return {
                    "error": f"Plugin tool execution failed: {safe_error}",
                    "tool_name": tool_name,
                    "plugin_id": plugin_id,
                    "source": "plugin",
                    "error_category": "execution_failed",
                    "reason": "plugin_tool_exception",
                }
    return {
        "error": f"Plugin tool not found: {tool_name}",
        "tool_name": tool_name,
        "source": "plugin",
        "error_category": "invalid_name",
        "reason": "plugin_tool_not_found",
    }


def enable_plugin(plugin_id: str) -> bool:
    """Enable a plugin."""
    global ENABLED_PLUGINS

    ENABLED_PLUGINS[plugin_id] = True
    _save_plugin_state(ENABLED_PLUGINS)

    return True


def disable_plugin(plugin_id: str) -> bool:
    """Disable a plugin."""
    global ENABLED_PLUGINS

    if plugin_id in PLUGIN_INSTANCES:
        plugin = PLUGIN_INSTANCES[plugin_id]
        plugin.on_unload()
        del PLUGIN_INSTANCES[plugin_id]

    ENABLED_PLUGINS[plugin_id] = False
    _save_plugin_state(ENABLED_PLUGINS)

    return True


def is_plugin_enabled(plugin_id: str) -> bool:
    """Check if a plugin is enabled."""
    return plugin_id in PLUGIN_INSTANCES


def is_plugin_discovered(plugin_id: str) -> bool:
    """Check if a plugin is discovered (exists but may be disabled)."""
    plugin_classes = discover_plugins()
    for plugin_cls in plugin_classes:
        try:
            instance = plugin_cls()
            if instance.metadata.id == plugin_id:
                return True
        except Exception:
            pass
    return False


def reload_plugins() -> dict[str, BasePlugin]:
    """Reload all plugins."""
    global PLUGIN_INSTANCES
    for plugin in PLUGIN_INSTANCES.values():
        plugin.on_unload()
    PLUGIN_INSTANCES.clear()
    return load_plugins()


def get_loaded_plugins() -> list[dict[str, Any]]:
    """Get list of loaded plugins with metadata."""
    return [
        {
            "id": plugin.metadata.id,
            "name": plugin.metadata.name,
            "version": plugin.metadata.version,
            "description": plugin.metadata.description,
            "author": plugin.metadata.author,
            "tags": plugin.metadata.tags,
            "tools": [t.name for t in plugin.get_tools()],
            "enabled": True,
        }
        for plugin in PLUGIN_INSTANCES.values()
    ]


def get_all_discovered_plugins() -> list[dict[str, Any]]:
    """Get list of all discovered plugins with their status."""
    discovered = []
    plugin_classes = discover_plugins()
    state = _load_plugin_state()

    for plugin_cls in plugin_classes:
        try:
            instance = plugin_cls()
            plugin_id = instance.metadata.id
            is_loaded = plugin_id in PLUGIN_INSTANCES

            discovered.append(
                {
                    "id": plugin_id,
                    "name": instance.metadata.name,
                    "version": instance.metadata.version,
                    "description": instance.metadata.description,
                    "author": instance.metadata.author,
                    "tags": instance.metadata.tags,
                    "tools": [t.name for t in instance.get_tools()],
                    "enabled": is_loaded,
                    "manually_disabled": state.get(plugin_id, None) is False,
                }
            )
        except Exception as e:
            log.error("Failed to get plugin info: %s", error_text("plugin_info_failed", e))

    return discovered
