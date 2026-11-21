"""What the Stop hook tells the person's phone about this session.

From the transcript in the session's own config dir: the title (the first prompt's first line) and the last
answer, both redacted with the session digest's own redaction (``mcp_session_ingest_common.redact``) and capped.
Best effort: anything unreadable or unexpected gives no summary, never an error. It runs in the Stop hook ahead of
the verification call, so no failure here may ever reach the hook (a broken transcript or config
must not end in "stopping without verification").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .digest import _SCRIPTS_DIR, transcript_inside
from .state import LocalState

MAX_TITLE = 80
MAX_READ_TITLE = 2000  # redaction sees the whole line before it is cut (a secret split at the cut stays hidden)
MAX_LAST_TEXT = 4000
MAX_READ_BYTES = 4 * 1024 * 1024


def _redact(text: str) -> str:
    scripts = str(_SCRIPTS_DIR)
    if scripts not in sys.path:
        sys.path.append(scripts)
    import mcp_session_ingest_common  # noqa: PLC0415 - lives outside this package

    return mcp_session_ingest_common.redact(text)


def _texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [str(part.get("text") or "") for part in content
                if isinstance(part, dict) and part.get("type") == "text" and part.get("text")]
    return []


def read_summary(transcript: Path) -> dict[str, str]:
    """``{"title", "last_text"}`` from a Claude Code transcript (JSON lines), each only when found."""
    size = transcript.stat().st_size
    with transcript.open("rb") as handle:
        head = handle.read(min(size, 256 * 1024))
        if size > MAX_READ_BYTES:
            handle.seek(size - MAX_READ_BYTES)
        tail = handle.read() if size > 256 * 1024 else b""
    title, last = "", ""
    for raw in head.splitlines():
        entry = _entry(raw)
        if entry.get("type") == "user" and not title:
            text = " ".join(_texts((entry.get("message") or {}).get("content"))).strip()
            if text and not text.startswith("<"):  # command wrappers and system reminders are no title
                title = text.splitlines()[0][:MAX_READ_TITLE]
    for raw in (head + tail).splitlines():
        entry = _entry(raw)
        if entry.get("type") == "assistant":
            text = "\n".join(_texts((entry.get("message") or {}).get("content"))).strip()
            if text:
                last = text
    summary = {}
    if title:
        summary["title"] = _redact(title)[:MAX_TITLE]
    if last:
        summary["last_text"] = _redact(last)[-MAX_LAST_TEXT:]
    return summary


def _entry(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def stop_summary(state: LocalState, hook_input: dict[str, Any]) -> dict[str, str]:
    """The summary for the Stop hook's body (``mobile``), or ``{}``; never raises."""
    try:
        transcript_path = str(hook_input.get("transcript_path") or "")
        transcript = next(
            (found for root in (state.claude_config_dir, state.claude_config_dir_for("seat"))
             if (found := transcript_inside(transcript_path, root)) is not None),
            None,
        )
        if transcript is None:
            return {}
        summary = read_summary(transcript)
        return {key: value for key, value in summary.items() if isinstance(value, str)}
    except Exception:  # noqa: BLE001 - the phone's summary must never cost the verification gate
        return {}


__all__ = ["read_summary", "stop_summary"]
