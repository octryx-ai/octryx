"""Files a phone turn made on this Mac, fetched by the person on demand (Octryx Mobile).

Artifacts a session creates must be retrievable from the app: a turn that writes a report,
a picture or code leaves it on the Mac; the person opens it from the app.

- **only a project folder** (the rule of ``project_folder``): a job whose folder is a home
  folder, a disk, temp or a system folder (a take-over session started in ``~``) lists and serves nothing. Inside,
  dot files and folders and ``Library`` are never entered or served at any depth, nor octryx's own state or a
  Claude Code config folder.
- **after each turn** :func:`changed_files` lists the files in the turn's folder changed since the turn started
  (newest first, at most :data:`MAX_LISTED`). Left out: secrets (``device_sdk.secret_path``), ``.git``, dependency
  and cache folders, files over :data:`MAX_FILE_BYTES`, links. The list goes to the chat as a ``files`` job event;
  no content leaves the Mac.
- **on request** (``file_request {request_id, job_id, path}`` on the channel) :meth:`FileServer.serve` sends one
  file in chunks (``file_chunk``), or ``file_failed {reason}``. The Mac answers only for a job it ran (its own
  record, :func:`remember_turn`), only inside that job's folder (no ``..``, no link out of it), only a regular file
  that is no secret and not larger than :data:`MAX_FILE_BYTES`.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .device_sdk_events import secret_path
from .state import LocalState, read_json, write_private_json

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_LISTED = 50
MAX_VISITED = 5000
MAX_REMEMBERED = 200
CHUNK_BYTES = 192 * 1024
JOBS_FILE = "device-job-folders.json"
SKIPPED_DIRS = frozenset({".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
                          ".pytest_cache", ".ruff_cache", ".tox", ".idea", ".gradle", ".next", ".cache", ".terraform"})
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_NOT_PROJECT_ROOTS = frozenset({"/", "/Users", "/home", "/Volumes", "/tmp", "/private", "/private/tmp", "/private/var",
                                "/var", "/etc", "/opt", "/usr", "/Library", "/System", "/Applications"})
_SYSTEM_TOP_LEVEL = frozenset({"etc", "opt", "usr", "bin", "sbin", "Library", "System", "Applications", "private",
                               "var", "tmp", "dev", "cores", "Network"})


def shared_folder(folder: str, *, home: Path | None = None, state_root: Path | None = None) -> Path | None:
    """The job folder when files may be shared from it: a project folder, never the home folder, a disk, temp, a
    system folder, ``~/Library``, a dot folder, octryx's state or a Claude Code config folder."""
    if not folder or not folder.startswith("/"):
        return None
    try:
        path = Path(folder).resolve()
    except (OSError, RuntimeError):
        return None
    home = (home or Path.home()).resolve()
    text, parts = path.as_posix(), path.parts[1:]
    if text in _NOT_PROJECT_ROOTS or path == home or len(parts) < 2 or parts[0] in _SYSTEM_TOP_LEVEL:
        return None
    if parts[0] in {"Users", "home", "Volumes"} and len(parts) < 3:
        return None
    if any(part.startswith(".") or part == "Library" for part in parts):
        return None
    for protected in [state_root, *(home.glob(".claude*"))]:
        if protected is None:
            continue
        protected = protected.resolve()
        if path == protected or protected in path.parents or path in protected.parents:
            return None  # inside octryx's state or a Claude config folder, or a folder that contains one
    return path


def _hidden(part: str) -> bool:
    return part.startswith(".") or part == "Library" or part in SKIPPED_DIRS


def changed_files(folder: str, since: float, *, limit: int = MAX_LISTED, home: Path | None = None,
                  state_root: Path | None = None) -> list[dict[str, Any]]:
    """Files under ``folder`` changed at or after ``since``; nothing for a folder that is not shared; never raises."""
    root = shared_folder(folder, home=home, state_root=state_root)
    if root is None:
        return []
    found: list[dict[str, Any]] = []
    visited = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not _hidden(d))
        for name in sorted(files):
            if _hidden(name):
                continue
            visited += 1
            if visited > MAX_VISITED:
                break
            path = Path(current) / name
            try:
                info = path.lstat()
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            if (not path.is_file() or path.is_symlink() or info.st_mtime < since or info.st_size > MAX_FILE_BYTES
                    or secret_path("/" + rel)):
                continue
            found.append({"path": rel, "size": int(info.st_size), "mtime": int(info.st_mtime)})
        if visited > MAX_VISITED:
            break
    found.sort(key=lambda item: item["mtime"], reverse=True)
    return found[:limit]


