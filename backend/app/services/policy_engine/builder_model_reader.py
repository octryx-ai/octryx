"""The strict field reader behind ``builder_model.model_from_json``: every wrong value is an issue, never dropped."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import fields
from typing import Any

MAX_TEXT = 200
MAX_ITEMS = 50

ISSUE_INVALID = "builder_value_invalid"
ISSUE_UNKNOWN_FIELD = "builder_field_unknown"


class _Reader:
    def __init__(self) -> None:
        self.issues: list[dict[str, str]] = []

    def issue(self, path: str, code: str, message: str) -> None:
        self.issues.append({"path": path, "code": code, "message": message})

    def text(self, raw: Any, path: str, *, limit: int = MAX_TEXT, allowed: Iterable[str] | None = None) -> str:
        if raw is None:
            return ""
        if not isinstance(raw, str) or len(raw) > limit or raw != raw.strip():
            self.issue(path, ISSUE_INVALID, f"Use plain text of at most {limit} characters without outer spaces.")
            return ""
        options = tuple(allowed) if allowed is not None else None
        if raw and options is not None and raw not in options:
            self.issue(path, ISSUE_INVALID, f"Use one of: {', '.join(options)}.")
            return ""
        return raw

    def flag(self, raw: Any, path: str) -> bool:
        if raw is None:
            return False
        if not isinstance(raw, bool):
            self.issue(path, ISSUE_INVALID, "Use true or false.")
            return False
        return raw

    def items(self, raw: Any, path: str, *, allowed: Iterable[str] | None = None) -> tuple[str, ...]:
        if raw is None:
            return ()
        if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
            self.issue(path, ISSUE_INVALID, f"Use a list of at most {MAX_ITEMS} values.")
            return ()
        values = [self.text(item, f"{path}[{index}]", allowed=allowed) for index, item in enumerate(raw)]
        if any(not isinstance(item, str) or not item for item in raw):
            self.issue(path, ISSUE_INVALID, "Values may not be empty.")
        return tuple(dict.fromkeys(value for value in values if value))

    def section(self, raw: Any, path: str, cls: type) -> Mapping[str, Any]:
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            self.issue(path, ISSUE_INVALID, "Use an object.")
            return {}
        known = {item.name for item in fields(cls)}
        for key in sorted(set(raw) - known):
            self.issue(f"{path}.{key}", ISSUE_UNKNOWN_FIELD, "This field is not part of the builder model.")
        return raw


def _paths(reader: _Reader, raw: Any) -> tuple[str, ...]:
    values = reader.items(raw, "what.paths")
    for index, value in enumerate(values):
        if "?" in value or "[" in value:
            reader.issue(f"what.paths[{index}]", ISSUE_INVALID,
                         "Use * as the only wildcard; ? and [..] are not supported.")
    return values


__all__ = ["ISSUE_INVALID", "ISSUE_UNKNOWN_FIELD", "MAX_ITEMS", "MAX_TEXT"]
