"""Content fingerprints and job keys of registered schedules.

A fingerprint covers exactly the fields that decide a registration: for a Scheduler its id, cron
expression, active flag and target task; for a Task its id, schedule and active flag. ``Task`` has
no ``updated_at`` and ``Scheduler.updated_at`` is an application-clock value, so neither time is
part of it: an identical re-save leaves the registration untouched. The encoding is canonical JSON
of a fixed-order list, so no two different tuples share an encoding (no separator ambiguity).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

SCHEDULER_KIND = "scheduler"
TASK_KIND = "task"


def _digest(parts: list[Any]) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def scheduler_fingerprint(scheduler: Any) -> str:
    return _digest([SCHEDULER_KIND, scheduler.id, scheduler.cron_expression,
                    getattr(scheduler, "is_active", None) is True, scheduler.task_id])


def task_fingerprint(task: Any) -> str:
    return _digest([TASK_KIND, task.id, task.schedule, getattr(task, "is_active", None) is True])


def job_key(kind: str, object_id: str) -> str:
    """The acknowledgement key: ``scheduler:<id>`` or ``task:<id>``."""
    return f"{kind}:{object_id}"


def apscheduler_job_id(kind: str, object_id: str) -> str:
    """The in-memory APScheduler job id (``scheduler_<id>`` / ``task_<id>``) that registration, removal and the
    registered-jobs list use; the coordination tables key the same job as :func:`job_key`."""
    return f"{kind}_{object_id}"


def parse_job_key(key: str) -> tuple[str, str]:
    kind, _, object_id = key.partition(":")
    return kind, object_id


@dataclass(frozen=True)
class ScheduleRecord:
    """A detached snapshot of the fields one registration needs."""

    kind: str
    id: str
    expression: str
    task_id: str
    name: str
    fingerprint: str

