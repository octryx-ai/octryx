"""The states, triggers and bounds a structured build shares between its request, claim and slice."""

from __future__ import annotations

from dataclasses import dataclass

STATE_PENDING = "pending"
STATE_RUNNING = "running"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
# A slice result, never a stored state: another worker holds the build now, so this one stops at once.
RESULT_LOST = "lost"
TRIGGER_MANUAL = "manual"
TRIGGER_SOURCE_SYNC = "source_sync"
# Run by the projection worker between projection batches; manual builds have their own runner.
COOPERATIVE_TRIGGERS = (TRIGGER_SOURCE_SYNC,)
LEASE_SECONDS = 300
SLICE_SECONDS = 10.0
MAX_REVISIONS_PER_SLICE = 100
FAILURE_SOURCE_UNREADABLE = "source_unreadable"
FAILURE_BUILD = "build_failed"


@dataclass(frozen=True, slots=True)
class BuildLease:
    """The claim a slice writes under: ``store.write_revision`` checks and renews it in its transaction."""

    build_id: str
    worker_id: str
    lease_seconds: float


class BuildLeaseLostError(Exception):
    """Another worker claimed the build (or it ended): the write is rolled back, the slice stops."""


class StructuredSourceError(Exception):
    """One revision could not be read; it is recorded with a fixed token and not retried until it changes."""

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token


__all__ = [
    "COOPERATIVE_TRIGGERS",
    "RESULT_LOST",
    "BuildLease",
    "BuildLeaseLostError",
    "FAILURE_BUILD",
    "FAILURE_SOURCE_UNREADABLE",
    "LEASE_SECONDS",
    "MAX_REVISIONS_PER_SLICE",
    "SLICE_SECONDS",
    "STATE_COMPLETED",
    "STATE_FAILED",
    "STATE_PENDING",
    "STATE_RUNNING",
    "TRIGGER_MANUAL",
    "TRIGGER_SOURCE_SYNC",
    "StructuredSourceError",
]
