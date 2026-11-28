"""Code-aware spans with line ranges. Same text in, same spans out: each line belongs to its innermost symbol."""

from __future__ import annotations

from dataclasses import dataclass

from ..ingestion.spans import MAX_SPAN_CHARS, MAX_SPANS_PER_REVISION, DerivedSpan
from ..ledger.errors import EvidenceSpanLimitExceededError, InvalidEvidenceRequestError
from .symbols import symbols_of

MAX_UNIT_LINES = 80
WINDOW_LINES = 60
OVERLAP_LINES = 10
MERGE_MAX_LINES = 60


def _owners(line_count: int, text: str, language: str | None) -> list[tuple[str, ...]]:
    owners: list[tuple[str, ...]] = [()] * line_count
    # Outer symbols first, so an inner symbol overwrites the lines it covers.
    for symbol in sorted(symbols_of(text, language), key=lambda item: len(item.path)):
        for line in range(max(1, symbol.line_start), min(line_count, symbol.line_end) + 1):
            owners[line - 1] = symbol.path
    return owners


def _units(lines: list[str], owners: list[tuple[str, ...]]) -> list[tuple[int, int, tuple[str, ...]]]:
    units: list[tuple[int, int, tuple[str, ...]]] = []
    start = 1
    for number in range(2, len(lines) + 2):
        if number > len(lines) or owners[number - 1] != owners[start - 1]:
            units.append((start, number - 1, owners[start - 1]))
            start = number
    return units


@dataclass(frozen=True, slots=True)
class _Piece:
    first: int
    last: int
    path: tuple[str, ...]
    mergeable: bool
    offset: int = 0
    length: int | None = None

    @property
    def top(self) -> str | None:
        # The top-level declaration a piece belongs to; ``None`` is the file preamble.
        return self.path[0] if self.path else None


def _common_prefix(paths: list[tuple[str, ...]]) -> tuple[str, ...]:
    prefix = paths[0]
    for path in paths[1:]:
        size = 0
        while size < min(len(prefix), len(path)) and prefix[size] == path[size]:
            size += 1
        prefix = prefix[:size]
    return prefix


class _Builder:
    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        self.offsets: list[int] = []
        position = 0
        for line in self.lines:
            self.offsets.append(position)
            position += len(line) + 1
        self.spans: list[DerivedSpan] = []
        self.pieces: list[_Piece] = []

    def _text(self, first: int, last: int) -> str:
        return "\n".join(self.lines[first - 1 : last])

    def _add(self, first: int, last: int, path: tuple[str, ...], start: int, chunk: str) -> None:
        if len(self.spans) >= MAX_SPANS_PER_REVISION:
            raise EvidenceSpanLimitExceededError()
        self.spans.append(
            DerivedSpan(
                span_ordinal=len(self.spans) + 1,
                char_start=start,
                char_end=start + len(chunk),
                text=chunk,
                section_path=path,
                line_start=first,
                line_end=last,
            )
        )

    def _piece(self, first: int, last: int, path: tuple[str, ...], *, mergeable: bool) -> None:
        self.pieces.append(_Piece(first, last, path, mergeable))

    def unit(self, first: int, last: int, path: tuple[str, ...]) -> None:
        while first <= last and not self.lines[first - 1].strip():
            first += 1
        while last >= first and not self.lines[last - 1].strip():
            last -= 1
        if first > last or not any(ch.isalnum() for ch in self._text(first, last)):
            return
        if last - first + 1 <= MAX_UNIT_LINES and len(self._text(first, last)) <= MAX_SPAN_CHARS:
            self._piece(first, last, path, mergeable=True)
            return
        self.windows(first, last, path)

    def windows(self, first: int, last: int, path: tuple[str, ...]) -> None:
        start = first
        while start <= last:
            end = min(last, start + WINDOW_LINES - 1)
            while end > start and len(self._text(start, end)) > MAX_SPAN_CHARS:
                end -= 1
            chunk = self._text(start, end)
            if len(chunk) > MAX_SPAN_CHARS:
                self.long_line(start, path)
            elif chunk.strip():
                self._piece(start, end, path, mergeable=False)
            if end >= last:
                return
            start = max(start + 1, end - OVERLAP_LINES + 1) if end - start + 1 > OVERLAP_LINES else end + 1

    def long_line(self, number: int, path: tuple[str, ...]) -> None:
        line = self.lines[number - 1]
        for position in range(0, len(line), MAX_SPAN_CHARS):
            chunk = line[position : position + MAX_SPAN_CHARS]
            if chunk.strip():
                self.pieces.append(_Piece(number, number, path, False, position, len(chunk)))

    def emit(self) -> None:
        group: list[_Piece] = []
        for piece in self.pieces:
            if group and not self._fits(group, piece):
                self._emit_group(group)
                group = []
            group.append(piece)
        if group:
            self._emit_group(group)

    def _fits(self, group: list[_Piece], piece: _Piece) -> bool:
        head = group[0]
        if not (head.mergeable and piece.mergeable and head.top == piece.top):
            return False
        if piece.last - head.first + 1 > MERGE_MAX_LINES:
            return False
        return len(self._text(head.first, piece.last)) <= MAX_SPAN_CHARS

    def _emit_group(self, group: list[_Piece]) -> None:
        head, tail = group[0], group[-1]
        if head.length is not None:
            line = self.lines[head.first - 1]
            chunk = line[head.offset : head.offset + head.length]
            self._add(head.first, head.first, head.path, self.offsets[head.first - 1] + head.offset, chunk)
            return
        path = _common_prefix([piece.path for piece in group])
        self._add(head.first, tail.last, path, self.offsets[head.first - 1], self._text(head.first, tail.last))


def derive_code_spans(text: str, language: str | None) -> tuple[DerivedSpan, ...]:
    if type(text) is not str or not text.strip():
        raise InvalidEvidenceRequestError()
    builder = _Builder(text)
    owners = _owners(len(builder.lines), text, language)
    for first, last, path in _units(builder.lines, owners):
        builder.unit(first, last, path)
    builder.emit()
    if not builder.spans:
        raise InvalidEvidenceRequestError()
    return tuple(builder.spans)


__all__ = ["MAX_UNIT_LINES", "MERGE_MAX_LINES", "OVERLAP_LINES", "WINDOW_LINES", "derive_code_spans"]
