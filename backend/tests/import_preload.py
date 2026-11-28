"""Import every workflow-run module once, before the first test runs, so a test's monkeypatch can never become
a lazily imported module's ``from ... import`` binding for the rest of the worker."""

from __future__ import annotations

import importlib
import pkgutil

PRELOADED_PACKAGES = ("app.services.workflow_runs",)


def preload(packages: tuple[str, ...] = PRELOADED_PACKAGES) -> list[str]:
    names: list[str] = []
    for package_name in packages:
        package = importlib.import_module(package_name)
        for module in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            importlib.import_module(module.name)
            names.append(module.name)
    return names
