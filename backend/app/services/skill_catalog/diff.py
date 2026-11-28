"""Per-file line diffs between two skill bundles (review drawer, update view). Deterministic (difflib)."""

from __future__ import annotations

import difflib
from typing import Any

MAX_DIFF_LINES = 4000


def line_diff(old: str, new: str) -> list[dict[str, str]]:
    old_lines, new_lines = old.splitlines(), new.splitlines()
    rows: list[dict[str, str]] = []
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, a_start, a_end, b_start, b_end in matcher.get_opcodes():
        if tag == "equal":
            rows += [{"kind": "same", "text": line} for line in old_lines[a_start:a_end]]
            continue
        rows += [{"kind": "removed", "text": line} for line in old_lines[a_start:a_end]]
        rows += [{"kind": "added", "text": line} for line in new_lines[b_start:b_end]]
    return rows


def bundle_diff(old: dict[str, str], new: dict[str, str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(set(old) | set(new)):
        before, after = old.get(path), new.get(path)
        status = ("added" if before is None else "removed" if after is None
                  else "unchanged" if before == after else "changed")
        lines = [] if status == "unchanged" else line_diff(before or "", after or "")
        truncated = len(lines) > MAX_DIFF_LINES
        entries.append({
            "path": path, "status": status,
            "added": sum(1 for line in lines if line["kind"] == "added"),
            "removed": sum(1 for line in lines if line["kind"] == "removed"),
            "lines": lines[:MAX_DIFF_LINES], "truncated": truncated,
        })
    return entries


__all__ = ["bundle_diff", "line_diff"]
