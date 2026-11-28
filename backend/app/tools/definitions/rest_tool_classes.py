"""Which ``rest__`` tools write, and the run class each write needs (custom REST connector)."""

from __future__ import annotations

_WRITE_CLASSES: dict[str, str] = {}


def remember_rest_tool(tool_name: str, write_class: str | None) -> None:
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
