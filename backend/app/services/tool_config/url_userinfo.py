"""Detect credentials written into a URL's authority (``user[:pass]@host``)."""

from __future__ import annotations

import re
import unicodedata

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_AUTHORITY_END = re.compile(r"[/\\?#]")


def _compact(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    return "".join(ch for ch in text if not (ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf")))


def carries_userinfo(value: object) -> bool:
    if not isinstance(value, str):
        return False
    rest = _SCHEME.sub("", _compact(value), count=1).lstrip("/\\")
    return "@" in _AUTHORITY_END.split(rest, maxsplit=1)[0]
