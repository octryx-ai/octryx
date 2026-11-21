"""A correction's signature: redacted first, then normalised, so the same mistake gives the same key. Pure.

a signature never holds a secret or a person's name. ``redact`` runs before anything is
normalised or stored (the platform's secret redaction, the data's token patterns, then the names of the Workspace's
people); ``normalise`` then drops what differs between two occurrences of one mistake (paths, files, numbers,
quoted text, identifiers) and keeps the words that say what was wrong.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any


@lru_cache(maxsize=1)
def data() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("corrections.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _redact_patterns() -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern) for pattern in data()["redact"]["patterns"])


@lru_cache(maxsize=1)
def _normalise_rules() -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple((re.compile(rule["pattern"]), rule["replace"]) for rule in data()["normalise"]["rules"])


def name_parts(people: Iterable[Any]) -> tuple[str, ...]:
    """The words that name the given people: display name parts, user names and e-mail local parts (at least
    ``min_name`` letters), longest first so a full name goes before its parts."""
    shortest = int(data()["redact"]["min_name"])
    found: set[str] = set()
    for person in people:
        if isinstance(person, str):
            values = [person]
        else:
            email = str(getattr(person, "email", "") or "")
            values = [str(getattr(person, "display_name", "") or ""), str(getattr(person, "username", "") or ""),
                      email.split("@", 1)[0]]
        for value in values:
            value = value.strip()
            if len(value) >= shortest:
                found.add(value)
            found.update(part for part in re.split(r"[\s._\-]+", value) if len(part) >= shortest)
    return tuple(sorted(found, key=lambda item: (-len(item), item)))


def redact(text: Any, names: Iterable[str] = ()) -> str:
    """``text`` without secrets, e-mail addresses, @mentions and the given names."""
    from ...redaction_policy import redact_secret_text

    replacement = str(data()["redact"]["replacement"])
    value = redact_secret_text(str(text or ""))
    for pattern in _redact_patterns():
        value = pattern.sub(replacement, value)
    for name in names:
        value = re.sub(rf"(?<![\w]){re.escape(name)}(?![\w])", replacement, value, flags=re.IGNORECASE)
    return value


def normalise(text: str) -> str:
    """The shape of a (redacted) message: what was wrong, without where and with which names."""
    value = text
    for pattern, replacement in _normalise_rules():
        value = pattern.sub(replacement, value)
    return value.strip()[: int(data()["normalise"]["max_message"])]


def file_pattern(path: Any) -> str:
    """``shop/pricing/cart.py`` → ``shop/**/*.py``; a file at the root → ``*.py``; none → ``*``."""
    raw = str(path or "").strip().split(":", 1)[0].lstrip("./")
    if not raw or raw.startswith("("):
        return "*"
    pure = PurePosixPath(raw)
    suffix = pure.suffix
    folders = pure.parts[:-1][: int(data()["file_pattern"]["depth"])]
    name = f"*{suffix}" if suffix else "*"
    return f"{'/'.join(folders)}/**/{name}" if folders else name


def kind_hint(check_kind: str) -> str:
    hints = data()["kind_hints"]
    return str(hints.get(check_kind) or hints["default"])


def key(check_kind: str, pattern: str, message: str) -> str:
    return hashlib.sha256(f"{check_kind}\n{pattern}\n{message.lower()}".encode()).hexdigest()[:32]


def excerpt(text: Any, names: Iterable[str] = ()) -> str:
    """The occurrence's own words for the evidence, redacted and bounded (never normalised)."""
    return " ".join(redact(text, names).split())[: int(data()["max_excerpt"])]


__all__ = ["data", "excerpt", "file_pattern", "key", "kind_hint", "name_parts", "normalise", "redact"]
