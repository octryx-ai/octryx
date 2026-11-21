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
    """Whether a value carries credentials in its authority (``user[:pass]@host``), under any scheme or none.

    Deliberately wider than a URL parser: an optional scheme, then any run of slashes or backslashes
    (``https://``, scheme-relative ``//``, ``https:`` plus backslashes, or none), then the authority up to
    the first slash, backslash, ``?`` or ``#``. Any ``@`` there is userinfo. A scheme-less ``user:pass@host``
    matches too: its ``user:`` reads as a scheme and ``pass@host`` is the authority.

    The value is first NFKC-normalized and every whitespace, control and format character is removed, so
    ``ht\\ttps://u:p@…``, ``https:\\t//…``, ``https: //…``, a full-width ``＠`` or a zero-width space cannot
    hide the userinfo from the check.
    """
    if not isinstance(value, str):
        return False
    rest = _SCHEME.sub("", _compact(value), count=1).lstrip("/\\")
    return "@" in _AUTHORITY_END.split(rest, maxsplit=1)[0]
