"""Masking of findings with placeholders: one-way, deterministic, numbered per conversation.

The model only sees placeholders such as ``[EMAIL #1]``. ``#n`` comes from a :class:`Masker`:
the same value gets the same number, so the model can tell two values apart; a masker is built for one request
and numbers values in the order they first appear. Every call carries the whole conversation in the same
order, so history is masked identically on every call (prompt caching stays stable) and nothing is stored
between calls. The masker keys values by an HMAC with a key that lives as long as the masker, never by the value.

There is no vault and no unmasking. Styles (``vocabulary.MASK_STYLES``):

- ``last4`` ``[PHONE ********1234 #1]``, ``type_token`` ``[EMAIL #2]``, ``country_last4`` ``[IBAN DE…3000]``,
  ``full`` (the token alone, no number).

A style a detector does not offer falls back to the detector's first style. A placeholder never matches a detector
again, so a masked text re-scans clean.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable
from dataclasses import dataclass

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


class Masker:
    """Placeholder numbering for one request (see the module doc)."""

    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)
        self._numbers: dict[bytes, int] = {}

    def number(self, token: str, normalized: str) -> int:
        digest = hmac.new(self._key, f"{token}\x00{normalized}".encode(), hashlib.sha256).digest()
        if digest not in self._numbers:
            self._numbers[digest] = len(self._numbers) + 1
        return self._numbers[digest]

    def placeholder(self, info: DetectorInfo, value: str, style: str) -> str:
        normalized = _normalized(info.id, value)
        token = info.token
        if style == MASK_FULL:
            return f"[{token}]"
        if style == MASK_COUNTRY_LAST4 and len(normalized) > 6:
            return f"[{token} {normalized[:2]}…{normalized[-4:]}]"
        number = self.number(token, normalized)
        if style == MASK_LAST4 and len(normalized) > 4:
            return f"[{token} {'*' * (len(normalized) - 4)}{normalized[-4:]} #{number}]"
        return f"[{token} #{number}]"


#: What replaces a text whose scan could not finish (``Examination.finished`` false): it is never sent, released or
#: shown as checked.
WITHHELD_TEXT = "[WITHHELD: content not fully scanned]"


@dataclass(frozen=True, slots=True)
class MaskResult:
    text: str
    masked: int
    detectors: tuple[str, ...] = ()


def mask_text(text: str, findings: Iterable[Finding], *, detectors: DetectorSet, mask: frozenset[str],
              style: str | None, masker: Masker) -> MaskResult:
    """``text`` with every finding of a detector in ``mask`` replaced; ``style`` as the policy asked."""
    chosen = non_overlapping([item for item in findings if item.detector in mask])
    if not chosen:
        return MaskResult(text, 0)
    parts: list[str] = []
    position = 0
    used: set[str] = set()
    for finding in chosen:
        info = detectors.info(finding.detector)
        if info is None:
            continue
        parts.append(text[position:finding.start])
        parts.append(masker.placeholder(info, text[finding.start:finding.end], resolve_style(info, style)))
        position = finding.end
        used.add(finding.detector)
    parts.append(text[position:])
    masked = sum(1 for item in chosen if item.detector in used)
    return MaskResult("".join(parts), masked, tuple(sorted(used)))


__all__ = [
    "WITHHELD_TEXT",
    "MaskResult",
    "Masker",
    "mask_text",
    "resolve_style",
]
