"""Canonical package exports for session service modules."""

from __future__ import annotations

import importlib

_PUBLIC_MODULES = frozenset(
    {
        "api",
        "collaboration",
        "entity",
        "run_state",
        "stream",
        "tool_cache",
        "workspace",
        "workspace_restore",
        "workspace_sync",
        "workspace_storage",
    }
)


def __getattr__(name: str):
    if name in _PUBLIC_MODULES:
        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _PUBLIC_MODULES)


__all__ = sorted(_PUBLIC_MODULES)
