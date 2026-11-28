"""Which catalog icon belongs on a topic: a closed synonym vocabulary."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

#: Closed topic vocabulary. Key -> ordered synonyms; the order is the
#: preference. The keys are the deck's own section/column keys, not free text —
#: an unknown key gets no icon, never an approximated one.
TOPIC_SYNONYMS: dict[str, tuple[str, ...]] = {
    # the five resource themes of the AWS deck
    "network": ("network", "connectivity", "globe", "internet", "cloud", "wifi"),
    "compute": ("server", "cog", "computer", "compute", "cpu", "processor", "chip"),
    "data": ("database", "folder", "server", "data", "storage", "disk"),
    "security": ("shield", "lock", "fingerprint", "security", "padlock", "key"),
    "integration": ("cog", "connectivity", "integration", "gear", "puzzle", "plug", "api"),
    # the three columns of the "survey in three numbers" slide
    "resource_types": ("chart", "line", "server", "resource", "layer", "stack"),
    "services": ("cog", "server", "service", "gear", "setting"),
    "regions": ("globe", "location", "map", "region", "world", "earth", "pin"),
}

#: Icon fields whose text names the icon itself. The category is deliberately
#: absent: every icon of an "Icons Security" slide would otherwise answer to
#: ``security``, whatever it shows.
_NAME_FIELDS = ("slug", "name", "alt_text", "file_name")

_SPLIT = re.compile(r"[^a-z0-9]+")


def _tokens(values: Iterable[str]) -> set[str]:
    words: set[str] = set()
    for value in values:
        for token in _SPLIT.split(str(value or "").lower()):
            if len(token) < 2 or token.isdigit():
                continue
            words.add(token)
            if len(token) > 3 and token.endswith("s"):
                words.add(token[:-1])
    return words


def icon_words(icon: dict[str, Any]) -> frozenset[str]:
    category_words = _tokens([str(icon.get("category") or ""), str(icon.get("category_key") or "")])
    tags = [tag for tag in (icon.get("tags") or ()) if isinstance(tag, str)]
    words = _tokens([str(icon.get(field) or "") for field in _NAME_FIELDS])
    words |= _tokens(tags) - category_words
    return frozenset(words)


def match_topic_icon(icons: Iterable[Any], topic_key: str) -> dict[str, Any] | None:
    synonyms = TOPIC_SYNONYMS.get(str(topic_key or "").strip().lower())
    if not synonyms:
        return None
    indexed = [
        (icon, icon_words(icon))
        for icon in icons
        if isinstance(icon, dict) and icon.get("part")
    ]
    for word in synonyms:
        for icon, words in indexed:
            if word in words:
                return icon
    return None


__all__ = ["TOPIC_SYNONYMS", "icon_words", "match_topic_icon"]
