"""A function's tool set: tool names and selectors, matched against a tool's registry metadata."""
from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable
from functools import lru_cache

RISKS = ("read", "write", "admin")
_NAME = re.compile(r"^[A-Za-z0-9_*?.\-]{1,120}$")
_CONNECTOR = re.compile(r"^[a-z0-9_*]{1,40}$")


class ToolSetError(ValueError):
    def __init__(self, entry: str) -> None:
        super().__init__(f"Not a tool name or selector: {entry!r}")
        self.entry = entry


def normalize_entry(raw: object) -> str:
    entry = str(raw or "").strip()
    if entry.startswith("risk:"):
        if entry[5:] not in RISKS:
            raise ToolSetError(entry)
        return entry
    if entry.startswith("connector:"):
        parts = entry.split(":")
        if len(parts) not in (2, 3) or not _CONNECTOR.match(parts[1]) or (len(parts) == 3 and parts[2] not in RISKS):
            raise ToolSetError(entry)
        return entry
    if not _NAME.match(entry):
        raise ToolSetError(entry)
    return entry


def normalize_entries(raw: Iterable[object] | None) -> list[str]:
    return list(dict.fromkeys(normalize_entry(item) for item in (raw or [])))


@lru_cache(maxsize=4096)
def _metadata(tool_name: str) -> tuple[str, str]:
    from ...tools.definitions import get_tool_definition_metadata

    metadata = get_tool_definition_metadata(tool_name)
    connector = str(metadata.connector or "") if metadata.owner_type == "connector" else ""
    return connector, str(metadata.risk or "")


def entry_matches(entry: str, tool_name: str) -> bool:
    if entry.startswith("risk:"):
        return _metadata(tool_name)[1] == entry[5:]
    if entry.startswith("connector:"):
        parts = entry.split(":")
        connector, risk = _metadata(tool_name)
        if not connector or not fnmatch.fnmatchcase(connector, parts[1]):
            return False
        return len(parts) == 2 or risk == parts[2]
    if "*" in entry or "?" in entry:
        return fnmatch.fnmatchcase(tool_name, entry)
    return entry == tool_name


def entries_match(entries: Iterable[str], tool_name: str) -> bool:
    return any(entry_matches(entry, tool_name) for entry in entries)


def is_selector(entry: str) -> bool:
    return entry.startswith(("risk:", "connector:")) or "*" in entry or "?" in entry


__all__ = ["RISKS", "ToolSetError", "entries_match", "entry_matches", "is_selector", "normalize_entries",
           "normalize_entry"]
