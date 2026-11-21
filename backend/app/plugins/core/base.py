"""Plugin system base classes and interfaces."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginMetadata:
    """Metadata for a plugin."""

    id: str
    name: str
    version: str
    description: str
    author: str = ""
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


@dataclass
class PluginToolDefinition:
    """Tool definition for OpenRouter function calling."""

    name: str
    description: str
    parameters: dict[str, Any]
    risk: str | None = None
    scopes: tuple[str, ...] = ()
    required_config: str | None = None
    mutates_state: bool | None = None
    filesystem_access: str = "none"
    network_access: str = "none"
    audit_required: bool | None = None


class BasePlugin(ABC):
    """Base class for all plugins (generic plugins like tools, skills, etc.)."""

    metadata: PluginMetadata

    @abstractmethod
    async def execute(self, params: dict, context: Any) -> dict[str, Any]:
        """Execute the plugin with given parameters.

        Args:
            params: Tool parameters from the LLM
            context: ToolContext with user/project information

        Returns:
            dict with 'success' and 'data' or 'error' keys
        """
        pass

    @abstractmethod
    def get_tools(self) -> list[PluginToolDefinition]:
        """Return list of tool definitions this plugin provides."""
        pass

    def on_load(self) -> None:
        """Called when plugin is loaded. Override for initialization."""
        pass

    def on_unload(self) -> None:
        """Called when plugin is unloaded. Override for cleanup."""
        pass


class ChannelPlugin(ABC):
    """
    Abstract base class for all channel plugins.
    Each channel plugin must implement these methods to integrate with Octryx.

    ``INBOUND_POLLING`` marks a plugin that pulls its inbound messages itself (IMAP, long polling,
    sync loops). Such a loop must run in exactly one process: the one that runs the background
    workers. Elsewhere (an API process of a split deployment) the plugin is loaded for sending only,
    with ``config["__inbound"] = False``. Webhook-driven plugins receive in whichever
    API process the webhook reaches.
    """

    INBOUND_POLLING = False

    def __init__(self, plugin_id: str, config: dict[str, Any]):
        self.plugin_id = plugin_id
        self.config = config
        self.enabled = config.get("enabled", False)
        self._initialized = False

    @property
    def inbound_enabled(self) -> bool:
        """``False`` when this process only sends through the channel (no inbound polling loop here)."""
        return self.config.get("__inbound", True) is not False

    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the plugin. This is called after the plugin is loaded.
        Should set up connections, authenticate, and prepare to receive/send messages.
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """
        Shutdown the plugin. Clean up resources, close connections.
        """
        pass

    @abstractmethod
    async def send_message(self, target: str, content: str, **kwargs) -> bool:
        """
        Send a message to a target (user, room, group, etc.) via this channel.
        Returns True if successful, False otherwise.
        """
        pass

    @abstractmethod
    async def receive_message(self) -> dict[str, Any] | None:
        """
        Receive a message from the channel.
        Should return a dict with at least:
        - sender_id: identifier of the sender
        - content: message text
        - target: where the message was sent to (room, group, user id)
        - timestamp: when the message was sent (ISO string or epoch)
        - raw: the original payload from the channel (for debugging/audit)
        Return None if no message is available (non-blocking poll).
        """
        pass

    @abstractmethod
    def get_plugin_info(self) -> dict[str, Any]:
        """
        Return metadata about this plugin for display in admin panel.
        Should include: name, description, version, author, etc.
        """
        pass

    def is_enabled(self) -> bool:
        return self.enabled

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
