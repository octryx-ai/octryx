"""Turn a parsed DoclingDocument into ordered, located, citable spans. Pure and deterministic; an unknown structure is a
parser contract violation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ....models.project.knowledge_parsing import (
    SPAN_KIND_CODE,
    SPAN_KIND_HEADING,
    SPAN_KIND_LIST,
    SPAN_KIND_TABLE,
    SPAN_KIND_TEXT,
)
from ..ledger.errors import EvidenceSpanLimitExceededError, InvalidEvidenceRequestError
from .docling_items import ADMONITION_MARKERS, Block
from .docling_walk import document_blocks
from .spans import MAX_SPAN_CHARS, DerivedSpan

TARGET_SPAN_CHARS = 1200
MAX_PARSED_SPANS = 10000
_SEPARATOR = "\n\n"
_STANDALONE_KINDS = frozenset({SPAN_KIND_TABLE, SPAN_KIND_CODE})


@dataclass(frozen=True, slots=True)
class LocatedSpan:
    span: DerivedSpan
    kind: str
    page_start: int | None
    page_end: int | None
    section_path: tuple[str, ...]


def _pieces(block: Block) -> list[Block]:
    if len(block.text) <= TARGET_SPAN_CHARS:
        return [block]
    separator = "\n" if "\n" in block.text else " "
    pieces: list[str] = []
    current = ""
    for part in block.text.split(separator):
        while len(part) > TARGET_SPAN_CHARS:  # one unbroken run: a deterministic hard cut
            if current:
                pieces.append(current)
                current = ""
            pieces.append(part[:TARGET_SPAN_CHARS])
            part = part[TARGET_SPAN_CHARS:]
        candidate = f"{current}{separator}{part}" if current else part
        if len(candidate) > TARGET_SPAN_CHARS:
            pieces.append(current)
            current = part
        else:
            current = candidate
    if current:
        pieces.append(current)
    return [replace(block, text=piece) for piece in pieces if piece.strip()]


def _group_kind(group: list[Block]) -> str:
    content = [block.kind for block in group if block.kind != SPAN_KIND_HEADING]
    if not content:
        return SPAN_KIND_HEADING
    for kind in (SPAN_KIND_TABLE, SPAN_KIND_CODE):
        if kind in content:
            return kind
    return SPAN_KIND_LIST if all(kind == SPAN_KIND_LIST for kind in content) else SPAN_KIND_TEXT


def located_spans(blocks: list[Block]) -> tuple[str, tuple[LocatedSpan, ...]]:
    pieces = [piece for block in blocks for piece in _pieces(block)]
    if not pieces:
        raise InvalidEvidenceRequestError()
    offsets: list[tuple[int, int]] = []
    position = 0
    for piece in pieces:
        offsets.append((position, position + len(piece.text)))
        position += len(piece.text) + len(_SEPARATOR)
    text = _SEPARATOR.join(piece.text for piece in pieces)

    spans: list[LocatedSpan] = []
    group: list[int] = []

    def flush() -> None:
        if not group:
            return
        if len(spans) >= MAX_PARSED_SPANS:
            raise EvidenceSpanLimitExceededError()
        members = [pieces[index] for index in group]
        start, end = offsets[group[0]][0], offsets[group[-1]][1]
        content = [block for block in members if block.kind != SPAN_KIND_HEADING] or members
        pages = [block.page for block in members if block.page is not None]
        spans.append(
            LocatedSpan(
                span=DerivedSpan(span_ordinal=len(spans) + 1, char_start=start, char_end=end, text=text[start:end]),
                kind=_group_kind(members),
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                section_path=content[0].section_path,
            )
        )
        group.clear()

    for index, piece in enumerate(pieces):
        has_content = any(pieces[member].kind != SPAN_KIND_HEADING for member in group)
        length = offsets[index][1] - (offsets[group[0]][0] if group else offsets[index][0])
        standalone = piece.kind in _STANDALONE_KINDS
        if length > MAX_SPAN_CHARS:
            flush()  # the hard bound, whatever the group holds (a long run of headings, say)
        elif piece.kind == SPAN_KIND_HEADING or standalone:
            if has_content:
                flush()  # a heading opens the next span; a table or code block is its own span
        elif has_content and length > TARGET_SPAN_CHARS:
            flush()
        group.append(index)
        if standalone:
            flush()
    flush()
    return text, tuple(spans)


def parse_document(
    document: object, *, admonitions: tuple[str, ...] = ADMONITION_MARKERS, outline: object = None
) -> tuple[LocatedSpan, ...]:
    return located_spans(document_blocks(document, admonitions=admonitions, outline=outline))[1]


__all__ = [
    "LocatedSpan",
    "MAX_PARSED_SPANS",
    "located_spans",
    "parse_document",
]
