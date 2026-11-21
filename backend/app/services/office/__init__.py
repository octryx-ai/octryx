"""Canonical package exports for Office service modules."""

from __future__ import annotations

import importlib

_PUBLIC_MODULES = frozenset(
    {
        "ai_template",
        "documents",
        "render",
        "storage",
        "template",
        "template_package",
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
