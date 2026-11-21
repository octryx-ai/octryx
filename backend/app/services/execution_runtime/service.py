"""Pluggable execution runtime for host and containerized command execution.

This module owns the dispatch (``execute_with_runtime``: provider choice, host fallback, output
redaction at the result boundary). Configuration lives in ``config``, value types in ``contracts``,
and the two runners in ``host`` and ``docker``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.base import ExecutionRuntimeUnavailableError as _BaseRuntimeError

from ..error_facts import error_text
from ..process_output_redaction import redact_process_output
from . import command_audit as _audit
from . import foreign_build_guard as _guard
from . import server_env as _server_env
from .config import ExecutionRuntimeConfig, resolve_execution_runtime_config
from .contracts import ExecutionRuntimeMount, ExecutionRuntimeResult
from .docker import _run_docker_command_impl
from .host import _run_host_command_impl

ExecutionRuntimeUnavailableError = _BaseRuntimeError

RUNTIME_UNAVAILABLE_CODE = "execution_runtime_unavailable"


def _redacted_result(result: ExecutionRuntimeResult, metadata: dict[str, Any]) -> ExecutionRuntimeResult:
    """Command output is a product result: kept at this one boundary, but only redacted."""
    return ExecutionRuntimeResult(
        exit_code=result.exit_code,
        stdout=redact_process_output(result.stdout),
        stderr=redact_process_output(result.stderr),
        timed_out=result.timed_out,
        metadata=metadata,
    )


async def execute_with_runtime(
    *,
    db: AsyncSession | None,
    project_config: Mapping[str, Any] | None,
    command: list[str] | str,
    cwd: Path,
    workspace_root: Path,
    timeout_sec: int,
    shell: bool = False,
    env: Mapping[str, str] | None = None,
    mounts: list[ExecutionRuntimeMount] | None = None,
    resolve_config_fn: Callable[..., Awaitable[ExecutionRuntimeConfig]] | None = None,
    host_command_fn: Callable[..., Awaitable[ExecutionRuntimeResult]] | None = None,
    docker_command_fn: Callable[..., Awaitable[ExecutionRuntimeResult]] | None = None,
    guard_foreign_build: bool = True,
) -> ExecutionRuntimeResult:
    """Run ``command`` on the platform's runtime (host or docker); the output comes back redacted.

    ``guard_foreign_build``: the server never runs repository build/test tooling (``foreign_build_guard``).
    A refused command does not start (``exit_code`` ``None``, the plain message in ``stderr``,
    ``metadata.refused`` = ``server_build_not_allowed`` with the verdict). Only a caller that runs a fixed,
    platform-chosen binary that is not repository content (kubectl, a connector probe, a saved script in the forced
    docker sandbox, the platform's own git of a snapshot, worktree or git-intelligence read) passes ``False``; every
    other caller is held, whatever its own checks were. A held command is audited (``command_audit``, fail-closed)
    and runs with the allowlisted environment (``server_env``); every command gets the neutralised git
    configuration."""
    audit = None
    host_kwargs: dict[str, Any] = {}
    if guard_foreign_build:
        refusal = await _foreign_build_refusal(command, cwd, shell)
        if refusal is not None:
            return refusal
        try:
            audit = await _audit.record(command, verdict="executed", where="execute_with_runtime")
        except _audit.CommandAuditUnavailableError:
            return ExecutionRuntimeResult(
                exit_code=None, stdout="", stderr="The command was not run: its audit record could not be written.",
                timed_out=False, metadata={"refused": _audit.AUDIT_UNAVAILABLE, "cwd": str(cwd), "shell_mode": shell})
        # No secret of this process reaches the command; git in it runs nothing of the working copy.
        env = _server_env.with_git_hardening(_server_env.explicit_env(env))
        host_kwargs = {"process_env": _server_env.inherited_env()}
    else:
        env = _server_env.with_git_hardening(env)  # the platform's own git runs nothing of a working copy either
    result = await _execute_dispatched(
        db=db, project_config=project_config, command=command, cwd=cwd, workspace_root=workspace_root,
        timeout_sec=timeout_sec, shell=shell, env=env, mounts=mounts, resolve_config_fn=resolve_config_fn,
        host_command_fn=host_command_fn, docker_command_fn=docker_command_fn, host_kwargs=host_kwargs)
    await _audit.record_exit(audit, result.exit_code, timed_out=result.timed_out)
    return result


async def _foreign_build_refusal(command: list[str] | str, cwd: Path, shell: bool) -> ExecutionRuntimeResult | None:
    """The audited refusal of a repository build/test command, or ``None`` when the command may run."""
    verdict = _guard.classify_command(command)  # resolved at call time
    if not verdict.blocked:
        verdict = _guard.cwd_verdict(cwd) or verdict
    if not verdict.blocked:
        return None
    shown = command if isinstance(command, str) else " ".join(str(word) for word in command)
    _guard.logger.warning(
        "foreign_build_guard refused a runtime command: class=%s program=%s cwd=%s command=%r",
        verdict.command_class, verdict.program, str(cwd), shown[:300])
    try:
        await _audit.record(command, verdict="refused", where="execute_with_runtime",
                            reason=_guard.SERVER_BUILD_NOT_ALLOWED)
    except _audit.CommandAuditUnavailableError:
        pass  # refused either way
    return ExecutionRuntimeResult(
        exit_code=None, stdout="", stderr=_guard.SERVER_BUILD_MESSAGE, timed_out=False,
        metadata={"refused": _guard.SERVER_BUILD_NOT_ALLOWED, "foreign_build_guard": verdict.to_dict(),
                  "cwd": str(cwd), "shell_mode": shell},
    )


def _base_metadata(config: ExecutionRuntimeConfig, *, cwd: Path, workspace_root: Path, shell: bool) -> dict[str, Any]:
    return {
        "requested_provider": config.provider,
        "docker_image": config.docker_image if config.provider == "docker" else "",
        "docker_network_mode": config.docker_network_mode if config.provider == "docker" else "",
        "host_fallback": False,
        "fallback_reason": "",
        "containerized": config.provider == "docker",
        "sandbox_mode": config.sandbox_mode,
        "docker_memory_mb": config.docker_memory_mb if config.provider == "docker" else 0,
        "docker_pids_limit": config.docker_pids_limit if config.provider == "docker" else 0,
        "cwd": str(cwd.resolve()),
        "workspace_root": str(workspace_root.resolve()),
        "shell_mode": shell,
    }


async def _execute_dispatched(
    *,
    db: AsyncSession | None,
    project_config: Mapping[str, Any] | None,
    command: list[str] | str,
    cwd: Path,
    workspace_root: Path,
    timeout_sec: int,
    shell: bool,
    env: Mapping[str, str] | None,
    mounts: list[ExecutionRuntimeMount] | None,
    resolve_config_fn: Callable[..., Awaitable[ExecutionRuntimeConfig]] | None,
    host_command_fn: Callable[..., Awaitable[ExecutionRuntimeResult]] | None,
    docker_command_fn: Callable[..., Awaitable[ExecutionRuntimeResult]] | None,
    host_kwargs: dict[str, Any],
) -> ExecutionRuntimeResult:
    resolve_config = resolve_config_fn or resolve_execution_runtime_config
    run_host_command = host_command_fn or _run_host_command_impl
    run_docker_command = docker_command_fn or _run_docker_command_impl

    config = await resolve_config(db, project_config=project_config)
    base_metadata = _base_metadata(config, cwd=cwd, workspace_root=workspace_root, shell=shell)
    host_call: dict[str, Any] = {
        "command": command, "cwd": cwd, "timeout_sec": timeout_sec, "shell": shell, "env": env, **host_kwargs,
    }

    try:
        if config.provider == "docker":
            result = await run_docker_command(
                command=command,
                cwd=cwd,
                workspace_root=workspace_root,
                timeout_sec=timeout_sec,
                shell=shell,
                env=env,
                config=config,
                mounts=mounts,
            )
        else:
            result = await run_host_command(**host_call)
    except ExecutionRuntimeUnavailableError as exc:
        return await _host_fallback(exc, config, base_metadata, run_host_command, host_call)

    return _redacted_result(result, {**base_metadata, **result.metadata})


async def _host_fallback(
    exc: ExecutionRuntimeUnavailableError,
    config: ExecutionRuntimeConfig,
    base_metadata: dict[str, Any],
    run_host_command: Callable[..., Awaitable[ExecutionRuntimeResult]],
    host_call: dict[str, Any],
) -> ExecutionRuntimeResult:
    """The configured runtime is unavailable: run on the host when allowed, otherwise report it."""
    if not config.allow_host_fallback:
        return ExecutionRuntimeResult(
            exit_code=None,
            stdout="",
            stderr=error_text(RUNTIME_UNAVAILABLE_CODE, exc),
            timed_out=False,
            metadata={
                **base_metadata,
                "provider": config.provider,
                "containerized": config.provider == "docker",
            },
        )
    result = await run_host_command(**host_call)
    return _redacted_result(
        result,
        {
            **base_metadata,
            **result.metadata,
            "host_fallback": True,
            "fallback_reason": RUNTIME_UNAVAILABLE_CODE,
            "containerized": False,
        },
    )


__all__ = [
    "ExecutionRuntimeUnavailableError",
    "execute_with_runtime",
]
