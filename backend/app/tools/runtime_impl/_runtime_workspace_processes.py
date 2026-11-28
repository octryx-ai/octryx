"""Durable runtime process tools."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ...services.durable_process_runtime import (
    cancel_runtime_process,
    collect_runtime_process,
    poll_runtime_process,
    start_runtime_process,
)
from ...services.workspace_change_safety import (
    build_workspace_change_contract,
    capture_workspace_change_state,
    workspace_has_dirty_files,
)
from ._runtime_cli_helpers import (
    _command_likely_writes_workspace,
    _contains_shell_control_operators,
    _ensure_repository_for_write,
    _workspace_root,
)
from ._runtime_command_policy import _policy_block_result
from ._runtime_cwd_resolution import _resolve_cwd


async def _audit_refusal(command: str, where: str, reason: str) -> None:
    from ...services.execution_runtime import command_audit

    try:
        await command_audit.record(command, verdict="refused", where=where, reason=reason)
    except command_audit.CommandAuditUnavailableError:
        pass  # refused either way


async def _start_audit_refusal(command: str, argv: list[str], cwd: Path) -> dict[str, Any] | None:
    from ...services.execution_runtime import command_audit
    from ...services.execution_runtime.foreign_build_guard import cwd_verdict, refusal_payload

    if (inside := cwd_verdict(cwd)) is not None:
        await _audit_refusal(command, "start_runtime_process", inside.command_class)
        return refusal_payload(inside, command=command) | {"cwd": str(cwd)}
    try:  # one audit row before the process starts; its exit is the process record's
        await command_audit.record(argv, verdict="executed", where="start_runtime_process")
    except command_audit.CommandAuditUnavailableError:
        return command_audit.unavailable_payload(argv) | {"cwd": str(cwd)}
    return None


async def _mutating_process_guard(
    tool_name: str, params: dict, context: ToolContext, *, argv: list[str], command: str, cwd: Path
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not _command_likely_writes_workspace(argv):
        return None, None
    bootstrap = await _ensure_repository_for_write(context)
    if bootstrap and bootstrap.get("status") == "error":
        return None, {"error": "Repository bootstrap failed", "repository_bootstrap": bootstrap, "cwd": str(cwd)}
    before_change_state = capture_workspace_change_state(_workspace_root(context))
    if workspace_has_dirty_files(before_change_state) and not bool(params.get("allow_dirty_workspace")):
        return None, {
            "error": (
                "Refusing to start a mutating runtime process while the workspace already has "
                "uncommitted changes. If the dirty state is your own intended work for this "
                "change, retry with allow_dirty_workspace=true."
            ),
            "command": command,
            "cwd": str(cwd),
            "workspace_change_contract": build_workspace_change_contract(
                tool_name=tool_name,
                before_state=before_change_state,
            ),
            **({"repository_bootstrap": bootstrap} if bootstrap else {}),
        }
    workspace_change_contract = build_workspace_change_contract(
        tool_name=tool_name,
        before_state=before_change_state,
        override_dirty=bool(params.get("allow_dirty_workspace")),
    )
    return workspace_change_contract, None


class StartRuntimeProcessTool:
    """Start a long-running process and return a durable process id."""

    name = "start_runtime_process"
    description = "Start a long-running workspace process and return a durable process id for polling."

    async def execute(self, params: dict, context: ToolContext) -> dict:
        if context.db is None:
            return {"error": "start_runtime_process requires a database-bound tool context."}
        command = str(params.get("command") or "").strip()
        if not command:
            return {"error": "command is required"}
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        blocked = await _policy_block_result(self.name, command, context)
        if blocked is not None:
            return blocked | {"cwd": str(cwd)}
        if _contains_shell_control_operators(command):
            return {
                "error": (
                    "start_runtime_process only supports direct executable invocations. "
                    "Use a saved script or explicit executable arguments for shell operators."
                ),
                "command": command,
                "cwd": str(cwd),
            }
        try:
            argv = shlex.split(command, posix=True)
        except ValueError as exc:
            return {"error": f"Invalid command syntax: {exc}", "command": command, "cwd": str(cwd)}
        if not argv:
            return {"error": "command is required", "cwd": str(cwd)}

        workspace_root = _workspace_root(context)
        workspace_change_contract, refusal = await _mutating_process_guard(
            self.name, params, context, argv=argv, command=command, cwd=cwd
        )
        if refusal is not None:
            return refusal

        if (start_refusal := await _start_audit_refusal(command, argv, cwd)) is not None:
            return start_refusal
        result = await start_runtime_process(
            context.db,
            command=argv,
            cwd=cwd,
            workspace_root=workspace_root,
            user_id=context.user_id,
            session_id=context.session_id,
            project_id=(context.project_ids or [None])[0],
            project_config=context.project_config,
            tool_name=self.name,
            timeout_seconds=int(params.get("timeout_sec") or params.get("timeout_seconds") or 3600),
        )
        result["kind"] = "runtime_process"
        if workspace_change_contract is not None:
            result["workspace_change_contract"] = workspace_change_contract
        return result


class PollRuntimeProcessTool:
    """Poll a durable runtime process."""

    name = "poll_runtime_process"
    description = "Poll a durable runtime process by id and return current status and bounded output."

    async def execute(self, params: dict, context: ToolContext) -> dict:
        if context.db is None:
            return {"error": "poll_runtime_process requires a database-bound tool context."}
        process_id = str(params.get("process_id") or "").strip()
        if not process_id:
            return {"error": "process_id is required"}
        result = await poll_runtime_process(context.db, process_id=process_id, user_id=context.user_id)
        result["kind"] = "runtime_process"
        return result


class CollectRuntimeProcessTool:
    """Collect a durable runtime process result."""

    name = "collect_runtime_process"
    description = "Collect a durable runtime process result, optionally waiting briefly for completion."

    async def execute(self, params: dict, context: ToolContext) -> dict:
        if context.db is None:
            return {"error": "collect_runtime_process requires a database-bound tool context."}
        process_id = str(params.get("process_id") or "").strip()
        if not process_id:
            return {"error": "process_id is required"}
        result = await collect_runtime_process(
            context.db,
            process_id=process_id,
            user_id=context.user_id,
            wait_seconds=int(params.get("wait_seconds") or 0),
        )
        result["kind"] = "runtime_process"
        return result


class CancelRuntimeProcessTool:
    """Cancel a durable runtime process."""

    name = "cancel_runtime_process"
    description = "Cancel a durable runtime process by id."

    async def execute(self, params: dict, context: ToolContext) -> dict:
        if context.db is None:
            return {"error": "cancel_runtime_process requires a database-bound tool context."}
        process_id = str(params.get("process_id") or "").strip()
        if not process_id:
            return {"error": "process_id is required"}
        result = await cancel_runtime_process(context.db, process_id=process_id, user_id=context.user_id)
        result["kind"] = "runtime_process"
        return result


__all__ = [
    "CancelRuntimeProcessTool",
    "CollectRuntimeProcessTool",
    "PollRuntimeProcessTool",
    "StartRuntimeProcessTool",
]
