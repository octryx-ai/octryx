"""Deterministic span, evidence-key, and citation derivation.

Same bytes in, same spans out: the split depends only on the decoded text, so a
projection can always be rebuilt from the stored object without invalidating a
citation that was already handed out.

Pipeline:

1. decode as strict UTF-8 (no lenient fallback: undecodable bytes are a typed
   refusal, never mojibake silently persisted as evidence);
2. normalize line endings to ``\\n`` and drop unsafe characters (the same
   character-safety rule the retrieval contract enforces, applied once at
   ingestion so stored spans can always be constructed into ``Evidence``);
3. split on blank lines into paragraphs, then hard-wrap any paragraph longer
   than :data:`MAX_SPAN_CHARS` at a whitespace boundary;
4. number spans from 1 and record each span's ``[char_start, char_end)`` range
   in the *normalized* text, which is the text the digest-verified bytes decode
   to.

The evidence key is ``<revision_id_hex>:<span_ordinal>``. It is validated
against the retrieval contract's own evidence-id rule, so a derived key can never
be rejected later — and never be mistaken for a database record id.

Two independent bounds, both explicit. A revision's bytes are bounded by
``ingestion.MAX_UPLOAD_BYTES`` (8 MiB), and its span count by
:data:`MAX_SPANS_PER_REVISION`. Neither implies the other: a document well inside
the byte bound can still have more than 2000 paragraphs, which is a capacity
refusal (:class:`EvidenceSpanLimitExceededError`, HTTP 413), not a malformed
request.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from ..ledger.errors import (
    EvidenceLedgerContractError,
    EvidenceSpanLimitExceededError,
    InvalidEvidenceRequestError,
    UnsupportedMediaTypeError,
)
from ..retrieval.contracts import MAX_CITATION_CHARS, is_valid_evidence_id
from ..text_safety import remove_unsafe_chars

MAX_SPAN_CHARS = 2000
MIN_SPAN_CHARS = 1
MAX_SPANS_PER_REVISION = 2000
MAX_SOURCE_KEY_CHARS = 200
MAX_DISPLAY_TITLE_CHARS = 300

_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")
_SOURCE_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,199}$")


@dataclass(frozen=True, slots=True)
class DerivedSpan:
    """One ordered, citable span of a revision's normalized text."""

    span_ordinal: int
    char_start: int
    char_end: int
    text: str
    # Headings above the span, for Markdown and AsciiDoc (``text_outline.py``); the enclosing
    # symbols (class, method) for code (``code/chunking.py``); empty otherwise.
    section_path: tuple[str, ...] = ()
    # 1-based, inclusive line range of a code span (``#L<start>-L<end>``); ``None`` for prose.
    line_start: int | None = None
    line_end: int | None = None

    def __post_init__(self) -> None:
        if type(self.span_ordinal) is not int or self.span_ordinal < 1:
            raise EvidenceLedgerContractError()
        if type(self.char_start) is not int or type(self.char_end) is not int:
            raise EvidenceLedgerContractError()
        if not 0 <= self.char_start < self.char_end:
            raise EvidenceLedgerContractError()
        if type(self.text) is not str or not MIN_SPAN_CHARS <= len(self.text) <= MAX_SPAN_CHARS:
            raise EvidenceLedgerContractError()
        if (self.line_start is None) != (self.line_end is None):
            raise EvidenceLedgerContractError()
        if self.line_start is not None and not (
            type(self.line_start) is int and type(self.line_end) is int and 1 <= self.line_start <= self.line_end
        ):
            raise EvidenceLedgerContractError()


def new_revision_id() -> str:
    """A revision id whose hex can never look like a database record id.

    ``<hex>:<ordinal>`` would match the record-id shape if the hex happened to be
    all decimal digits, which the retrieval contract rejects. Regenerating is
    cheaper than special-casing the key format.
    """
    while True:
        candidate = uuid.uuid4()
        if not candidate.hex.isdigit():
            return str(candidate)


def normalize_source_key(raw: object) -> str:
    """Validate the Workspace-stable document key. Never a path or a file name."""
    if type(raw) is not str:
        raise InvalidEvidenceRequestError()
    key = raw.strip().lower()
    if not key or len(key) > MAX_SOURCE_KEY_CHARS or not _SOURCE_KEY.fullmatch(key):
        raise InvalidEvidenceRequestError()
    return key


def normalize_display_title(raw: object) -> str:
    """Validate the human-facing title; unsafe characters are refused, not stripped."""
    if type(raw) is not str:
        raise InvalidEvidenceRequestError()
    title = " ".join(raw.split())
    if not title or len(title) > MAX_DISPLAY_TITLE_CHARS:
        raise InvalidEvidenceRequestError()
    if remove_unsafe_chars(title, allow_line_breaks=False) != title:
        raise InvalidEvidenceRequestError()
    return title


