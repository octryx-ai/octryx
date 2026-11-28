"""Masking of findings with one-way placeholders, numbered per request."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import NamedTuple

from .findings import Finding, non_overlapping
from .scanner import DetectorSet
from .vocabulary import DETECTOR_EMAIL, DETECTOR_IBAN, MASK_COUNTRY_LAST4, MASK_FULL, MASK_LAST4, DetectorInfo


def _normalized(detector: str, value: str) -> str:
    if detector == DETECTOR_EMAIL:
        return value.lower()
    if detector == DETECTOR_IBAN:
        return value.replace(" ", "").upper()
    digits = "".join(char for char in value if char.isdigit())
    return digits if len(digits) >= 4 else "".join(char for char in value if char.isalnum())


def resolve_style(info: DetectorInfo, requested: str | None) -> str:
    if requested in info.mask_styles:
        return str(requested)
    return info.default_mask_style


class Piece(NamedTuple):
    text: str
    generated: bool = True


# One-way: an HMAC under a key that lives as long as the masker numbers values per request; there is no vault and no
# unmasking.
class Masker:
    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)
        self._numbers: dict[bytes, int] = {}

    def number(self, token: str, normalized: str) -> int:
        digest = hmac.new(self._key, f"{token}\x00{normalized}".encode(), hashlib.sha256).digest()
        if digest not in self._numbers:
            self._numbers[digest] = len(self._numbers) + 1
        return self._numbers[digest]

    def pieces(self, info: DetectorInfo, value: str, style: str) -> tuple[Piece, ...]:
        normalized = _normalized(info.id, value)
        token = info.token
        if style == MASK_FULL:
            return (Piece(f"[{token}]"),)
        if style == MASK_COUNTRY_LAST4 and len(normalized) > 6:
            return (Piece(f"[{token} "), Piece(normalized[:2], generated=False), Piece("…"),
                    Piece(normalized[-4:], generated=False), Piece("]"))
        number = self.number(token, normalized)
        if style == MASK_LAST4 and len(normalized) > 4:
            return (Piece(f"[{token} {'*' * (len(normalized) - 4)}"), Piece(normalized[-4:], generated=False),
                    Piece(f" #{number}]"))
        return (Piece(f"[{token} #{number}]"),)

    def placeholder(self, info: DetectorInfo, value: str, style: str) -> str:
        return "".join(piece.text for piece in self.pieces(info, value, style))


#: What replaces a text whose scan could not finish (``Examination.finished`` false): it is never sent, released or
#: shown as checked.
WITHHELD_TEXT = "[WITHHELD: content not fully scanned]"


# A half-open [start, end) range of masker-generated characters in one masked text, never retained input. A rescan
# may ignore findings inside one: only the masker makes spans, for its own output object, so no input can add one.
Span = tuple[int, int]


@dataclass(frozen=True, slots=True)
class MaskResult:
    text: str
    masked: int
    detectors: tuple[str, ...] = ()
    generated: tuple[Span, ...] = ()


class PlaceholderSpans:
    def __init__(self) -> None:
        self._spans: dict[int, tuple[str, list[int], tuple[Span, ...]]] = {}

    def add(self, result: MaskResult) -> None:
        if result.generated:
            starts = [start for start, _end in result.generated]
            self._spans[id(result.text)] = (result.text, starts, result.generated)

    def covers(self, text: str | None, finding: Finding) -> bool:
        entry = self._spans.get(id(text))
        if entry is None or entry[0] is not text:
            return False
        _text, starts, spans = entry
        index = bisect_right(starts, finding.start) - 1
        return index >= 0 and finding.end <= spans[index][1]

    def outside(self, text: str | None, findings: Iterable[Finding],
                expired: Callable[[], bool]) -> tuple[Finding, ...] | None:
        kept: list[Finding] = []
        for finding in findings:
            if expired():
                return None
            if not self.covers(text, finding):
                kept.append(finding)
        return tuple(kept)


def mask_text(text: str, findings: Iterable[Finding], *, detectors: DetectorSet, mask: frozenset[str],
              style: str | None, masker: Masker) -> MaskResult:
    chosen = non_overlapping([item for item in findings if item.detector in mask])
    if not chosen:
        return MaskResult(text, 0)
    parts: list[str] = []
    spans: list[Span] = []
    position = length = 0
    used: set[str] = set()
    for finding in chosen:
        info = detectors.info(finding.detector)
        if info is None:
            continue
        kept = text[position:finding.start]
        parts.append(kept)
        length += len(kept)
        for piece, generated in masker.pieces(info, text[finding.start:finding.end], resolve_style(info, style)):
            parts.append(piece)
            if generated:
                spans.append((length, length + len(piece)))
            length += len(piece)
        position = finding.end
        used.add(finding.detector)
    parts.append(text[position:])
    masked = sum(1 for item in chosen if item.detector in used)
    return MaskResult("".join(parts), masked, tuple(sorted(used)), tuple(spans))


__all__ = [
    "WITHHELD_TEXT",
    "MaskResult",
    "Masker",
    "Piece",
    "PlaceholderSpans",
    "Span",
    "mask_text",
    "resolve_style",
]
