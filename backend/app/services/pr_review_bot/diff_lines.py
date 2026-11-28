"""Which lines of a pull request a review comment may anchor on, read from its unified diff."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ADDED, CONTEXT = "ADDED", "CONTEXT"
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(slots=True)
class FileChange:
    path: str
    added: int = 0
    removed: int = 0
    status: str = "modified"  # added | deleted | renamed | modified | binary
    old_path: str = ""
    lines: dict[int, str] = field(default_factory=dict)  # new-side line → ADDED | CONTEXT
    old_lines: dict[int, int] = field(default_factory=dict)  # a CONTEXT line's new-side number → its old-side one
    text: dict[int, str] = field(default_factory=dict)  # new-side line → its text (a suggestion's range check)


def _path(header: str) -> str:
    text = header[4:].strip()
    if text == "/dev/null":
        return ""
    return text[2:] if text[:2] in ("a/", "b/") else text


def _start(line: str, files: dict[str, FileChange]) -> FileChange | None:
    parts = line[len("diff --git "):].split(" b/", 1)
    path = parts[1] if len(parts) == 2 else parts[0]
    change = FileChange(path)
    files[path] = change
    return change


def parse_diff(diff: str) -> dict[str, FileChange]:
    files: dict[str, FileChange] = {}
    current: FileChange | None = None
    new_line = old_line = 0
    in_hunk = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            current, in_hunk = _start(line, files), False
            continue
        if current is None:
            continue
        if not in_hunk:
            in_hunk = _header_line(line, current, files)
            if in_hunk:
                old_line, new_line = (int(group) for group in _HUNK.match(line).groups())
            continue
        match = _HUNK.match(line)
        if match:
            old_line, new_line = (int(group) for group in match.groups())
        elif line.startswith("+"):
            current.added += 1
            current.lines[new_line] = ADDED
            current.text[new_line] = line[1:]
            new_line += 1
        elif line.startswith("-"):
            current.removed += 1
            old_line += 1
        elif line.startswith(" ") or line == "":
            current.lines[new_line] = CONTEXT
            current.old_lines[new_line] = old_line
            current.text[new_line] = line[1:]
            new_line += 1
            old_line += 1
    return files


def _header_line(line: str, current: FileChange, files: dict[str, FileChange]) -> bool:
    if line.startswith("new file mode"):
        current.status = "added"
    elif line.startswith("deleted file mode"):
        current.status = "deleted"
    elif line.startswith("rename from "):
        current.status, current.old_path = "renamed", line[len("rename from "):]
    elif line.startswith("Binary files "):
        current.status = "binary" if current.status == "modified" else current.status
    elif line.startswith("+++ "):
        path = _path(line)
        if path and path != current.path:
            files.pop(current.path, None)
            current.path = path
            files[path] = current
    return bool(_HUNK.match(line))


def line_kind(files: dict[str, FileChange], path: str, line: int) -> str:
    change = files.get(path.strip().lstrip("./"))
    return change.lines.get(line, "") if change is not None else ""


def old_line_of(files: dict[str, FileChange], path: str, line: int) -> int:
    change = files.get(path.strip().lstrip("./"))
    return change.old_lines.get(line, 0) if change is not None else 0


def line_text(files: dict[str, FileChange], path: str, line: int) -> str | None:
    change = files.get(path.strip().lstrip("./"))
    return change.text.get(line) if change is not None else None


def range_in_diff(files: dict[str, FileChange], path: str, start: int, end: int) -> bool:
    return start <= end and all(line_kind(files, path, number) for number in range(start, end + 1))


__all__ = ["ADDED", "CONTEXT", "FileChange", "line_kind", "line_text", "old_line_of", "parse_diff", "range_in_diff"]
