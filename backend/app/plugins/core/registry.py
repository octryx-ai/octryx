import importlib
import logging
import pkgutil

from app.services.error_facts import error_text

from .base import ChannelPlugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """
    Discovers and loads channel plugins from a given package or directory.
    """

    def __init__(self, plugin_package: str = "backend.app.plugins.channels"):
        """
        Args:
            plugin_package: The Python package where channel plugins are located.
                            Plugins should be modules or packages in this package,
                            each containing a class that inherits from ChannelPlugin.
                            The class should be named the same as the module or
                            specified in a variable `Plugin` in the module.
        """
        self.plugin_package = plugin_package
        self._plugin_classes: dict[str, type[ChannelPlugin]] = {}

    def discover_plugins(self) -> dict[str, type[ChannelPlugin]]:
        """
        Discover all plugins in the plugin_package.
        Returns a dictionary mapping plugin_id to plugin class.
        """
        self._plugin_classes = {}

        try:
            package = importlib.import_module(self.plugin_package)
        except ImportError as e:
            logger.error(
                "Could not import plugin package %s: %s",
                self.plugin_package,
                error_text("plugin_package_import_failed", e),
            )
            return self._plugin_classes

        # If the package is a namespace package, we need to iterate over its submodules
        if hasattr(package, "__path__"):
            for importer, modname, ispkg in pkgutil.walk_packages(
                path=package.__path__, prefix=package.__name__ + ".", onerror=lambda x: None
            ):
                try:
                    module = importlib.import_module(modname)
                    # Look for a class that inherits from ChannelPlugin
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if isinstance(attr, type) and issubclass(attr, ChannelPlugin) and attr is not ChannelPlugin:
                            # Use the module name (last part) as the plugin id by default
                            plugin_id = modname.split(".")[-1]
                            self._plugin_classes[plugin_id] = attr
                            logger.info(f"Discovered plugin: {plugin_id} from {modname}")
                except Exception as e:
                    logger.exception(f"Failed to load plugin module {modname}: {e}")
        else:
            # It's a single module, not a package
            for attr_name in dir(package):
                attr = getattr(package, attr_name)
                if isinstance(attr, type) and issubclass(attr, ChannelPlugin) and attr is not ChannelPlugin:
                    plugin_id = attr_name.lower()
                    self._plugin_classes[plugin_id] = attr
                    logger.info(f"Discovered plugin: {plugin_id} in {self.plugin_package}")

        return self._plugin_classes

    def get_plugin_class(self, plugin_id: str) -> type[ChannelPlugin] | None:
        """Get the plugin class for a given plugin_id."""
        return self._plugin_classes.get(plugin_id)

    def get_all_plugin_classes(self) -> dict[str, type[ChannelPlugin]]:
        """Get a copy of all discovered plugin classes."""
        return self._plugin_classes.copy()
