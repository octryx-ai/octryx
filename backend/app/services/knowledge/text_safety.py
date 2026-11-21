"""Character safety rules for text crossing the Knowledge retrieval contract.

Query text, evidence text, and citations reach models and user interfaces, so
invisible, reordering, or meaning-free characters must not pass:

- C0/C1 controls (``Cc``), bidi and other format characters (``Cf``, e.g.
  U+202E, U+200B, or the tag block), lone surrogates (``Cs``), private-use
  characters (``Co``), and the line and paragraph separators (``Zl``/``Zp``);
- variation selectors U+FE00-U+FE0F and U+E0100-U+E01EF;
- the Hangul fillers U+115F, U+1160, U+3164, and U+FFA0, which render blank;
- Unicode noncharacters: U+FDD0-U+FDEF and every code point ending in FFFE or
  FFFF.

Ordinary letters and combining marks of any script pass. Body text may keep
tab, line feed, and carriage return.
"""

from __future__ import annotations

import unicodedata

_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Zl", "Zp"})
_LINE_BREAKS = frozenset({"\t", "\n", "\r"})
_HANGUL_FILLERS = frozenset({"ᅟ", "ᅠ", "ㅤ", "ﾠ"})


def _is_unsafe_code_point(code_point: int) -> bool:
    return (
        0xFE00 <= code_point <= 0xFE0F  # variation selectors
        or 0xE0100 <= code_point <= 0xE01EF  # variation selectors supplement
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
    """Drop unsafe characters; for adapters mapping untrusted external content."""
    return "".join(char for char in text if not is_unsafe_char(char, allow_line_breaks=allow_line_breaks))
