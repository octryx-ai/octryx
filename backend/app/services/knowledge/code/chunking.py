"""Code-aware spans with line ranges.

Same text in, same spans out. Each line of the file is owned by the innermost symbol that covers it
(``symbols.py``): a method's lines by the method, the fields and the closing brace of a class by the
class, the package and imports by no symbol. Runs of consecutive lines with the same owner are the
units, so a method is one unit and its class's remaining lines are another. A member's annotations
and its Javadoc or decorators belong to it (the parser's range starts there).

A unit is then bounded: blank lines at its edges are trimmed, a unit without any letter or digit
(a lone ``}``) is dropped, and a unit longer than ``MAX_UNIT_LINES`` lines or ``MAX_SPAN_CHARS``
characters is split into windows of ``WINDOW_LINES`` lines that overlap by ``OVERLAP_LINES``. A file
without symbols (any language without a parser) is windowed whole. A single line longer than
``MAX_SPAN_CHARS`` becomes consecutive character pieces that all carry that line.

Consecutive units of the same top-level declaration are then **merged** into one span while the
merged lines stay within ``MERGE_MAX_LINES`` and ``MAX_SPAN_CHARS``: a member is never
split by the merge, a window never merges, and the file preamble (package, imports) merges only
with itself. One member per span would make spans too fine to answer a question on their own (a
four-line ``initCreationForm`` span carrying ``/owners/new`` but not its class), so a
span holds a class's header together with its first members, or several neighbouring members.
A merged span's ``section_path`` is the common prefix of its units' symbol paths.

Every span records its 1-based, inclusive line range and its character range in the normalized
text, and its ``section_path`` is the owning symbol path, so a citation reads
``Owner.java § addPet`` and links ``#L<start>-L<end>``.
"""

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
    """A bounded unit before merging; ``length`` set only for a piece of one over-long line."""

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
        """Merge consecutive mergeable pieces of one top-level declaration, then add the spans."""
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
    """Ordered, bounded, line-ranged spans of one normalized source file. Deterministic."""
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
