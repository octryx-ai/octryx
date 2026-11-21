"""Governed execution of the run's verification contract.

``run_validation_commands`` executes EXACTLY the commands of the approved
verification contract stored on the session (secure_work_execution) — the
agent cannot invent commands here. Each command runs in the coding workspace
with a bounded timeout; the result carries per-command exit codes and the
``all_green`` completion signal the step machine keys on.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.tools.context import ToolContext

from ...services.error_facts import error_type
from ...services.execution_runtime.process_tree import communicate_within_deadline, process_group_spawn_kwargs
from ...services.process_output_redaction import redact_process_output

_COMMAND_TIMEOUT_SEC = 300
_OUTPUT_TAIL_CHARS = 2000


async def _contract_commands(context: ToolContext) -> list[str] | None:
    if context.db is None or not context.session_id:
        return None
    from ...models import Session

    session = (
        await context.db.execute(select(Session).where(Session.id == context.session_id))
    ).scalar_one_or_none()
    if session is None:
        return None
    execution = (dict(session.metadata_ or {})).get("secure_work_execution")
    if not isinstance(execution, dict):
        return None
    contract = execution.get("verification_contract")
    if not isinstance(contract, dict):
        return None
    return [
        str(entry.get("command") or "").strip()
        for entry in (contract.get("commands") or [])
        if isinstance(entry, dict) and str(entry.get("command") or "").strip()
    ]


async def _run_command(command: str, *, cwd: Path) -> dict[str, Any]:
    from ...services.execution_runtime.server_env import server_command_env

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            env=server_command_env(),  # no secret of the API process; git runs nothing of the copy
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **process_group_spawn_kwargs(),
        )
        # The deadline (and a cancellation) kills the whole process group, not only the shell.
        bounded = await communicate_within_deadline(process, timeout_sec=_COMMAND_TIMEOUT_SEC)
        if bounded.timed_out:
            return {
                "command": command,
                "ok": False,
                "exit_code": None,
                "timed_out": True,
                "error": "timeout",
                "error_code": "validation_command_timed_out",
            }
        # The contract command's output is the verification report the agent must read: kept, redacted.
        output = redact_process_output(bounded.stdout)
        return {
            "command": command,
            "ok": process.returncode == 0,
            "exit_code": process.returncode,
            "output_tail": output[-_OUTPUT_TAIL_CHARS:],
        }
    except OSError as exc:
        # The OS error text can carry paths and environment details: only fixed facts leave.
        return {
            "command": command,
            "ok": False,
            "exit_code": None,
            "error": "validation_command_not_started",
            "error_code": "validation_command_not_started",
            "error_type": error_type(exc),
        }


class RunValidationCommandsTool:
    name = "run_validation_commands"
    description = (
        "Run the approved verification contract of this coding execution. "
        "Executes exactly the contract's commands in the workspace and returns "
        "per-command results plus all_green. The change is complete when "
        "all_green=true."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        commands = await _contract_commands(context)
        if not commands:
            return {
                "error": (
                    "No verification contract is registered for this session. "
                    "Use run_test_suite for framework-based verification instead."
                )
            }
        root = str(context.workspace_root or "").strip()
        workspace = str(params.get("cwd") or root).strip()
        if not workspace or not Path(workspace).is_dir():
            return {"error": f"Workspace directory not found: {workspace or '(unset)'}"}
        if root and not str(Path(workspace).resolve()).startswith(str(Path(root).resolve())):
            return {"error": "cwd must be inside the session workspace"}
        # The contract's commands are the repository's tests and builds; none of them runs on the server
        # (``foreign_build_guard``): the whole contract is refused before the first one starts.
        from ...services.execution_runtime import command_audit
        from ...services.execution_runtime.foreign_build_guard import cwd_verdict, guard_server_command

        for command in commands:
            refusal = guard_server_command(command, where=f"tool:{self.name}", audit={
                "session_id": context.session_id, "user_id": context.user_id})
            if refusal is None and (inside := cwd_verdict(workspace)) is not None:
                from ...services.execution_runtime.foreign_build_guard import refusal_payload

                refusal = refusal_payload(inside, command=command)
            if refusal is not None:
                try:
                    await command_audit.record(command, verdict="refused", where=f"tool:{self.name}",
                                               reason=str(refusal.get("error_code") or ""))
                except command_audit.CommandAuditUnavailableError:
                    pass  # refused either way
                return {**refusal, "all_green": False, "results": [], "command_count": len(commands),
                        "workspace": workspace}
        results = []
        for command in commands:
            try:  # one audit row before each command runs, its exit code after (never its output)
                handle = await command_audit.record(command, verdict="executed", where=f"tool:{self.name}")
            except command_audit.CommandAuditUnavailableError:
                results.append({"command": command, "ok": False, "exit_code": None,
                                **command_audit.unavailable_payload(command)})
                break
            outcome = await _run_command(command, cwd=Path(workspace))
            await command_audit.record_exit(handle, outcome.get("exit_code"), timed_out=bool(outcome.get("timed_out")))
            results.append(outcome)
        all_green = all(entry.get("ok") for entry in results)
        return {
            "all_green": all_green,
            "results": results,
            "command_count": len(results),
            "workspace": workspace,
        }

    def is_read_only(self) -> bool:
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def is_enabled(self) -> bool:
        return True


__all__ = ["RunValidationCommandsTool"]
