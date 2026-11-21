"""Node statuses and the small value types the DAG executor passes around."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

NODE_STATUS_PENDING = "pending"
NODE_STATUS_RUNNING = "running"
NODE_STATUS_COMPLETED = "completed"
NODE_STATUS_FAILED = "failed"
NODE_STATUS_PAUSED = "paused"
NODE_STATUS_SKIPPED = "skipped"
NODE_STATUS_CANCELLED = "cancelled"


@dataclass
class RuntimeFlowVersion:
    id: str
    definition_json: dict[str, Any]


class FlowPausedError(Exception):
    """Raised when a node intentionally pauses the flow."""

    def __init__(self, reason: str, output: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.output = output or {"reason": reason}
