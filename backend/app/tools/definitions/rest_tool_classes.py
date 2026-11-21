"""Which ``rest__`` tools write, and the run class each write needs (custom REST connector).

The tool metadata (``get_tool_definition_metadata``) and the run class (``tool_required_capability``) are decided
from a tool's name, synchronously, by every gate (chat writes, run capability, approval, unattended runs). A custom
REST operation is a database row an admin edits at any time, so its read/write nature cannot be a static table.
This module is the in-process view of it: the REST connector writes it whenever it reads its operations (the offered
tools of a turn, every ``rest__`` dispatch right before the gates run, an admin's operation update), so the gates
of a dispatch always judge the operation as it is stored now. A name never seen here is a read, and
the executor refuses a write whose stored class the run does not cover, so a stale entry can never let a write
through.
"""

from __future__ import annotations

_WRITE_CLASSES: dict[str, str] = {}


def remember_rest_tool(tool_name: str, write_class: str | None) -> None:
    """Record ``tool_name`` as a write needing ``write_class`` (``change``/``deliver``), or as a read (``None``)."""
    name = str(tool_name or "").strip()
    if not name:
        return
    if write_class:
        _WRITE_CLASSES[name] = write_class
    else:
        _WRITE_CLASSES.pop(name, None)


def rest_write_class(tool_name: str) -> str | None:
    """The run class a ``rest__`` write needs, or ``None`` for a read (or a name not known as a write)."""
    return _WRITE_CLASSES.get(str(tool_name or "").strip())


def forget_rest_tools() -> None:
    _WRITE_CLASSES.clear()


__all__ = ["forget_rest_tools", "remember_rest_tool", "rest_write_class"]
