"""The Claude Code sessions running on this machine right now, of every profile (Octryx Mobile "live").

Claude Code registers every running session in ``<config dir>/sessions/<pid>.json``: its name, folder, status (busy or
idle), session id and the socket of its inbox (``messagingSocketPath``). Another session reaches it with a cross-session
message to ``uds:<socket>``, across profiles. :func:`live_sessions` lists them, for the person's phone:

- every profile: ``~/.claude`` and every ``~/.claude-*`` (octryx's own config dirs live elsewhere);
- only records whose process is alive and whose inbox socket exists (stale files of ended sessions stay out);
- never the relay itself (:data:`RELAY_NAME`) and never octryx's own config dirs.

Nothing here reads a key file or a transcript; only the registry fields above leave the machine.
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from .state import LocalState

RELAY_NAME = "octryx-mobile"
MAX_SESSIONS = 40
PID_FILE = re.compile(r"^\d{1,9}\.json$")


def profile_label(config_dir: Path, home: Path) -> str:
    """``~/.claude`` is "default"; ``~/.claude-private`` is "private"; anything else its folder name."""
    if config_dir == (home / ".claude").resolve():
        return "default"
    stem = config_dir.name.removeprefix(".claude").strip("-_.").lower() or config_dir.name.lower()
    return re.sub(r"[^a-z0-9_-]", "", stem)[:8] or "profile"


def _profile_dirs(state: LocalState, home: Path) -> list[tuple[str, Path]]:
    dirs: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    own = state.root.resolve()
    for candidate in [home / ".claude", *sorted(home.glob(".claude-*"))]:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not (resolved / "sessions").is_dir() or own in (resolved, *resolved.parents):
            continue
        seen.add(resolved)
        dirs.append((profile_label(resolved, home), resolved))
    return dirs


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _socket(path: str) -> bool:
    try:
        return stat.S_ISSOCK(os.stat(path).st_mode)
    except OSError:
        return False


def live_sessions(state: LocalState, *, home: Path | None = None) -> list[dict[str, Any]]:
    """The running sessions of every profile, newest activity first; never raises."""
    home = home or Path.home()
    out: list[dict[str, Any]] = []
    for profile, config_dir in _profile_dirs(state, home):
        try:
            names = sorted(path.name for path in (config_dir / "sessions").iterdir() if PID_FILE.match(path.name))
        except OSError:
            continue
        for name in names:
            try:
                record = json.loads((config_dir / "sessions" / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            pid, socket = record.get("pid"), record.get("messagingSocketPath")
            if type(pid) is not int or not isinstance(socket, str) or not _alive(pid) or not _socket(socket):
                continue
            if record.get("name") == RELAY_NAME:
                continue
            out.append({
                "profile": profile[:8],
                "pid": pid,
                "session_id": str(record.get("sessionId") or "")[:64],
                "name": str(record.get("name") or "")[:120],
                "cwd": str(record.get("cwd") or "")[:500],
                "status": str(record.get("status") or "")[:20],
                "kind": str(record.get("kind") or "")[:20],
                "peer": f"uds:{socket}"[:300],
                "updated_at": int(record.get("updatedAt") or record.get("startedAt") or 0),
            })
    out.sort(key=lambda item: item["updated_at"], reverse=True)
    unique: dict[str, dict[str, Any]] = {}
    for item in out:  # one session may be registered in two profiles' directories; its inbox is one
        unique.setdefault(item["peer"], item)
    return list(unique.values())[:MAX_SESSIONS]


__all__ = ["RELAY_NAME", "live_sessions", "profile_label"]
