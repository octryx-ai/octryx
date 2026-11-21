"""CLI execution runtime tool implementation."""

from __future__ import annotations

import shlex
from time import perf_counter

from app.tools.context import ToolContext

from ...services.change_preview import build_command_change_preview
from ...services.coding_validation import parse_command_argv
from ...services.execution_runtime import execute_with_runtime
from ...services.workspace_change_safety import is_validation_command
from ._runtime_cli_command_run import (
    CliCommandPlan,
    completed_result,
    execution_records,
    finish_workspace_guard,
    not_completed_result,
    prepare_workspace_guard,
    redacted_outputs,
    server_build_refusal,
    shell_operator_refusal,
    validation_refusal_fields,
)
from ._runtime_cli_helpers import (
    _command_likely_writes_workspace,
    _command_resolution_error,
    _contains_shell_control_operators,
    _resolve_effective_command,
    _workspace_root,
)
from ._runtime_cli_script_resolution import _maybe_resolve_script_command
from ._runtime_command_policy import _policy_block_result
from ._runtime_cwd_resolution import _resolve_cwd


class RunCLICommandTool:
    """Run a CLI command in the workspace. Prefer read-only commands in diagnosis mode."""

    name = "run_cli_command"
    description = "Run a CLI command in the workspace. Prefer read-only commands in diagnosis mode."

    async def preview(self, params: dict[str, object], context: ToolContext) -> dict:
        command = str(params.get("command") or "").strip()
        if not command:
            return {"kind": "shell", "title": "CLI command", "summary": "", "details": ["No command provided."]}
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError:
            cwd = _workspace_root(context)
        return build_command_change_preview(self.name, command, cwd=str(cwd))

    async def execute(self, params: dict, context: ToolContext) -> dict:
        command = params.get("command")
        if not command:
            return {"error": "command is required"}
        validation_argv = parse_command_argv(command)
        command_is_validation = is_validation_command(validation_argv) if validation_argv else False

        timeout_sec = int(params.get("timeout_sec") or 30)
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {
                "error": str(exc),
                **validation_refusal_fields(command_is_validation, command=command, cwd=params.get("cwd"),
                                            error=str(exc)),
            }

        blocked = await _policy_block_result(self.name, command, context)
        if blocked is not None:
            return blocked | {"cwd": str(cwd)}

        effective_command, resolution, effective_cwd = _resolve_effective_command(
            command, cwd=cwd, context=context, script_resolver=_maybe_resolve_script_command
        )
        resolution_error = _command_resolution_error(command=command, cwd=cwd, resolution=resolution)
        if resolution_error is not None:
            return resolution_error | validation_refusal_fields(
                command_is_validation, command=command, cwd=str(cwd), error=str(resolution_error.get("error") or "")
            )

        if _contains_shell_control_operators(effective_command):
            return shell_operator_refusal(command, cwd, resolution, command_is_validation)

        try:
            argv = shlex.split(effective_command, posix=True)
        except ValueError as exc:
            return {"error": f"Invalid command syntax: {exc}", "command": command, "cwd": str(cwd)}
        if not argv:
            return {"error": "command is required", "cwd": str(cwd)}
        plan = CliCommandPlan(
            tool_name=self.name, params=params, command=command, effective_command=effective_command, cwd=cwd,
            effective_cwd=effective_cwd, workspace_root=_workspace_root(context), argv=argv,
            resolution=resolution,
            command_is_validation=command_is_validation or is_validation_command(argv), timeout_sec=timeout_sec,
        )
        return await self._run(plan, context)

    async def _run(self, plan: CliCommandPlan, context: ToolContext) -> dict:
        guard, refusal = await prepare_workspace_guard(
            plan, context, command_writes_workspace=_command_likely_writes_workspace(plan.argv)
        )
        if refusal is not None:
            return refusal

        started_at = perf_counter()
        runtime_result = await execute_with_runtime(
            db=context.db,
            project_config=context.project_config,
            command=plan.argv,
            cwd=plan.effective_cwd,
            workspace_root=plan.workspace_root,
            timeout_sec=plan.timeout_sec,
        )
        duration_ms = int((perf_counter() - started_at) * 1000)
        if (build_refusal := server_build_refusal(plan, runtime_result)) is not None:
            return build_refusal
        stdout_text, stderr_text = redacted_outputs(runtime_result)
        validation_outcome, execution_event = execution_records(
            plan, runtime_result, stdout_text=stdout_text, stderr_text=stderr_text, duration_ms=duration_ms
        )
        workspace_sync, workspace_change_contract = await finish_workspace_guard(
            plan, guard, context, runtime_result.exit_code
        )
        incomplete = not_completed_result(
            plan, runtime_result, guard, execution_event=execution_event, validation_outcome=validation_outcome,
            workspace_sync=workspace_sync, workspace_change_contract=workspace_change_contract,
        )
        if incomplete is not None:
            return incomplete
        return completed_result(
            plan, runtime_result, guard, context, stdout_text=stdout_text, stderr_text=stderr_text,
            execution_event=execution_event, validation_outcome=validation_outcome,
            workspace_sync=workspace_sync, workspace_change_contract=workspace_change_contract,
        )


__all__ = ["RunCLICommandTool"]
