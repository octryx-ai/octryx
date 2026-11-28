"""Bounds, output tails and the serialized view of a durable runtime process."""

from __future__ import annotations

from typing import Any

from ..models import RuntimeProcess
from .process_output_redaction import redact_process_output

MAX_PROCESS_OUTPUT_CHARS = 50_000
MIN_PROCESS_TIMEOUT_SECONDS = 1
MAX_PROCESS_TIMEOUT_SECONDS = 8 * 60 * 60


def serialize_runtime_process(process_record: RuntimeProcess) -> dict[str, Any]:
    return {
        "process_id": process_record.id,
        "status": process_record.status,
        "command": process_record.command,
        "cwd": process_record.cwd,
        "workspace_root": process_record.workspace_root,
        "provider": process_record.provider,
        "os_pid": process_record.os_pid,
        "timeout_seconds": process_record.timeout_seconds,
        "timeout_at": process_record.timeout_at.isoformat() if process_record.timeout_at else None,
        "started_at": process_record.started_at.isoformat() if process_record.started_at else None,
        "updated_at": process_record.updated_at.isoformat() if process_record.updated_at else None,
        "completed_at": process_record.completed_at.isoformat() if process_record.completed_at else None,
        "cancel_requested_at": (
            process_record.cancel_requested_at.isoformat() if process_record.cancel_requested_at else None
        ),
        "exit_code": process_record.exit_code,
        # Stored tails are redacted on write; they are redacted again here with the redaction rules in force.
        "stdout_tail": redact_process_output(process_record.stdout_tail),
        "stderr_tail": redact_process_output(process_record.stderr_tail),
        "output_truncated": bool(process_record.output_truncated),
        "runtime_metadata": process_record.runtime_metadata,
        "error": process_record.error,
    }


def _bounded_timeout(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 3600
    return max(MIN_PROCESS_TIMEOUT_SECONDS, min(parsed, MAX_PROCESS_TIMEOUT_SECONDS))


def _bounded_text(value: bytes) -> tuple[str, bool]:
    # The process log is the product the user watches, so it is kept, but redacted before it
    # is stored and before the tail is cut (a cut could split a secret past recognition).
    text = redact_process_output(value)
    if len(text) <= MAX_PROCESS_OUTPUT_CHARS:
        return text, False
    return text[-MAX_PROCESS_OUTPUT_CHARS:], True


def _terminal_status(exit_code: int | None, *, cancel_requested: bool) -> str:
    if cancel_requested:
        return "cancelled"
    return "completed" if exit_code == 0 else "failed"