def decode_text(data: bytes) -> str:
    """Strict UTF-8 decode plus one normalization pass. No lenient fallback."""
    if type(data) is not bytes or not data:
        raise InvalidEvidenceRequestError()
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        # Not text-native after all: the sandboxed parser owns these bytes.
        raise UnsupportedMediaTypeError() from None
    normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
    text = remove_unsafe_chars(normalized, allow_line_breaks=True)
    if not text.strip():
        raise InvalidEvidenceRequestError()
    return text


def derive_evidence_key(revision_id: str, span_ordinal: int) -> str:
    """``<revision_id_hex>:<span_ordinal>``, validated against the retrieval contract."""
    if type(revision_id) is not str or type(span_ordinal) is not int or span_ordinal < 1:
        raise EvidenceLedgerContractError()
    try:
        hex_form = uuid.UUID(revision_id).hex
    except (AttributeError, TypeError, ValueError):
        raise EvidenceLedgerContractError() from None
    key = f"{hex_form}:{span_ordinal}"
    if not is_valid_evidence_id(key):
        raise EvidenceLedgerContractError()
    return key


def derive_citation(display_title: str, revision_ordinal: int, span: DerivedSpan) -> str:
    """A fixed-shape, human-readable citation of exactly one span."""
    if type(revision_ordinal) is not int or revision_ordinal < 1:
        raise EvidenceLedgerContractError()
    if type(span) is not DerivedSpan:
        raise EvidenceLedgerContractError()
    title = normalize_display_title(display_title)
    section = f", § {span.section_path[-1][:120].rstrip()}" if span.section_path else ""
    if span.line_start is not None:
        where = f"lines {span.line_start}-{span.line_end}"
    else:
        where = f"chars {span.char_start}-{span.char_end}"
    suffix = f" (rev {revision_ordinal}, {where}{section})"
    # The title is truncated, never the structural suffix, so a citation always
    # names the revision and the character range it resolves to.
    room = MAX_CITATION_CHARS - len(suffix)
    if room < 1:
        raise EvidenceLedgerContractError()
    return f"{title[:room].rstrip()}{suffix}"


def derive_located_citation(
    display_title: str,
    revision_ordinal: int,
    *,
    page_start: int | None,
    page_end: int | None,
    section: str | None,
) -> str:
    """The citation of a parsed span: revision, pages, and the nearest heading."""
    if type(revision_ordinal) is not int or revision_ordinal < 1:
        raise EvidenceLedgerContractError()
    title = normalize_display_title(display_title)
    parts = [f"rev {revision_ordinal}"]
    if page_start is not None:
        parts.append(f"p. {page_start}" if page_end in (None, page_start) else f"pp. {page_start}-{page_end}")
    if section:
        parts.append(f"§ {section[:120].rstrip()}")
    suffix = f" ({', '.join(parts)})"
    room = MAX_CITATION_CHARS - len(suffix)
    if room < 1:
        raise EvidenceLedgerContractError()
    return f"{title[:room].rstrip()}{suffix}"


def _wrapped(paragraph: str, offset: int) -> list[tuple[int, int, str]]:
    """Split one over-long paragraph at whitespace, keeping absolute offsets."""
    pieces: list[tuple[int, int, str]] = []
    position = 0
    while position < len(paragraph):
        remaining = paragraph[position:]
        if len(remaining) <= MAX_SPAN_CHARS:
            chunk = remaining
        else:
            window = remaining[:MAX_SPAN_CHARS]
            cut = window.rfind(" ")
            # A paragraph with no space inside the window is cut at the bound; a
            # deterministic hard cut beats an unbounded span.
            chunk = window[:cut] if cut > 0 else window
        start = offset + position
        stripped = chunk.strip()
        if stripped:
            pieces.append((start, start + len(chunk), stripped))
        position += len(chunk)
        # Skip the separator the cut consumed, so offsets stay monotonic.
        while position < len(paragraph) and paragraph[position] == " ":
            position += 1
    return pieces


def paragraph_pieces(text: str) -> list[tuple[int, int, str]]:
    """``(char_start, char_end, text)`` of every bounded paragraph piece, in order."""
    if type(text) is not str or not text.strip():
        raise InvalidEvidenceRequestError()
    pieces: list[tuple[int, int, str]] = []
    position = 0
    for paragraph in _PARAGRAPH_BREAK.split(text):
        start = text.find(paragraph, position)
        if start < 0:  # pragma: no cover - split pieces are always present
            raise EvidenceLedgerContractError()
        position = start + len(paragraph)
        pieces.extend(_wrapped(paragraph, start))
    return pieces


def derive_spans(text: str) -> tuple[DerivedSpan, ...]:
    """Split normalized text into ordered, bounded spans. Deterministic."""
    spans: list[DerivedSpan] = []
    for char_start, char_end, chunk in paragraph_pieces(text):
        if len(spans) >= MAX_SPANS_PER_REVISION:
            # A capacity limit on valid text, not malformed input: the caller
            # has to split the document, so this must not read as a 400.
            raise EvidenceSpanLimitExceededError()
        spans.append(DerivedSpan(span_ordinal=len(spans) + 1, char_start=char_start, char_end=char_end, text=chunk))
    if not spans:
        raise InvalidEvidenceRequestError()
    return tuple(spans)
