"""Validation command outcome classification for governed coding runs."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from app.services.process_output_redaction import redact_process_output

_MISSING_TOOL_PATTERNS = (
    re.compile(r"(?i)\bcommand not found\b"),
    re.compile(r"(?i)\bnot recognized as (?:an internal|a)"),
    re.compile(r"(?i)\bexecutable file not found\b"),
    re.compile(r"(?i)\bno such file or directory\b"),
    re.compile(r"(?i)\berrno 2\b"),
)
_MANUAL_VALIDATION_PHRASES = (
    "manual verification required",
    "manual validation required",
    "repository-specific validation must be selected",
)


def parse_command_argv(command: Any) -> list[str]:
    if isinstance(command, list):
        return [str(part) for part in command if str(part).strip()]
    try:
        return shlex.split(str(command or ""), posix=True)
    except ValueError:
        return []


def _classify_outcome(
    *, command_text: str, text: str, timed_out: bool, executable: str, exit_code: int | None
) -> tuple[str, str, str]:
    if _is_manual_validation(command_text):
        status = "manual_required"
        blocker = "manual_validation_required"
        required_action = "Record manual validation evidence before delivery."
    elif _is_wrong_cwd_error(text):
        status = "wrong_cwd"
        blocker = "validation_cwd_invalid"
        required_action = "Run validation from an approved repository working directory."
    elif timed_out:
        status = "timed_out"
        blocker = "validation_timed_out"
        required_action = "Review the validation command timeout or use an approved longer-running validation path."
    elif _is_missing_tool(executable=executable, exit_code=exit_code, text=text):
        status = "missing_tool"
        blocker = "validation_tool_missing"
        required_action = f"Install or configure `{executable or 'required executable'}` in the validation environment."
    elif exit_code is None:
        status = "not_runnable"
        blocker = "validation_not_runnable"
        required_action = "Fix the validation environment before retrying this command."
    elif exit_code == 0:
        status = "passed"
        blocker = ""
        required_action = ""
    else:
        status = "failed"
        blocker = "validation_failed"
        required_action = "Fix the implementation or update the approved validation plan before delivery."
    return status, blocker, required_action


def build_validation_outcome(
    *,
    command: Any,
    cwd: str | Path | None,
    exit_code: int | None = None,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    error: str = "",
    execution_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    argv = parse_command_argv(command)
    executable = Path(argv[0]).name if argv else ""
    text = "\n".join(str(value or "") for value in (stdout, stderr, error))
    command_text = " ".join(argv) if argv else str(command or "").strip()

    status, blocker, required_action = _classify_outcome(
        command_text=command_text, text=text, timed_out=timed_out, executable=executable, exit_code=exit_code
    )

    return {
        "version": "validation_outcome.v1",
        "status": status,
        "command": command_text,
        "cwd": str(cwd or ""),
        "executable": executable,
        "exit_code": exit_code,
        "runtime": dict(execution_runtime or {}),
        "blocker": blocker,
        "required_action": required_action,
        # The validation run's own output is the evidence the agent repairs from: kept, through the
        # redactor. A platform-side ``error`` (a free exception text) is classified into
        # ``status``/``blocker`` above and never copied into the evidence.
        "evidence": {
            "stdout_excerpt": redact_process_output(stdout, max_chars=1200),
            "stderr_excerpt": redact_process_output(stderr, max_chars=1200),
        },
    }


def _is_manual_validation(command_text: str) -> bool:
    normalized = str(command_text or "").strip().lower()
    return any(phrase in normalized for phrase in _MANUAL_VALIDATION_PHRASES)


def _is_wrong_cwd_error(text: str) -> bool:
    normalized = str(text or "").lower()
    return "cwd" in normalized and (
        "stay inside workspace root" in normalized
        or "must stay inside workspace root" in normalized
        or "not a directory" in normalized
    )


def _is_missing_tool(*, executable: str, exit_code: int | None, text: str) -> bool:
    normalized = str(text or "")
    if exit_code == 127:
        return True
    if not any(pattern.search(normalized) for pattern in _MISSING_TOOL_PATTERNS):
        return False
    if not executable:
        return True
    return executable.lower() in normalized.lower() or exit_code is None
