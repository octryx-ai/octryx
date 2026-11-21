from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


async def binary_is_available_for_runtime(
    config: dict[str, Any],
    binary: str,
    *,
    resolve_runtime_config_fn: Callable[..., Awaitable[Any]],
    which_fn: Callable[[str], str | None],
) -> bool:
    runtime_config = await resolve_runtime_config_fn(None, project_config=config)
    if runtime_config.provider == "docker":
        return True
    return which_fn(binary) is not None or Path(binary).exists()


async def run_runtime_probe(
    *,
    config: dict[str, Any],
    command: list[str],
    cwd: Path,
    execute_with_runtime_fn: Callable[..., Awaitable[Any]],
    env: dict[str, str] | None = None,
    timeout_sec: int = 30,
) -> tuple[int, str, str, dict[str, Any]]:
    result = await execute_with_runtime_fn(
        db=None,
        project_config=config,
        command=command,
        cwd=cwd,
        workspace_root=cwd,
        timeout_sec=timeout_sec,
        env=env,
        guard_foreign_build=False,  # a fixed connector probe of a configured binary, not repository content
    )
    if result.timed_out:
        return 124, "", result.stderr or f"command timed out after {timeout_sec}s", result.metadata
    return (
        result.exit_code if result.exit_code is not None else 125,
        result.stdout,
        result.stderr,
        result.metadata,
    )
