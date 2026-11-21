"""Who and where one governed agent run executes: fixed for the run, never derived from model output."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    run_id: str
    attempt_id: str
    session_id: str
    workspace_id: str
    user_id: str


__all__ = ["ExecutionContext"]