def remember_turn(state: LocalState, job_id: str, folder: str, since: float) -> None:
    """The Mac's own record of which folder a job ran in: file requests are answered only from it."""
    path = state.root / JOBS_FILE
    jobs = read_json(path) if path.exists() else {}
    jobs = jobs if isinstance(jobs, dict) else {}
    previous = jobs.get(job_id) if isinstance(jobs.get(job_id), dict) else {}
    jobs.pop(job_id, None)
    jobs[job_id] = {"folder": folder, "since": min(float(previous.get("since") or since), since), "at": time.time()}
    while len(jobs) > MAX_REMEMBERED:
        jobs.pop(next(iter(jobs)))
    write_private_json(path, jobs)


def _job_folder(state: LocalState, job_id: str) -> str:
    path = state.root / JOBS_FILE
    jobs = read_json(path) if path.exists() else {}
    entry = jobs.get(job_id) if isinstance(jobs, dict) else None
    return str(entry.get("folder") or "") if isinstance(entry, dict) else ""


def resolve(state: LocalState, job_id: str, rel: str, *, home: Path | None = None) -> tuple[Path | None, str]:
    """``(file, "")`` when the Mac may hand it out, else ``(None, reason)``."""
    folder = _job_folder(state, job_id)
    if not folder:
        return None, "unknown_job"
    if not rel or rel.startswith("/") or "\x00" in rel or any(part == ".." for part in rel.split("/")):
        return None, "invalid_path"
    root = shared_folder(folder, home=home, state_root=state.root)
    if root is None:
        return None, "folder_not_shared"
    candidate = root / rel
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, "not_found"
    if root not in resolved.parents or candidate.is_symlink():
        return None, "outside_folder"
    if any(_hidden(part) for part in resolved.relative_to(root).parts):
        return None, "not_shared"
    if secret_path("/" + resolved.relative_to(root).as_posix()):
        return None, "secret_file"
    if not resolved.is_file():
        return None, "not_found"
    if resolved.stat().st_size > MAX_FILE_BYTES:
        return None, "too_large"
    return resolved, ""


class FileServer:
    def __init__(self, state: LocalState, send: Callable[[str, dict[str, Any]], Awaitable[bool]]) -> None:
        self.state = state
        self.send = send

    async def serve(self, body: dict[str, Any]) -> None:
        request_id = str(body.get("request_id") or "")
        if not _REQUEST_ID.match(request_id):
            return
        path, reason = resolve(self.state, str(body.get("job_id") or ""), str(body.get("path") or ""))
        if path is None:
            await self.send("file_failed", {"request_id": request_id, "reason": reason})
            return
        try:
            data = path.read_bytes()
        except OSError:
            await self.send("file_failed", {"request_id": request_id, "reason": "unreadable"})
            return
        if len(data) > MAX_FILE_BYTES:
            await self.send("file_failed", {"request_id": request_id, "reason": "too_large"})
            return
        digest = hashlib.sha256(data).hexdigest()
        chunks = [data[i:i + CHUNK_BYTES] for i in range(0, len(data), CHUNK_BYTES)] or [b""]
        for seq, chunk in enumerate(chunks):
            last = seq == len(chunks) - 1
            message = {"request_id": request_id, "seq": seq, "data": base64.b64encode(chunk).decode("ascii"),
                       "last": last}
            if last:
                message.update(size=len(data), sha256=digest)
            if not await self.send("file_chunk", message):
                return  # the channel dropped: the platform times the request out and the person asks again


__all__ = ["FileServer", "changed_files", "remember_turn", "resolve"]
