"""The relay's guard: only the mail the bridge asked for passes its PreToolUse hook (``mobile_relay``). The requested
``(address, text)`` pairs live in the relay's own folder, locked, each usable once until it expires."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import time
from pathlib import Path
from typing import Any

DELIVERY_SECONDS = 120.0
ALLOWED_FILE = "allowed.json"
PEER = re.compile(r"^uds:/[A-Za-z0-9_./-]{1,280}\.sock$")


@contextlib.contextmanager
def _locked(folder: Path):
    with (folder / ".lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _read_allowed(folder: Path) -> list[list[Any]]:
    try:
        data = json.loads((folder / ALLOWED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in data if isinstance(item, list) and len(item) == 3] if isinstance(data, list) else []


def _write_allowed(folder: Path, items: list[list[Any]]) -> None:
    tmp = folder / f".{ALLOWED_FILE}.tmp"
    tmp.write_text(json.dumps(items), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, folder / ALLOWED_FILE)


def allow(folder: Path, to: str, message: str, *, seconds: float = DELIVERY_SECONDS) -> None:
    with _locked(folder):
        now = time.time()
        items = [item for item in _read_allowed(folder) if float(item[2]) > now]
        _write_allowed(folder, [*items, [to, message, now + seconds]])


def revoke(folder: Path, to: str, message: str) -> None:
    with _locked(folder):
        items = _read_allowed(folder)
        for index, item in enumerate(items):
            if item[0] == to and item[1] == message:
                del items[index]
                break
        _write_allowed(folder, items)


def consume(folder: Path, to: str, message: str) -> bool:
    """``True`` once for a requested, unexpired ``(to, message)``; it is then used up."""
    with _locked(folder):
        now = time.time()
        items = [item for item in _read_allowed(folder) if float(item[2]) > now]
        for index, item in enumerate(items):
            if item[0] == to and item[1] == message:
                del items[index]
                _write_allowed(folder, items)
                return True
        _write_allowed(folder, items)
        return False


def guard(folder: Path, hook_input: dict[str, Any]) -> str:
    """The PreToolUse decision for one relay tool call: ``""`` allows it, anything else is the refusal."""
    if hook_input.get("tool_name") != "SendMessage":
        return f"the relay may only send mail, not use {str(hook_input.get('tool_name'))[:40]}"
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    to, message = tool_input.get("to"), tool_input.get("message")
    if not isinstance(to, str) or not isinstance(message, str) or not PEER.match(to):
        return "not a requested mail"
    if not consume(folder, to, message):
        return "not a requested mail: the address and the text must be exactly what the phone sent"
    return ""
