"""Section paths from a PDF's outline (bookmarks).

Docling reports every heading of the vendor manuals at level 1, so a span's section path is only its
nearest heading. The PDF outline has the real hierarchy (1300–1400 entries, six levels). Given that
outline, a span's path is the ancestor chain of the deepest bookmark at or before the span's start
(by page, then by distance from the page top), capped at :data:`MAX_OUTLINE_DEPTH` levels.

An entry is ``(level, title, page)`` or ``(level, title, page, top)``: ``level`` from 0, ``page`` from 1,
``top`` the distance in points from the page's top edge (``None``: the top of the page). A malformed
outline is ignored as a whole, so the document keeps its heading-based paths.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

MAX_OUTLINE_DEPTH = 6
MAX_OUTLINE_ENTRIES = 20_000
MAX_OUTLINE_TITLE_CHARS = 200


@dataclass(frozen=True, slots=True)
class OutlineIndex:
    keys: tuple[tuple[int, float], ...]
    paths: tuple[tuple[str, ...], ...]

    def path_at(self, page: int | None, top: float | None) -> tuple[str, ...] | None:
        """The section path of content starting at ``page``/``top``; ``None`` before the first bookmark."""
        if page is None:
            return None
        index = bisect_right(self.keys, (page, top if top is not None else 0.0)) - 1
        return self.paths[index] if index >= 0 else None


def _entry(raw: object) -> tuple[int, str, int, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) not in (3, 4):
        return None
    level, title, page = raw[0], raw[1], raw[2]
    top = raw[3] if len(raw) == 4 else None
    if type(level) is not int or level < 0 or type(page) is not int or page < 1 or type(title) is not str:
        return None
    if top is not None and (type(top) not in (int, float) or top < 0):
        return None
    clean = " ".join(title.split())[:MAX_OUTLINE_TITLE_CHARS].rstrip()
    return (level, clean, page, float(top or 0.0)) if clean else None


def outline_index(outline: object) -> OutlineIndex | None:
    """The lookup for an outline, or ``None`` when there is none or it is malformed."""
    if not isinstance(outline, (list, tuple)) or not outline or len(outline) > MAX_OUTLINE_ENTRIES:
        return None
    entries = [_entry(raw) for raw in outline]
    if any(entry is None for entry in entries):
        return None
    stack: list[tuple[int, str]] = []
    located: list[tuple[tuple[int, float], int, tuple[str, ...]]] = []
    for order, (level, title, page, top) in enumerate(entries):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        located.append(((page, top), order, tuple(text for _, text in stack[:MAX_OUTLINE_DEPTH])))
    located.sort(key=lambda item: (item[0], item[1]))  # by position; document order breaks ties
    return OutlineIndex(keys=tuple(key for key, _, _ in located), paths=tuple(path for _, _, path in located))


__all__ = ["MAX_OUTLINE_DEPTH", "OutlineIndex", "outline_index"]
