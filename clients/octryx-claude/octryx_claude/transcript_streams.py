"""A Claude Code session's transcript files on this Mac: its session id, its streams and their complete lines."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

READ_BYTES = 8 * 1024 * 1024
# The platform takes a batch of up to 16 MB; one line beyond this goes as a stub that says so.
MAX_LINE_BYTES = 12 * 1024 * 1024
STREAM_MAIN = "main"
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_AGENT_STREAM = re.compile(r"^agent-[A-Za-z0-9_-]{1,70}$")


def claude_session_for(session_key: str, claude_args: list[str] | tuple[str, ...]) -> str:
    args = list(claude_args)
    if any(arg in ("-c", "--continue", "--fork-session", "--from-pr") or arg.startswith("--from-pr=")
           for arg in args):
        return ""
    for index, arg in enumerate(args):
        name, _, inline = arg.partition("=")
        if name in ("-r", "--resume", "--session-id"):
            value = inline or (args[index + 1] if index + 1 < len(args) else "")
            return value if _SESSION_ID.match(value) else ""
    return session_key


def stream_files(config_dir: Path, claude_session_id: str) -> dict[str, Path]:
    if not _SESSION_ID.match(claude_session_id):
        return {}
    projects = (config_dir / "projects").resolve()
    found: dict[str, Path] = {}
    candidates = [(STREAM_MAIN, path) for path in projects.glob(f"*/{claude_session_id}.jsonl")]
    candidates += [(path.stem, path) for path in projects.glob(f"*/{claude_session_id}/subagents/agent-*.jsonl")]
    for stream, path in candidates:
        if stream != STREAM_MAIN and not _AGENT_STREAM.match(stream):
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if path.is_symlink() or not resolved.is_file() or projects not in resolved.parents:
            continue
        found.setdefault(stream, resolved)
    return found


def read_complete_lines(path: Path, offset: int) -> tuple[list[bytes], int]:
    size = path.stat().st_size
    if size <= offset:
        return [], offset
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read(min(size - offset, READ_BYTES))
        while b"\n" not in data and offset + len(data) < size:  # one line longer than a read
            more = handle.read(READ_BYTES)
            if not more:
                break
            data += more
    end = data.rfind(b"\n") + 1
    return data[:end].split(b"\n")[:-1], offset + end


def _entry(raw: bytes) -> Any:
    if len(raw) > MAX_LINE_BYTES:
        return {"type": "octryx_omitted", "reason": "line_too_large", "bytes": len(raw)}
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return {"type": "octryx_unparsed", "text": raw.decode("utf-8", errors="replace")}
