"""Character safety rules for text crossing the Knowledge retrieval contract. Invisible, reordering or meaning-free
characters must not pass."""

from __future__ import annotations

import unicodedata

_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Zl", "Zp"})
_LINE_BREAKS = frozenset({"\t", "\n", "\r"})
_HANGUL_FILLERS = frozenset({"ᅟ", "ᅠ", "ㅤ", "ﾠ"})


def _is_unsafe_code_point(code_point: int) -> bool:
    return (
        0xFE00 <= code_point <= 0xFE0F  # variation selectors
        or 0xE0100 <= code_point <= 0xE01EF
        or 0xFDD0 <= code_point <= 0xFDEF  # noncharacter block
        or (code_point & 0xFFFE) == 0xFFFE  # U+nFFFE and U+nFFFF noncharacters
    )


def is_unsafe_char(char: str, *, allow_line_breaks: bool) -> bool:
    if allow_line_breaks and char in _LINE_BREAKS:
        return False
    return (
        unicodedata.category(char) in _UNSAFE_CATEGORIES or char in _HANGUL_FILLERS or _is_unsafe_code_point(ord(char))
    )


def has_unsafe_chars(text: str, *, allow_line_breaks: bool) -> bool:
    return any(is_unsafe_char(char, allow_line_breaks=allow_line_breaks) for char in text)


def remove_unsafe_chars(text: str, *, allow_line_breaks: bool) -> str:
    return "".join(char for char in text if not is_unsafe_char(char, allow_line_breaks=allow_line_breaks))
