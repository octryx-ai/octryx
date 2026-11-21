"""Persistent process runtime for long-lived stdio and PTY workloads."""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..execution_runtime import (
    DEFAULT_EXECUTION_RUNTIME_PROVIDER,
    ExecutionRuntimeConfig,
    ExecutionRuntimeMount,
    ExecutionRuntimeUnavailableError,
    resolve_execution_runtime_config,
)
from ..execution_runtime.process_tree import process_group_spawn_kwargs
from ..execution_runtime.service import RUNTIME_UNAVAILABLE_CODE
from .docker_command import _build_docker_command

_async_session_factory: Callable[[], Awaitable[Any]] | None = None


def configure_persistent_process_runtime(
    session_factory: Callable[[], Awaitable[Any]] | None,
) -> None:
    global _async_session_factory
    _async_session_factory = session_factory


@dataclass(frozen=True)
class PersistentProcessHandle:
    process: Any
    metadata: dict[str, Any]
    runtime_kind: str


def _runtime_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    merged = dict(os.environ)
    if env:
        merged.update({str(key): str(value) for key, value in env.items()})
    return merged


async def _load_runtime_config(
    db: AsyncSession | None,
    *,
    project_config: Mapping[str, Any] | None = None,
) -> ExecutionRuntimeConfig:
    if db is not None:
        return await resolve_execution_runtime_config(db, project_config=project_config)
    if _async_session_factory is not None:
        async with _async_session_factory() as runtime_db:
            return await resolve_execution_runtime_config(runtime_db, project_config=project_config)
    return await resolve_execution_runtime_config(None, project_config=project_config)


