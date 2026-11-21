"""Fixed facts about a local runtime command (docker compose up/stop, host process start).

The command's stderr/stdout are never returned: docker compose prints image names, registry
hosts, compose paths and, with a credential helper misconfiguration, registry credentials. The
admin panel and the local bootstrap see a closed result code plus the exit status only.
"""

from __future__ import annotations

from typing import Any

RESULT_SUCCEEDED = "command_succeeded"
RESULT_FAILED = "command_failed"
RESULT_TIMED_OUT = "command_timed_out"

HOST_BINARY_NOT_FOUND = "local_binary_not_found"
HOST_START_NOT_CONFIGURED = "host_process_start_not_configured"
HOST_START_FAILED = "host_process_start_failed"
_HOST_ERRORS = frozenset({HOST_BINARY_NOT_FOUND, HOST_START_NOT_CONFIGURED, HOST_START_FAILED})


def _exit_code(run_result: dict[str, Any]) -> int | None:
    code = run_result.get("returncode")
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def command_result_code(run_result: dict[str, Any]) -> str:
    if run_result.get("ok"):
        return RESULT_SUCCEEDED
    if run_result.get("timed_out") or _exit_code(run_result) is None:
        return RESULT_TIMED_OUT
    return RESULT_FAILED


def command_facts(run_result: dict[str, Any], *, action: str) -> dict[str, Any]:
    """The returned ``command`` entry: action, closed result code and exit status, no output text."""
    facts: dict[str, Any] = {
        "ok": bool(run_result.get("ok")),
        "action": action,
        "result_code": command_result_code(run_result),
        "exit_code": _exit_code(run_result),
    }
    if run_result.get("host_fallback"):
        facts["host_fallback"] = True
    return facts


def command_failure_text(run_result: dict[str, Any], *, action: str) -> str:
    """``docker_compose_up_failed exit_code=1`` / ``docker_compose_stop_timed_out``."""
    if command_result_code(run_result) == RESULT_TIMED_OUT:
        return f"docker_compose_{action}_timed_out"
    return f"docker_compose_{action}_failed exit_code={_exit_code(run_result)}"


def host_fallback_failure_text(run_result: dict[str, Any], host_result: dict[str, Any]) -> str:
    """The compose failure plus the host process start's closed error code."""
    host_error = str(host_result.get("error_code") or "")
    host_error = host_error if host_error in _HOST_ERRORS else HOST_START_FAILED
    return f"local_runtime_start_failed {command_failure_text(run_result, action='up')} host_error={host_error}"


__all__ = [
    "HOST_BINARY_NOT_FOUND",
    "HOST_START_FAILED",
    "HOST_START_NOT_CONFIGURED",
    "command_facts",
    "command_failure_text",
    "command_result_code",
    "host_fallback_failure_text",
]
