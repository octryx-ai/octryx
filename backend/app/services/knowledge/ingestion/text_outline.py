"""Section-aware spans for Markdown and AsciiDoc."""

from __future__ import annotations

import re

from ..ledger.errors import EvidenceSpanLimitExceededError, InvalidEvidenceRequestError
from .spans import MAX_SPAN_CHARS, MAX_SPANS_PER_REVISION, DerivedSpan, paragraph_pieces

# Recorded as the parser version of outlined revisions: their spans are derived differently from
# plain text (``media_types.PARSER_VERSION``), and lineage must say so.
OUTLINE_PARSER_VERSION = "2-outline"
TARGET_SPAN_CHARS = 1200
MAX_SECTION_DEPTH = 6
MAX_HEADING_CHARS = 200

OUTLINE_SYNTAX_BY_MEDIA_TYPE = {"text/markdown": "markdown", "text/asciidoc": "asciidoc"}
_HEADINGS = {
    "markdown": re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$"),
    "asciidoc": re.compile(r"^(={1,6})[ \t]+(.+?)[ \t]*$"),
}
_ANCHOR_LINE = re.compile(r"^\[\[?[^\]]*\]\]?$")


def _heading(chunk: str, syntax: str) -> tuple[int, str] | None:
    lines = [line for line in chunk.split("\n") if line.strip()]
    while len(lines) > 1 and _ANCHOR_LINE.fullmatch(lines[0].strip()):
        lines.pop(0)
    if len(lines) != 1:
        return None
    match = _HEADINGS[syntax].fullmatch(lines[0].strip())
    if match is None:
        return None
    return len(match.group(1)), " ".join(match.group(2).split())[:MAX_HEADING_CHARS]


def has_outline(text: str, media_type: str) -> bool:
    syntax = OUTLINE_SYNTAX_BY_MEDIA_TYPE.get(media_type)
    return syntax is not None and any(_heading(chunk, syntax) for _, _, chunk in paragraph_pieces(text))


def derive_outlined_spans(text: str, media_type: str) -> tuple[DerivedSpan, ...]:
    syntax = OUTLINE_SYNTAX_BY_MEDIA_TYPE.get(media_type)
    if syntax is None:
        raise InvalidEvidenceRequestError()
    headings: list[tuple[int, str]] = []
    spans: list[DerivedSpan] = []
    # (start, end, is_heading, section path at this piece)
    group: list[tuple[int, int, bool, tuple[str, ...]]] = []

    def flush() -> None:
        if not group:
            return
        if len(spans) >= MAX_SPANS_PER_REVISION:
            raise EvidenceSpanLimitExceededError()
        start, end = group[0][0], group[-1][1]
        content = [piece for piece in group if not piece[2]] or group
        spans.append(
            DerivedSpan(
                span_ordinal=len(spans) + 1,
                char_start=start,
                char_end=end,
                text=text[start:end].strip(),
                section_path=content[0][3],
            )
        )
        group.clear()

    for start, end, chunk in paragraph_pieces(text):
        heading = _heading(chunk, syntax)
        if heading is not None:
            level, title = heading
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
        path = tuple(title for _, title in headings[:MAX_SECTION_DEPTH])
        has_content = any(not piece[2] for piece in group)
        length = end - (group[0][0] if group else start)
        if length > MAX_SPAN_CHARS:
            flush()
        elif heading is not None:
            if has_content:
                flush()
        elif has_content and length > TARGET_SPAN_CHARS:
            flush()
        group.append((start, end, heading is not None, path))
    flush()
    if not spans:
        raise InvalidEvidenceRequestError()
    return tuple(spans)


__all__ = ["OUTLINE_PARSER_VERSION", "derive_outlined_spans", "has_outline"]
