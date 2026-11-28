"""The request's one text (``request_text``) together with where each part of the body sits in it, so one detector
pass over the whole request answers for every part: a finding belongs to a part when it lies inside the part's span."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .request_text import UnreadableRequestError, opaque


@dataclass(frozen=True, slots=True)
class SpannedText:
    text: str
    spans: dict[int, tuple[int, int]]  # id() of a tracked part -> (start, end) in ``text``
    top: dict[str, tuple[int, int]]  # the root mapping's values by key (a string part has no stable id)

    def span(self, part: Any) -> tuple[int, int] | None:
        return self.spans.get(id(part))


# The same characters json.dumps(_readable(value), ensure_ascii=False) writes (request_text), built piece by piece so
# the parts named in ``track`` get their span. A float, a number or a key is written by json.dumps itself.
def spanned_text(value: Any, track: Callable[[Any], bool], skip: Callable[[str], bool] | None = None) -> SpannedText:
    pieces: list[str] = []
    spans: dict[int, tuple[int, int]] = {}
    top: dict[str, tuple[int, int]] = {}
    length = 0

    def write(piece: str) -> None:
        nonlocal length
        pieces.append(piece)
        length += len(piece)

    def emit(item: Any, holder: Mapping[str, Any] | None, key: Any, root: bool = False) -> None:
        start = length
        if isinstance(item, Mapping):
            write("{")
            for index, (name, child) in enumerate(item.items()):
                if index:
                    write(", ")
                write(_dumps(name if isinstance(name, str) else _key(name)))
                write(": ")
                child_start = length
                emit(child, item, name)
                if root and isinstance(name, str):
                    top[name] = (child_start, length)
            write("}")
        elif isinstance(item, list | tuple):
            write("[")
            for index, child in enumerate(item):
                if index:
                    write(", ")
                emit(child, None, None)  # opaque applies to a key's own string, not a list's items
            write("]")
        elif isinstance(item, str) and ((holder is not None and opaque(holder, key, item))
                                        or (skip is not None and skip(item))):
            write('""')
        else:
            write(_dumps(item))
        if track(item):
            spans[id(item)] = (start, length)

    try:
        emit(value, None, None, root=True)
    except RecursionError:
        raise UnreadableRequestError("the request cannot be read as JSON text") from None
    return SpannedText("".join(pieces), spans, top)


def _key(name: Any) -> str:
    # json.dumps writes a non-string key as its JSON form inside quotes (True -> "true", 1 -> "1", None -> "null").
    text = json.dumps({name: 0}, ensure_ascii=False, allow_nan=False)
    return json.loads(text[1:text.rindex(":")])


def _dumps(item: Any) -> str:
    try:
        return json.dumps(item, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise UnreadableRequestError("the request cannot be read as JSON text") from None


__all__ = ["SpannedText", "spanned_text"]
