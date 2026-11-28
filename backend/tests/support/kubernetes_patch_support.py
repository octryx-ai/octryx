"""Replaces a Kubernetes core helper (``app.tools.kubernetes``) everywhere a tool module imported it by name."""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

import app.tools


def patch_kubernetes(monkeypatch: Any, name: str, value: Any) -> None:
    for module_info in pkgutil.iter_modules(app.tools.__path__):
        if module_info.name == "kubernetes" or module_info.name.startswith("kubernetes_"):
            module = importlib.import_module(f"app.tools.{module_info.name}")
            if hasattr(module, name):
                monkeypatch.setattr(module, name, value)
