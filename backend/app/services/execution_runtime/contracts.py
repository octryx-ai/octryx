"""Execution runtime value types: mounts and command results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class ExecutionRuntimeMount:
    host_path: Path
    container_path: str
    read_only: bool = True


@dataclass(frozen=True)
class ExecutionRuntimeResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    metadata: dict[str, Any]


def workspace_mount_for_path(
    *,
    host_path: Path,
    container_path: str,
    read_only: bool = True,
) -> ExecutionRuntimeMount:
    return ExecutionRuntimeMount(
        host_path=host_path.resolve(),
        container_path=str(PurePosixPath(container_path)),
        read_only=read_only,
    )