def _base_metadata(
    config: ExecutionRuntimeConfig,
    *,
    runtime_kind: str,
    cwd: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    return {
        "requested_provider": config.provider,
        "provider": config.provider,
        "runtime_kind": runtime_kind,
        "containerized": config.provider == "docker",
        "host_fallback": False,
        "fallback_reason": "",
        "cwd": str(cwd.resolve()),
        "workspace_root": str(workspace_root.resolve()),
        "docker_image": config.docker_image if config.provider == "docker" else "",
        "docker_network_mode": config.docker_network_mode if config.provider == "docker" else "",
        "sandbox_mode": config.sandbox_mode,
        "docker_memory_mb": config.docker_memory_mb if config.provider == "docker" else 0,
        "docker_pids_limit": config.docker_pids_limit if config.provider == "docker" else 0,
    }


def _host_metadata(base_metadata: dict[str, Any], *, fallback: bool) -> dict[str, Any]:
    """Metadata of a process started on the host: directly, or as the fallback when the container runtime is
    unavailable."""
    metadata = {
        **base_metadata,
        "provider": DEFAULT_EXECUTION_RUNTIME_PROVIDER,
        "containerized": False,
    }
    if fallback:
        metadata["host_fallback"] = True
        metadata["fallback_reason"] = RUNTIME_UNAVAILABLE_CODE
    return metadata


def _restricted_envs(env: Mapping[str, str] | None) -> tuple[dict[str, str], dict[str, str]]:
    """The host environment (allowlist only) and the explicit environment with git hardened."""
    from ..execution_runtime.server_env import explicit_env, server_command_env, with_git_hardening

    host_env = server_command_env(env)
    return host_env, with_git_hardening(explicit_env(env))


async def _spawn_stdio_host(
    command: list[str],
    *,
    cwd: Path,
    stderr_target: int,
    env: Mapping[str, str] | None,
    host_env: dict[str, str] | None,
    new_process_group: bool,
) -> Any:
    return await asyncio.create_subprocess_exec(
        *[str(part) for part in command],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=stderr_target,
        cwd=str(cwd),
        env=host_env if host_env is not None else _runtime_env(env),
        **(process_group_spawn_kwargs() if new_process_group else {}),
    )


async def spawn_persistent_stdio_process(
    *,
    db: AsyncSession | None,
    project_config: Mapping[str, Any] | None,
    command: list[str],
    cwd: Path,
    workspace_root: Path,
    env: Mapping[str, str] | None = None,
    mounts: list[ExecutionRuntimeMount] | None = None,
    stderr_mode: str = "pipe",
    new_process_group: bool = False,
    restricted_env: bool = False,
) -> PersistentProcessHandle:
    """``new_process_group`` starts a host child as a group leader, so a deadline kills its whole tree.

    ``restricted_env``: an agent's command (``start_runtime_process``) inherits no secret of this process, only the
    allowlist plus what the caller sets, and git in it runs nothing of the working copy (``server_env``)."""
    if restricted_env:
        host_env, env = _restricted_envs(env)
    else:
        host_env = None
    config = await _load_runtime_config(db, project_config=project_config)
    base_metadata = {
        **_base_metadata(config, runtime_kind="stdio", cwd=cwd, workspace_root=workspace_root),
        "command": [str(part) for part in command],
    }
    stderr_target = asyncio.subprocess.DEVNULL if stderr_mode == "devnull" else asyncio.subprocess.PIPE
    host_spawn = {
        "cwd": cwd,
        "stderr_target": stderr_target,
        "env": env,
        "host_env": host_env,
        "new_process_group": new_process_group,
    }

    try:
        if config.provider == "docker":
            docker_command = _build_docker_command(
                config=config, command=command, cwd=cwd, workspace_root=workspace_root, env=env, mounts=mounts,
                allocate_tty=False,
            )
            process = await asyncio.create_subprocess_exec(
                *docker_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr_target,
            )
            return PersistentProcessHandle(process=process, metadata=base_metadata, runtime_kind="stdio")
        process = await _spawn_stdio_host(command, **host_spawn)
        return PersistentProcessHandle(
            process=process, metadata=_host_metadata(base_metadata, fallback=False), runtime_kind="stdio"
        )
    except ExecutionRuntimeUnavailableError:
        if not config.allow_host_fallback:
            raise
        process = await _spawn_stdio_host(command, **host_spawn)
        return PersistentProcessHandle(
            process=process, metadata=_host_metadata(base_metadata, fallback=True), runtime_kind="stdio"
        )


def _spawn_pty_host(
    argv: list[str],
    *,
    slave_fd: int,
    spawn_env: dict[str, str],
    cwd: Path,
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        argv,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        preexec_fn=os.setsid,
        env=spawn_env,
        cwd=str(cwd) if cwd.is_dir() else None,
    )


async def spawn_persistent_pty_process(
    *,
    db: AsyncSession | None,
    project_config: Mapping[str, Any] | None,
    shell_command: str,
    cwd: Path,
    workspace_root: Path,
    master_fd: int,
    slave_fd: int,
    env: Mapping[str, str] | None = None,
    mounts: list[ExecutionRuntimeMount] | None = None,
) -> PersistentProcessHandle:
    config = await _load_runtime_config(db, project_config=project_config)
    base_metadata = {
        **_base_metadata(config, runtime_kind="pty", cwd=cwd, workspace_root=workspace_root),
        "shell_command": shell_command,
        "session_label": str(uuid.uuid4()),
    }
    host_spawn = {"slave_fd": slave_fd, "spawn_env": _runtime_env(env), "cwd": cwd}

    try:
        if config.provider == "docker":
            docker_command = _build_docker_command(
                config=config,
                command=["/bin/sh", "-lc", shell_command],
                cwd=cwd,
                workspace_root=workspace_root,
                env=env,
                mounts=mounts,
                allocate_tty=True,
            )
            process = _spawn_pty_host(docker_command, **host_spawn)
            return PersistentProcessHandle(process=process, metadata=base_metadata, runtime_kind="pty")
        process = _spawn_pty_host([shell_command], **host_spawn)
        return PersistentProcessHandle(
            process=process, metadata=_host_metadata(base_metadata, fallback=False), runtime_kind="pty"
        )
    except ExecutionRuntimeUnavailableError:
        if not config.allow_host_fallback:
            raise
        process = _spawn_pty_host([shell_command], **host_spawn)
        return PersistentProcessHandle(
            process=process, metadata=_host_metadata(base_metadata, fallback=True), runtime_kind="pty"
        )
