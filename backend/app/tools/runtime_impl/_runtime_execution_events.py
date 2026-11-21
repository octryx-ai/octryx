"""Execution event helpers for runtime tools."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def build_execution_event(
    *,
    kind: str,
    tool_name: str,
    cwd: str,
    status: str,
    command: str | Sequence[str] | None = None,
    exit_code: int | None = None,
    duration_ms: int | None = None,
    stdout: str = "",
    stderr: str = "",
    max_output_chars: int = 8000,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the stable audit/event shape for a runtime execution attempt."""

    event: dict[str, Any] = {
        "kind": kind,
        "tool_name": tool_name,
        "cwd": cwd,
        "status": status,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout_chars": len(stdout),
        "stderr_chars": len(stderr),
        "stdout_truncated": len(stdout) > max_output_chars,
        "stderr_truncated": len(stderr) > max_output_chars,
    }
    if command is not None:
        event["command"] = list(command) if isinstance(command, (list, tuple)) else command
    if metadata:
        event["metadata"] = metadata
    return event


def execution_status_from_exit_code(exit_code: int | None, *, timed_out: bool = False) -> str:
    if timed_out:
        return "timed_out"
    if exit_code == 0:
        return "succeeded"
    if exit_code is None:
        return "failed"
    return "failed"


__all__ = ["build_execution_event", "execution_status_from_exit_code"]
