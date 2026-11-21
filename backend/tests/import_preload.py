"""Import every workflow-run module once, before the first test runs.

Many workflow-run modules bind ``dispatch_tool`` (and other helpers) with ``from .dispatch import ...`` at import
time, and several are imported lazily inside functions. If a module's first import happens during a test that
monkeypatches the source attribute, the module keeps the test's fake for the rest of the worker and later tests call
it. Importing them all up front means a monkeypatch can only replace an attribute, never become a module's binding.
"""

from __future__ import annotations

import importlib
import pkgutil

PRELOADED_PACKAGES = ("app.services.workflow_runs",)


def preload(packages: tuple[str, ...] = PRELOADED_PACKAGES) -> list[str]:
    """Import every module below each package; return the names imported."""
    names: list[str] = []
    for package_name in packages:
        package = importlib.import_module(package_name)
        for module in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            importlib.import_module(module.name)
            names.append(module.name)
    return names
