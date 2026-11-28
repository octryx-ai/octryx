"""Closed run states of the commands the code-quality tools run (OpenRewrite, tests, linters)."""

from __future__ import annotations

from typing import Any

RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_TIMED_OUT = "timed_out"
RUN_REFUSED = "refused"
RUN_NOT_STARTED = "not_started"
RUN_STATUSES = frozenset({RUN_SUCCEEDED, RUN_FAILED, RUN_TIMED_OUT, RUN_REFUSED, RUN_NOT_STARTED})

TIMED_OUT_EXIT_CODE = 124
NOT_STARTED_EXIT_CODE = 125
COMMAND_TIMED_OUT_CODE = "command_timed_out"
COMMAND_NOT_STARTED_CODE = "command_not_started"

# The deadline a caller (or the model, through a tool's ``timeout_sec``) may ask for is bounded.
MIN_COMMAND_TIMEOUT_SEC = 1
MAX_COMMAND_TIMEOUT_SEC = 1800


def bounded_command_timeout(value: Any) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = MIN_COMMAND_TIMEOUT_SEC
    return max(MIN_COMMAND_TIMEOUT_SEC, min(requested, MAX_COMMAND_TIMEOUT_SEC))


def run_outcome_fields(result: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "status": result.get("status") or (RUN_SUCCEEDED if result.get("exit_code") == 0 else RUN_FAILED),
        "timed_out": result.get("status") == RUN_TIMED_OUT,
    }
    for key in ("error", "error_code", "timeout_sec"):
        if result.get(key) is not None:
            fields[key] = result[key]
    return fields


def run_did_not_finish(result: dict[str, Any]) -> bool:
    return result.get("status") in {RUN_TIMED_OUT, RUN_REFUSED, RUN_NOT_STARTED}


def unfinished_run_blocker(result: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    status = str(result.get("status") or "")
    messages = {
        RUN_TIMED_OUT: "The run hit its deadline and its whole process tree was killed; it produced no result.",
        RUN_REFUSED: "The platform refused the run before it started.",
        RUN_NOT_STARTED: "The execution runtime could not start the run.",
    }
    return {
        "code": str(result.get("error_code") or status),
        "severity": "blocking",
        "tool_name": tool_name,
        "message": messages.get(status, "The run did not finish."),
    }


__all__ = [
    "COMMAND_NOT_STARTED_CODE",
    "COMMAND_TIMED_OUT_CODE",
    "MAX_COMMAND_TIMEOUT_SEC",
    "MIN_COMMAND_TIMEOUT_SEC",
    "NOT_STARTED_EXIT_CODE",
    "RUN_FAILED",
    "RUN_NOT_STARTED",
    "RUN_REFUSED",
    "RUN_STATUSES",
    "RUN_SUCCEEDED",
    "RUN_TIMED_OUT",
    "TIMED_OUT_EXIT_CODE",
    "bounded_command_timeout",
    "run_did_not_finish",
    "run_outcome_fields",
    "unfinished_run_blocker",
]
