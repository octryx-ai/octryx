"""The built-in detectors: RE2 finds candidates, validators decide.

Every candidate pattern runs on RE2 (linear time); the Python validators run only on candidates, and each
detector looks at no more than :data:`MAX_CANDIDATES` candidates per text (more marks the scan incomplete).

- ``iban``: country code, the per-country length and mod-97.
- ``email`` and ``phone`` (E.164, or a national number after tel/phone/mobile/fax): medium.
- ``secrets``: the gateway's secret scanner (``model_gateway/inbound/secret_scan``), high.
"""

from __future__ import annotations

from collections.abc import Callable

import re2

from ..model_gateway.inbound.secret_scan import secret_spans
from .findings import Finding
from .validators import IBAN_LENGTHS, iban_valid
from .vocabulary import (
    CATEGORY_PII,
    CATEGORY_SECRETS,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    DETECTOR_EMAIL,
    DETECTOR_IBAN,
    DETECTOR_PHONE,
    DETECTOR_SECRETS,
)

MAX_CANDIDATES = 5000


def _options() -> re2.Options:
    options = re2.Options()
    options.log_errors = False
    return options


_OPTIONS = _options()


def _compile(pattern: str):
    return re2.compile(pattern, _OPTIONS)


_IBAN = _compile(r"[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]){10,40}")
_EMAIL = _compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*"
    r"\.[A-Za-z]{2,24}"
)
_E164 = _compile(r"\+[1-9](?:[ -]?[0-9]){7,14}")
_PHONE_KEYWORD = _compile(r"(?i)\b(?:tel|phone|mobile|fax)\b\.?[ \t]*[:=#]?[ \t]*(\(?[0-9][0-9 ()/.-]{5,20}[0-9])")


class CandidateLimitError(Exception):
    """A text had more candidates than :data:`MAX_CANDIDATES`; the scan is incomplete."""


def _wordish(char: str) -> bool:
    return char.isalnum() or char == "_"


def _bounded(text: str, start: int, end: int) -> bool:
    return (start == 0 or not _wordish(text[start - 1])) and (end >= len(text) or not _wordish(text[end]))


def _matches(pattern, text: str):
    for count, match in enumerate(pattern.finditer(text)):
        if count >= MAX_CANDIDATES:
            raise CandidateLimitError()
        yield match


def _digits(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def _iban_end(text: str, start: int, length: int) -> int | None:
    """The end of an IBAN of ``length`` characters from ``start`` (single spaces allowed), else ``None``."""
    collected, index = 0, start
    while index < len(text) and collected < length:
        char = text[index]
        if char.isascii() and char.isalnum():
            collected += 1
        elif not (char == " " and collected and index + 1 < len(text) and text[index + 1] != " "):
            return None
        index += 1
    return index if collected == length else None


def find_iban(text: str) -> list[Finding]:
    found: list[Finding] = []
    for match in _matches(_IBAN, text):
        start = match.start()
        length = IBAN_LENGTHS.get(text[start:start + 2])
        if length is None or (start > 0 and _wordish(text[start - 1])):
            continue
        end = _iban_end(text, start, length)
        if end is None or (end < len(text) and _wordish(text[end])):
            continue
        if iban_valid(text[start:end].replace(" ", "")):
            found.append(Finding(DETECTOR_IBAN, CATEGORY_PII, CONFIDENCE_HIGH, start, end))
    return found


def find_email(text: str) -> list[Finding]:
    return [Finding(DETECTOR_EMAIL, CATEGORY_PII, CONFIDENCE_MEDIUM, match.start(), match.end())
            for match in _matches(_EMAIL, text) if match.end() >= len(text) or not _wordish(text[match.end()])]


def find_phone(text: str) -> list[Finding]:
    found: list[Finding] = []
    for match in _matches(_E164, text):
        if _bounded(text, match.start() + 1, match.end()) and (match.start() == 0 or not _wordish(
                text[match.start() - 1])):
            found.append(Finding(DETECTOR_PHONE, CATEGORY_PII, CONFIDENCE_MEDIUM, match.start(), match.end()))
    for match in _matches(_PHONE_KEYWORD, text):
        start, end = match.start(1), match.end(1)
        if 7 <= len(_digits(text[start:end])) <= 15 and (end >= len(text) or not text[end].isdigit()) and not any(
                item.start <= start < item.end for item in found):
            found.append(Finding(DETECTOR_PHONE, CATEGORY_PII, CONFIDENCE_MEDIUM, start, end))
    return found


def find_secrets(text: str) -> list[Finding]:
    return [Finding(DETECTOR_SECRETS, CATEGORY_SECRETS, CONFIDENCE_HIGH, start, end, kind)
            for kind, start, end in secret_spans(text)]


# Detectors that do not depend on another detector's findings, in the order they run.
INDEPENDENT: dict[str, Callable[[str], list[Finding]]] = {
    DETECTOR_IBAN: find_iban,
    DETECTOR_EMAIL: find_email,
    DETECTOR_PHONE: find_phone,
    DETECTOR_SECRETS: find_secrets,
}


def find_builtin(text: str, enabled: frozenset[str]) -> list[Finding]:
    """Every enabled built-in detector over ``text``; raises :class:`CandidateLimitError`."""
    found: list[Finding] = []
    for detector_id, finder in INDEPENDENT.items():
        if detector_id in enabled:
            found.extend(finder(text))
    return found


__all__ = [
    "INDEPENDENT",
    "MAX_CANDIDATES",
    "CandidateLimitError",
    "find_builtin",
    "find_email",
    "find_iban",
    "find_phone",
    "find_secrets",
]
