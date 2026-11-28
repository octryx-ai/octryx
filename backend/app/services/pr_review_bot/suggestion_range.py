"""The exact lines a one-click suggestion replaces."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .diff_lines import FileChange, line_text

SIMILAR = 0.75
SAME_START = 0.5
MIN_CHARS = 8
NEAR = 3  # how far a range the suggestion does not rewrite is moved to the line it does (a reviewer's off-by-n)
_WORD = re.compile(r"[A-Za-z_][\w.]*")


def _first_word(text: str) -> str:
    match = _WORD.match(text)
    return match.group(0) if match else ""


def rewrites(new: str, old: str) -> bool:
    ratio = SequenceMatcher(None, new, old).ratio()
    return ratio >= SIMILAR or (ratio >= SAME_START and _first_word(new) != "" and _first_word(new) == _first_word(old))


def _comparable(files: dict[str, FileChange], path: str, line: int) -> str:
    text = (line_text(files, path, line) or "").strip()
    return text if len(text) >= MIN_CHARS else ""


def _matches(lines: list[str], text: str) -> list[int]:
    return [index for index, line in enumerate(lines) if text and rewrites(line, text)]


def _nearby(lines: list[str], files: dict[str, FileChange], path: str, start: int,
            end: int) -> tuple[int, int, list[int]] | None:
    for offset in (1, -1, 2, -2, 3, -3)[: 2 * NEAR]:
        moved = range(start + offset, end + offset + 1)
        if start + offset < 1 or any(line_text(files, path, number) is None for number in moved):
            continue
        inside = [index for number in moved for index in _matches(lines, _comparable(files, path, number))]
        if inside:
            return start + offset, end + offset, inside
    return None


def cover(files: dict[str, FileChange], path: str, start: int, end: int, suggestion: str) -> tuple[int, int]:
    lines = [line.strip() for line in suggestion.splitlines()]
    inside = [index for number in range(start, end + 1) for index in _matches(lines, _comparable(files, path, number))]
    if not inside:
        shifted = _nearby(lines, files, path, start, end)
        if shifted is None:
            return start, end  # the suggestion rewrites nothing near its range: no anchor to grow from
        start, end, inside = shifted
    first, last = min(inside), max(inside)
    while above := [index for index in _matches(lines, _comparable(files, path, start - 1)) if index < first]:
        start, first = start - 1, max(above)
    while below := [index for index in _matches(lines, _comparable(files, path, end + 1)) if index > last]:
        end, last = end + 1, min(below)
    return start, end


__all__ = ["cover", "rewrites"]
