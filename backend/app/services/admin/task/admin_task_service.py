"""Admin-panel service helpers for task management flows."""

from __future__ import annotations

from ._admin_task_dependencies import (
    creates_task_dependency_cycle as _creates_task_dependency_cycle,
)
from ._admin_task_stats import serialize_task_with_stats as _serialize_task_with_stats

serialize_task_with_stats = _serialize_task_with_stats
creates_task_dependency_cycle = _creates_task_dependency_cycle

__all__ = [
    "serialize_task_with_stats",
    "creates_task_dependency_cycle",
]
