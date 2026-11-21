"""Running one of the launcher's pinned tools on code a job fetched (the check proof and the review bot's
scan): no shell, only a tool from ``tools_data`` this device has in its pinned version, in a folder inside the
system's temporary directory, with a minimal environment (PATH, HOME = that folder, LANG): a tool that reads a
stranger's code never sees the launcher's device token, seat or proxy keys. A missing tool or a timeout is a status,
never an exception; output and the files the call writes are capped (``max_output``).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import tools
from .tools_data import TOOLS

MAX_OUTPUT = 200_000


def _executable(tool_id: str) -> str | None:
    tool = next((item for item in TOOLS if item["id"] == tool_id), None)
    root = tools.default_root()
    if tool is None or not tool.get("bin") or tools._version_of(tool, root) is None:
        return None
    return tools._executable(tool, root)


def _capped(data: bytes, limit: int) -> tuple[str, bool]:
    return data[:limit].decode("utf-8", "replace"), len(data) > limit


def run_tool(tool_id: str, args: list[str], *, cwd: Path, timeout: float, max_output: int = MAX_OUTPUT,
             outputs: list[str] | None = None) -> dict[str, Any]:
    """``{status: ok | missing | timeout | error, exit, stdout, stderr, truncated, files}``; ``files`` holds each of
    ``outputs`` (paths relative to ``cwd``) the call wrote, as text within ``max_output`` or ``truncated``."""
    cwd = Path(cwd).resolve()
    if not cwd.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not cwd.is_dir():
        return {"status": "error", "exit": None, "stdout": "", "stderr": "cwd is not a temporary folder",
                "truncated": False, "files": {}}
    executable = _executable(tool_id)
    if executable is None:
        return {"status": "missing", "exit": None, "stdout": "", "stderr": f"{tool_id} is not available here",
                "truncated": False, "files": {}}
    env = {"PATH": os.pathsep.join([*tools.bin_dirs(tools.default_root()), "/usr/bin", "/bin"]),
           "HOME": str(cwd), "LANG": "C.UTF-8"}
    try:
        done = subprocess.run([executable, *[str(item) for item in args]], cwd=cwd, env=env, capture_output=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "exit": None, "stdout": "", "stderr": f"{tool_id} ran past {timeout:.0f} s",
                "truncated": False, "files": {}}
    except OSError as error:
        return {"status": "error", "exit": None, "stdout": "", "stderr": str(error)[:500], "truncated": False,
                "files": {}}
    stdout, cut_out = _capped(done.stdout, max_output)
    stderr, cut_err = _capped(done.stderr, max_output)
    files: dict[str, str] = {}
    cut_files = False
    for name in outputs or []:
        path = (cwd / name).resolve()
        if path.is_relative_to(cwd) and path.is_file():
            files[name], cut = _capped(path.read_bytes(), max_output)
            cut_files = cut_files or cut
    return {"status": "ok", "exit": done.returncode, "stdout": stdout, "stderr": stderr,
            "truncated": cut_out or cut_err or cut_files, "files": files}


__all__ = ["MAX_OUTPUT", "run_tool"]
