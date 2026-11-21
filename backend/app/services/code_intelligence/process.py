"""Process execution and text index helpers for code intelligence."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from app.services.code_intelligence.storage_capabilities import _find_binary
from app.services.code_intelligence.storage_runtime import _zoekt_index_dir


async def _run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_sec: int = 180,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return {
            "command": command,
            "exit_code": 124,
            "stdout": "",
            "stderr": "",
            "timed_out": True,
        }
    return {
        "command": command,
        "exit_code": int(proc.returncode or 0),
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
    }


async def _maybe_build_zoekt_index(*, repository_id: str, repo_root: Path) -> dict[str, Any]:
    zoekt_git_index = _find_binary("zoekt-git-index")
    zoekt_index = _find_binary("zoekt-index")
    if not zoekt_git_index and not zoekt_index:
        return {"status": "skipped", "reason": "zoekt_not_installed"}

    index_dir = _zoekt_index_dir(repository_id)
    if repo_root.joinpath(".git").exists() and zoekt_git_index:
        command = [zoekt_git_index, "-index", str(index_dir), str(repo_root)]
    elif zoekt_index:
        command = [zoekt_index, "-index", str(index_dir), str(repo_root)]
    else:
        return {"status": "skipped", "reason": "zoekt_indexer_missing"}

    result = await _run_command(command, cwd=repo_root, timeout_sec=300)
    artifacts = sorted(str(path.relative_to(index_dir)) for path in index_dir.glob("**/*") if path.is_file())
    # Indexer output is diagnostics only; a failure keeps the closed code and the exit status.
    failed = result["exit_code"] != 0
    return {
        "status": "error" if failed else "ready",
        "index_dir": str(index_dir),
        "artifacts": artifacts[:50],
        "command": result["command"],
        "exit_code": result["exit_code"],
        "error_code": "zoekt_index_failed" if failed else None,
    }
