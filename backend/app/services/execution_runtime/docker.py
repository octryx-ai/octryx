"""Containerized command execution through ``docker run``."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from app.exceptions.base import ExecutionRuntimeUnavailableError

from .config import ExecutionRuntimeConfig
from .contracts import ExecutionRuntimeMount, ExecutionRuntimeResult
from .process_tree import communicate_within_deadline, process_group_spawn_kwargs

# How long ``docker kill`` of a timed-out or cancelled run's container may take.
_CONTAINER_KILL_TIMEOUT_SEC = 15.0


def _container_workdir(*, workspace_root: Path, cwd: Path) -> str:
    workspace_root = workspace_root.resolve()
    cwd = cwd.resolve()
    if cwd != workspace_root and workspace_root not in cwd.parents:
        raise ValueError(f"cwd must stay inside workspace root for container runtime: {workspace_root}")
    relative = cwd.relative_to(workspace_root)
    return "/workspace" if str(relative) in {"", "."} else f"/workspace/{relative.as_posix()}"


def _dedupe_mounts(mounts: list[ExecutionRuntimeMount]) -> list[ExecutionRuntimeMount]:
    deduped: list[ExecutionRuntimeMount] = []
    seen: set[tuple[str, str]] = set()
    for mount in mounts:
        key = (str(mount.host_path.resolve()), mount.container_path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(mount)
    return deduped


async def _kill_named_container(
    docker_binary: str,
    container_name: str,
    subprocess_exec_factory: Callable[..., Awaitable[Any]],
) -> None:
    try:
        killer = await subprocess_exec_factory(
            docker_binary,
            "kill",
            container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(killer.wait(), timeout=_CONTAINER_KILL_TIMEOUT_SEC)
    except (OSError, TimeoutError):
        # The container already exited, or the daemon does not answer: the run stays timed out.
        pass


def _docker_command(
    *,
    docker_binary: str,
    command: list[str] | str,
    workspace_root: Path,
    workdir: str,
    container_name: str,
    shell: bool,
    env: Mapping[str, str] | None,
    config: ExecutionRuntimeConfig,
    mounts: list[ExecutionRuntimeMount] | None,
) -> list[str]:
    docker_command = [
        docker_binary,
        "run",
        "--rm",
        "--init",
        "--network",
        config.docker_network_mode,
        "-v",
        f"{workspace_root.resolve()}:/workspace",
        "-w",
        workdir,
        # Named, so a timed-out or cancelled run can kill its container: killing the
        # ``docker run`` client alone leaves the container running.
        "--name",
        container_name,
    ]
    if config.sandbox_mode == "hard":
        docker_command.extend(_hard_sandbox_flags(config))
    for key, value in (env or {}).items():
        docker_command.extend(["-e", f"{key}={value}"])
    for mount in _dedupe_mounts(mounts or []):
        mode = "ro" if mount.read_only else "rw"
        docker_command.extend(
            [
                "-v",
                f"{mount.host_path.resolve()}:{mount.container_path}:{mode}",
            ]
        )
    docker_command.append(config.docker_image)
    if shell:
        docker_command.extend(["/bin/sh", "-lc", str(command)])
    else:
        docker_command.extend(str(arg) for arg in (command if isinstance(command, list) else [command]))
    return docker_command


def _hard_sandbox_flags(config: ExecutionRuntimeConfig) -> list[str]:
    return [
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--tmpfs",
        "/run:rw,noexec,nosuid,size=16m",
        "--memory",
        f"{config.docker_memory_mb}m",
        "--pids-limit",
        str(config.docker_pids_limit),
    ]


def _docker_metadata(config: ExecutionRuntimeConfig) -> dict[str, Any]:
    return {
        "provider": "docker",
        "containerized": True,
        "docker_image": config.docker_image,
        "docker_network_mode": config.docker_network_mode,
        "sandbox_mode": config.sandbox_mode,
        "docker_memory_mb": config.docker_memory_mb,
        "docker_pids_limit": config.docker_pids_limit,
    }


async def _run_docker_command_impl(
    *,
    command: list[str] | str,
    cwd: Path,
    workspace_root: Path,
    timeout_sec: int,
    shell: bool,
    env: Mapping[str, str] | None = None,
    config: ExecutionRuntimeConfig,
    mounts: list[ExecutionRuntimeMount] | None = None,
    docker_which: Callable[[str], str | None] | None = None,
    subprocess_exec_factory: Callable[..., Awaitable[Any]] | None = None,
) -> ExecutionRuntimeResult:
    # Resolve at call time so monkeypatched module attributes take effect.
    docker_which = docker_which or shutil.which
    subprocess_exec_factory = subprocess_exec_factory or asyncio.create_subprocess_exec
    docker_binary = docker_which("docker")
    if not docker_binary:
        raise ExecutionRuntimeUnavailableError("Docker execution runtime is configured but docker is not installed.")

    workdir = _container_workdir(workspace_root=workspace_root, cwd=cwd)
    container_name = f"octryx-exec-{uuid.uuid4().hex[:16]}"
    docker_command = _docker_command(
        docker_binary=docker_binary, command=command, workspace_root=workspace_root, workdir=workdir,
        container_name=container_name, shell=shell, env=env, config=config, mounts=mounts,
    )

    process = await subprocess_exec_factory(
        *docker_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **process_group_spawn_kwargs(),
    )

    async def _kill_container() -> None:
        await _kill_named_container(docker_binary, container_name, subprocess_exec_factory)

    output = await communicate_within_deadline(process, timeout_sec=timeout_sec, on_kill=_kill_container)
    if output.timed_out:
        return ExecutionRuntimeResult(
            exit_code=None,
            stdout="",
            stderr=f"Command timed out after {timeout_sec}s",
            timed_out=True,
            metadata=_docker_metadata(config),
        )
    return ExecutionRuntimeResult(
        exit_code=process.returncode,
        stdout=output.stdout.decode("utf-8", errors="replace"),
        stderr=output.stderr.decode("utf-8", errors="replace"),
        timed_out=False,
        metadata=_docker_metadata(config),
    )
