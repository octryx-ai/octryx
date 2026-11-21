"""Building blocks of ``run_cli_command``: the run plan, workspace change guard, execution records and results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ...services.coding_validation import build_validation_outcome
from ...services.execution_runtime.foreign_build_guard import runtime_refusal
from ...services.process_output_redaction import redact_process_output
from ...services.session.workspace_sync import (
    capture_workspace_file_snapshot,
    resolve_workspace_sync_policy,
    sync_workspace_changes_since_snapshot,
)
from ...services.workspace_change_safety import (
    build_workspace_change_contract,
    capture_workspace_change_state,
    workspace_has_dirty_files,
)
from ._runtime_cli_helpers import _ensure_repository_for_write, _truncate, detect_system_context
from ._runtime_execution_events import build_execution_event, execution_status_from_exit_code


@dataclass(frozen=True, kw_only=True)
class CliCommandPlan:
    """A resolved ``run_cli_command`` call, ready to run: what the agent asked for and what actually runs."""

    tool_name: str
    params: dict
    command: Any
    effective_command: str
    cwd: Path
    effective_cwd: Path
    workspace_root: Path
    argv: list[str]
    resolution: dict[str, Any] | None
    command_is_validation: bool
    timeout_sec: int


@dataclass
class CliWorkspaceGuard:
    """Workspace state captured before a command that may write the workspace or validate a change."""

    bootstrap: dict[str, Any] | None = None
    before_change_state: Any = None
    workspace_sync_policy: Any = None
    before_workspace_snapshot: Any = None


def validation_refusal_fields(command_is_validation: bool, *, command: Any, cwd: Any, error: str) -> dict[str, Any]:
    """A refused validation command still reports its validation outcome."""
    outcome = build_validation_outcome(command=command, cwd=cwd, error=error) if command_is_validation else None
    return {"validation_outcome": outcome} if outcome else {}


def shell_operator_refusal(command: Any, cwd: Path, resolution: dict[str, Any] | None,
                           command_is_validation: bool) -> dict[str, Any]:
    return {
        "error": (
            "run_cli_command only supports direct executable invocations. "
            "Use the bash tool for shell operators, pipes, redirects, or command chaining."
        ),
        "command": command,
        "cwd": str(cwd),
        **({"script_resolution": resolution} if resolution else {}),
        **validation_refusal_fields(command_is_validation, command=command, cwd=str(cwd),
                                    error="run_cli_command does not support shell control operators"),
    }


async def prepare_workspace_guard(
    plan: CliCommandPlan, context: ToolContext, *, command_writes_workspace: bool
) -> tuple[CliWorkspaceGuard, dict[str, Any] | None]:
    """Capture the workspace before the command; ``(guard, refusal)`` with a refusal for a failed bootstrap or a
    mutating command in a dirty workspace."""
    guard = CliWorkspaceGuard()
    if command_writes_workspace or plan.command_is_validation:
        guard.before_change_state = capture_workspace_change_state(plan.workspace_root)
    if not command_writes_workspace:
        return guard, None
    guard.bootstrap = bootstrap = await _ensure_repository_for_write(context)
    if bootstrap and bootstrap.get("status") == "error":
        return guard, {"error": "Repository bootstrap failed", "repository_bootstrap": bootstrap, "cwd": str(plan.cwd)}
    guard.before_change_state = capture_workspace_change_state(plan.workspace_root)
    if workspace_has_dirty_files(guard.before_change_state) and not bool(plan.params.get("allow_dirty_workspace")):
        return guard, {
            "error": (
                "Refusing to run a mutating command while the workspace already has "
                "uncommitted changes. If the dirty state is your own intended work for "
                "this change, retry with allow_dirty_workspace=true."
            ),
            "command": plan.command,
            "cwd": str(plan.cwd),
            "workspace_change_contract": build_workspace_change_contract(
                tool_name=plan.tool_name,
                before_state=guard.before_change_state,
            ),
            **({"repository_bootstrap": bootstrap} if bootstrap else {}),
        }
    guard.workspace_sync_policy = await resolve_workspace_sync_policy(context.db)
    guard.before_workspace_snapshot = capture_workspace_file_snapshot(
        plan.workspace_root, policy=guard.workspace_sync_policy
    )
    return guard, None


async def finish_workspace_guard(
    plan: CliCommandPlan, guard: CliWorkspaceGuard, context: ToolContext, exit_code: int | None
) -> tuple[Any, Any]:
    """``(workspace_sync, workspace_change_contract)`` after the command ran."""
    workspace_sync = None
    after_change_state = None
    if guard.before_workspace_snapshot is not None:
        workspace_sync = await sync_workspace_changes_since_snapshot(
            db=context.db,
            session_id=context.session_id,
            workspace_root=plan.workspace_root,
            before_snapshot=guard.before_workspace_snapshot,
            policy=guard.workspace_sync_policy,
        )
    if guard.before_change_state is not None:
        after_change_state = capture_workspace_change_state(plan.workspace_root)
    workspace_change_contract = (
        build_workspace_change_contract(
            tool_name=plan.tool_name,
            before_state=guard.before_change_state,
            after_state=after_change_state,
            override_dirty=bool(plan.params.get("allow_dirty_workspace")),
            validation_command=plan.argv if plan.command_is_validation else None,
            validation_exit_code=exit_code if plan.command_is_validation else None,
        )
        if guard.before_change_state is not None
        else None
    )
    return workspace_sync, workspace_change_contract


def redacted_outputs(runtime_result: Any) -> tuple[str, str]:
    # The output of the command the agent ran is its product result: kept, redacted, in one
    # place. Without an exit code (timeout, runtime unavailable) stderr carries runtime or
    # exception text, so nothing of it is kept.
    if runtime_result.exit_code is None:
        return "", ""
    return redact_process_output(runtime_result.stdout), redact_process_output(runtime_result.stderr)


def execution_records(
    plan: CliCommandPlan, runtime_result: Any, *, stdout_text: str, stderr_text: str, duration_ms: int
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """``(validation_outcome, execution_event)`` of a command that ran."""
    validation_outcome = (
        build_validation_outcome(
            command=plan.argv,
            cwd=str(plan.effective_cwd),
            exit_code=runtime_result.exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            timed_out=runtime_result.timed_out,
            execution_runtime=runtime_result.metadata,
        )
        if plan.command_is_validation
        else None
    )
    execution_event = build_execution_event(
        kind="validation" if plan.command_is_validation else "shell",
        tool_name=plan.tool_name,
        command=plan.argv,
        cwd=str(plan.effective_cwd),
        status=execution_status_from_exit_code(runtime_result.exit_code, timed_out=runtime_result.timed_out),
        exit_code=runtime_result.exit_code,
        duration_ms=duration_ms,
        stdout=runtime_result.stdout,
        stderr=runtime_result.stderr,
        metadata={
            **runtime_result.metadata,
            **({"validation_outcome": validation_outcome} if validation_outcome else {}),
        },
    )
    return validation_outcome, execution_event


def server_build_refusal(plan: CliCommandPlan, runtime_result: Any) -> dict[str, Any] | None:
    if (refusal := runtime_refusal(runtime_result, command=plan.command)) is not None:
        return refusal | {"cwd": str(plan.effective_cwd)}  # the server-build backstop: nothing ran
    return None


def _optional_fields(validation_outcome: Any, workspace_sync: Any, workspace_change_contract: Any) -> dict[str, Any]:
    return {
        **({"validation_outcome": validation_outcome} if validation_outcome else {}),
        **({"workspace_sync": workspace_sync} if workspace_sync else {}),
        **({"workspace_change_contract": workspace_change_contract} if workspace_change_contract else {}),
    }


def not_completed_result(
    plan: CliCommandPlan, runtime_result: Any, guard: CliWorkspaceGuard, *, execution_event: dict[str, Any],
    validation_outcome: Any, workspace_sync: Any, workspace_change_contract: Any,
) -> dict[str, Any] | None:
    """The fixed-facts result of a timed-out or not started command, or None when it completed."""
    if runtime_result.timed_out:
        error = f"cli_command_timed_out timeout_sec={plan.timeout_sec}"
        error_code = "cli_command_timed_out"
    elif runtime_result.exit_code is None:
        error = error_code = "cli_command_not_started"
    else:
        return None
    return {
        "error": error,
        "error_code": error_code,
        "command": plan.command,
        "effective_command": plan.effective_command,
        "cwd": str(plan.cwd),
        "execution_runtime": runtime_result.metadata,
        "execution_event": execution_event,
        **_optional_fields(validation_outcome, workspace_sync, workspace_change_contract),
        **({"repository_bootstrap": guard.bootstrap} if guard.bootstrap else {}),
    }


def completed_result(
    plan: CliCommandPlan, runtime_result: Any, guard: CliWorkspaceGuard, context: ToolContext, *,
    stdout_text: str, stderr_text: str, execution_event: dict[str, Any], validation_outcome: Any,
    workspace_sync: Any, workspace_change_contract: Any,
) -> dict[str, Any]:
    result = {
        "command": plan.command,
        "effective_command": plan.effective_command,
        "cwd": str(plan.effective_cwd),
        "os_name": (context.system_context or detect_system_context(context.workspace_root)).get("os_name"),
        "shell": (context.system_context or detect_system_context(context.workspace_root)).get("shell"),
        "exit_code": runtime_result.exit_code,
        "stdout": _truncate(stdout_text),
        "stderr": _truncate(stderr_text),
        "execution_runtime": runtime_result.metadata,
        "execution_event": execution_event,
        **({"validation_outcome": validation_outcome} if validation_outcome else {}),
        **({"script_resolution": plan.resolution} if plan.resolution else {}),
        **({"workspace_sync": workspace_sync} if workspace_sync else {}),
        **({"workspace_change_contract": workspace_change_contract} if workspace_change_contract else {}),
    }
    if guard.bootstrap:
        result["repository_bootstrap"] = guard.bootstrap
    return result
