"""The content an edit leaves, computed before the workspace write decision."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def proposed_content(file_path: Path, apply: Callable[[str], str]) -> dict[Path, str] | None:
    try:
        return {file_path: apply(file_path.read_text(encoding="utf-8"))}
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def apply_all(content: str, edits: list[dict[str, Any]], apply_edit: Callable[..., tuple[str, str]]) -> str:
    for edit in edits:
        old_string, new_string = edit.get("old_string", ""), edit.get("new_string", "")
        if old_string != new_string:
            content = apply_edit(content, old_string, new_string, bool(edit.get("replace_all", False)))[0]
    return content


__all__ = ["apply_all", "proposed_content"]
