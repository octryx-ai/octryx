"""Plugin package exports."""

import hashlib
import json
import logging

from app.services.error_facts import error_text

from .channels import EmailPlugin, MatrixPlugin, SlackPlugin, TeamsPlugin, TelegramPlugin
from .core import (
    PLUGIN_INSTANCES,
    BasePlugin,
    ChannelPlugin,
    PluginMetadata,
    PluginRegistry,
    PluginToolDefinition,
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

logger = logging.getLogger(__name__)


class _PluginManager:
    """Channel plugin manager – manages lifecycle of ChannelPlugin instances."""

    def __init__(self):
        self._plugins: dict[str, ChannelPlugin] = {}
        self._plugin_classes: dict[str, type] = {}
        # channel id -> fingerprint of the configuration last applied in this process: the
        # channel reconciler (services/channel_config/runtime_sync) skips what this process already applied.
        self._applied: dict[str, str] = {}
        self._register_known_plugins()

    @staticmethod
    def channel_fingerprint(plugin_id: str, config: dict) -> str:
        """A stable digest of a channel's runtime configuration (the process-local ``__inbound`` excluded)."""
        material = {"plugin_id": plugin_id, "config": {k: v for k, v in config.items() if k != "__inbound"}}
        return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()

    def applied_fingerprint(self, channel_id: str) -> str | None:
        return self._applied.get(channel_id)

    def applied_channel_ids(self) -> set[str]:
        return set(self._applied) | set(self._plugins)

    def forget_channel(self, channel_id: str) -> None:
        self._applied.pop(channel_id, None)

    def _inbound_here(self, cls: type) -> bool:
        """Polling inbound runs only in the process with the background workers; webhook inbound anywhere."""
        from ..runtime_toggles import background_workers_enabled

        return background_workers_enabled() or not getattr(cls, "INBOUND_POLLING", False)

    def _register_known_plugins(self) -> None:
        _to_register = [
            ("telegram", ".channels.telegram", "TelegramPlugin"),
            ("email", ".channels.email_plugin", "EmailPlugin"),
            ("msteams", ".channels.teams_plugin", "TeamsPlugin"),
            ("matrix", ".channels.matrix_plugin", "MatrixPlugin"),
            ("slack", ".channels.slack_plugin", "SlackPlugin"),
        ]
        for plugin_id, module_path, class_name in _to_register:
            try:
                import importlib

                mod = importlib.import_module(module_path, package=__name__)
                self._plugin_classes[plugin_id] = getattr(mod, class_name)
            except Exception as e:
                logger.warning("Could not register plugin '%s': %s", plugin_id, error_text("plugin_register_failed", e))

    # ------------------------------------------------------------------ info
    def get_known_plugin_ids(self) -> list:
        return list(self._plugin_classes.keys())

    def get_plugin_info(self, plugin_id: str) -> dict:
        """Return metadata / config_fields for a plugin (uses running instance or temp one)."""
        plugin = self._plugins.get(plugin_id)
        if plugin:
            return plugin.get_plugin_info()
        cls = self._plugin_classes.get(plugin_id)
        if cls:
            try:
                instance = cls(plugin_id, {})
                return instance.get_plugin_info()
            except Exception:
                pass
        return {"id": plugin_id, "name": plugin_id, "description": "", "config_fields": []}

    def get_status(self, plugin_id: str) -> str:
        return "running" if any(plugin.plugin_id == plugin_id for plugin in self._plugins.values()) else "stopped"

    def get_channel_status(self, channel_id: str) -> str:
        return "running" if channel_id in self._plugins else "stopped"

    def get_channel(self, channel_id: str) -> ChannelPlugin | None:
        return self._plugins.get(channel_id)

    def get_channels_for_plugin(self, plugin_id: str) -> list[tuple[str, ChannelPlugin]]:
        return [(channel_id, plugin) for channel_id, plugin in self._plugins.items() if plugin.plugin_id == plugin_id]

    def get_single_channel_for_plugin(self, plugin_id: str) -> tuple[str, ChannelPlugin] | None:
        matches = self.get_channels_for_plugin(plugin_id)
        if len(matches) == 1:
            return matches[0]
        return None

    def iter_channels(self) -> list[tuple[str, ChannelPlugin]]:
        return list(self._plugins.items())

    # ---------------------------------------------------------------- lifecycle
    def load_channel(self, channel_id: str, plugin_id: str, config: dict) -> ChannelPlugin | None:
        cls = self._plugin_classes.get(plugin_id)
        if not cls:
            logger.warning(f"No plugin class registered for plugin_id: {plugin_id}")
            return None
        try:
            plugin = cls(plugin_id, {**config, "__inbound": self._inbound_here(cls)})
            self._plugins[channel_id] = plugin
            return plugin
        except Exception as e:
            logger.error("Failed to instantiate plugin %s: %s", plugin_id, error_text("plugin_instantiate_failed", e))
            return None

    async def initialize_channel(self, channel_id: str) -> bool:
        plugin = self._plugins.get(channel_id)
        if not plugin:
            return False
        try:
            await plugin.initialize()
            return True
        except Exception as e:
            logger.error(
                    "Failed to initialize channel %s (%s): %s",
                    channel_id,
                    plugin.plugin_id,
                    error_text("channel_initialize_failed", e),
                )
            self._plugins.pop(channel_id, None)
            return False

    async def start_channel(self, channel_id: str) -> bool:
        """No-op – initialization already starts the plugin (e.g. starts polling)."""
        return channel_id in self._plugins

    async def stop_channel(self, channel_id: str) -> bool:
        plugin = self._plugins.pop(channel_id, None)
        if plugin:
            try:
                await plugin.shutdown()
                logger.info(f"Channel {channel_id} ({plugin.plugin_id}) stopped")
                return True
            except Exception as e:
                logger.error("Error stopping channel %s: %s", channel_id, error_text("channel_stop_failed", e))
        return False

    async def stop_all(self) -> None:
        for channel_id in list(self._plugins.keys()):
            await self.stop_channel(channel_id)

    async def reload_channel(self, channel_id: str, plugin_id: str, new_config: dict) -> bool:
        """Stop the plugin (if running), then start it again if enabled."""
        self._applied[channel_id] = self.channel_fingerprint(plugin_id, new_config)
        await self.stop_channel(channel_id)
        if new_config.get("enabled"):
            plugin = self.load_channel(channel_id, plugin_id, new_config)
            if plugin:
                return await self.initialize_channel(channel_id)
        return True


plugin_manager = _PluginManager()

__all__ = [
    "BasePlugin",
    "ChannelPlugin",
    "EmailPlugin",
    "MatrixPlugin",
    "SlackPlugin",
    "TeamsPlugin",
    "TelegramPlugin",
    "PluginMetadata",
    "PluginToolDefinition",
    "PluginRegistry",
    "PLUGIN_INSTANCES",
    "plugin_manager",
    "get_all_discovered_plugins",
    "load_plugins",
    "get_plugin_tools",
    "get_all_tool_names",
    "execute_plugin_tool",
    "enable_plugin",
    "disable_plugin",
    "is_plugin_discovered",
    "is_plugin_enabled",
    "reload_plugins",
    "get_loaded_plugins",
]
