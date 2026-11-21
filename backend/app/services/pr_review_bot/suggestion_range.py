"""The exact lines a one-click suggestion replaces. Pure.

A suggestion replaces the lines ``start_line``..``line`` with its text (``verdict.SUGGESTION_RULE``). A reviewer
sometimes rewrites a line next to its range too (e.g. a finding on line 35, the ``return``, whose suggestion of four
lines begins with a new ``percent = COUPONS.get(…)``, a rewrite of line 34). Applied as given, the old line stays
next to the new ones: there ``percent = COUPONS[code]`` still raises the ``KeyError``
the suggestion was meant to fix. A correctness error, not a style one.

:func:`cover` therefore reads the lines around the range on the new side of the diff. While the line above is
rewritten by an earlier line of the suggestion, or the line below by a later one (in order), the range grows over
it. It only grows over lines on the diff, so it stays one anchorable range, and only from a range the suggestion
visibly rewrites. Lines too short to compare (a bracket,
``else:``) and lines off the diff end the check.

A range of which the suggestion rewrites nothing is first moved to the nearest line within :data:`NEAR` lines that
it does rewrite (e.g. a finding naming line 32, the ``def``, for a suggestion that rewrites the
``if`` on line 34; one click would replace the ``def``).

A line rewrites another when both are similar (:data:`SIMILAR`), or when they start with the same word (the same
assignment target, the same ``return``) and are still somewhat similar (:data:`SAME_START`).
"""

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
    """Whether the suggestion line ``new`` is a rewrite of the file line ``old`` (both stripped)."""
    ratio = SequenceMatcher(None, new, old).ratio()
    return ratio >= SIMILAR or (ratio >= SAME_START and _first_word(new) != "" and _first_word(new) == _first_word(old))


def _comparable(files: dict[str, FileChange], path: str, line: int) -> str:
    text = (line_text(files, path, line) or "").strip()
    return text if len(text) >= MIN_CHARS else ""


def _matches(lines: list[str], text: str) -> list[int]:
    return [index for index, line in enumerate(lines) if text and rewrites(line, text)]


def _nearby(lines: list[str], files: dict[str, FileChange], path: str, start: int,
            end: int) -> tuple[int, int, list[int]] | None:
    """The range moved by the nearest offset (up to :data:`NEAR`) at which the suggestion rewrites a line of it."""
    for offset in (1, -1, 2, -2, 3, -3)[: 2 * NEAR]:
        moved = range(start + offset, end + offset + 1)
        if start + offset < 1 or any(line_text(files, path, number) is None for number in moved):
            continue
        inside = [index for number in moved for index in _matches(lines, _comparable(files, path, number))]
        if inside:
            return start + offset, end + offset, inside
    return None


def cover(files: dict[str, FileChange], path: str, start: int, end: int, suggestion: str) -> tuple[int, int]:
    """``(start, end)``: the lines the suggestion really replaces."""
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
