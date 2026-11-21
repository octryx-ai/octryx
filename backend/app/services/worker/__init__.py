"""Worker service package."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "create_worker",
    "create_worker_trust_event",
    "list_worker_trust_events",
    "list_workers",
    "patch_worker",
    "record_worker_trust_event",
    "refresh_all_workers_on_startup",
    "refresh_worker_startup_state",
    "serialize_worker",
    "serialize_worker_trust_event",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    service_module = import_module(".service", __name__)
    return getattr(service_module, name)
