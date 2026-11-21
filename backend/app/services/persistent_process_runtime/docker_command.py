"""Docker command line for a persistent process in the container runtime."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from ..execution_runtime import (
    ExecutionRuntimeConfig,
    ExecutionRuntimeMount,
    ExecutionRuntimeUnavailableError,
)


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


def _container_workdir(*, workspace_root: Path, cwd: Path) -> str:
    workspace_root = workspace_root.resolve()
    cwd = cwd.resolve()
    if cwd != workspace_root and workspace_root not in cwd.parents:
        raise ValueError(f"cwd must stay inside workspace root for container runtime: {workspace_root}")
    relative = cwd.relative_to(workspace_root)
    return "/workspace" if str(relative) in {"", "."} else f"/workspace/{relative.as_posix()}"


def _build_docker_command(
    *,
    config: ExecutionRuntimeConfig,
    command: list[str],
    cwd: Path,
    workspace_root: Path,
    env: Mapping[str, str] | None = None,
    mounts: list[ExecutionRuntimeMount] | None = None,
    allocate_tty: bool,
) -> list[str]:
    docker_binary = shutil.which("docker")
    if not docker_binary:
        raise ExecutionRuntimeUnavailableError("Docker execution runtime is configured but docker is not installed.")

    docker_command = [
        docker_binary,
        "run",
        "--rm",
        "--init",
        "-i",
        "--network",
        config.docker_network_mode,
        "-v",
        f"{workspace_root.resolve()}:/workspace",
        "-w",
        _container_workdir(workspace_root=workspace_root, cwd=cwd),
    ]
    if config.sandbox_mode == "hard":
        docker_command.extend(
            [
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
        )
    if allocate_tty:
        docker_command.append("-t")
    for key, value in (env or {}).items():
        docker_command.extend(["-e", f"{key}={value}"])
    for mount in _dedupe_mounts(mounts or []):
        mode = "ro" if mount.read_only else "rw"
        docker_command.extend(
            [
                "-v",
                f"{mount.host_path.resolve()}:{str(PurePosixPath(mount.container_path))}:{mode}",
            ]
        )
    docker_command.append(config.docker_image)
    docker_command.extend(str(part) for part in command)
    return docker_command
