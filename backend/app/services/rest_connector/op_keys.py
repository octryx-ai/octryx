"""Readable, stable operation keys for imported operations, also when the spec has no ``operationId``.

SAP Business Accelerator Hub specs (e.g. Business Partner A2X) carry no ``operationId`` at all, and a key derived
from ``method + path`` and cut at 32 characters reads ``get_a_business_partner_business``,
``patch_a_business_partner_busines``. The full spec has hundreds of operations under ``/A_BusinessPartner...`` and
``/A_BusinessPartnerAddress(...)/to_...``, so a cut key collides or says nothing.

A derived key is built from the method and the meaningful path parts: the entity set or resource, ``by_key`` for an
OData key predicate ``(...)`` or ``by_<name>`` for a ``{name}`` segment, and the navigation (``to_EmailAddress``).
When that is longer than 32 characters (the tool-name budget, ``common``), it is shortened step by step: an
intermediate key part is left out and a long intermediate name is abbreviated to its initials plus its last word
(``a_business_partner_address`` -> ``abp_address``), then the navigation prefix ``to_`` is dropped, then the last
part is abbreviated too; if it is still too long, the end is kept (the navigation is what tells two operations of
one entity apart) and a short hash of method and path is added. A collision within one
definition gets the same hash suffix, so the key depends only on its own method and path, never on import order.

Keys are computed at import only; a stored operation keeps its ``op_key`` (tool names and grants refer to it).
"""

from __future__ import annotations

import hashlib
import re

from .common import snake_case

MAX_KEY = 32
HASH_LEN = 6
_PREDICATE = re.compile(r"^(?P<name>[^(]*)\((?P<keys>.*)\)$")
_PLACEHOLDER = re.compile(r"^\{(?P<name>[^}]+)\}$")
_NO_LIMIT = 10_000


def _hash(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:HASH_LEN]


def _snake(text: str) -> str:
    return snake_case(text, limit=_NO_LIMIT)


def _parts(path: str) -> list[str]:
    """The path as key parts; a key part (``by_...``) is marked by its prefix."""
    parts: list[str] = []
    for segment in str(path or "").split("/"):
        segment = segment.strip()
        if not segment:
            continue
        placeholder = _PLACEHOLDER.match(segment)
        if placeholder:
            parts.append(f"by_{_snake(placeholder.group('name'))}")
            continue
        predicate = _PREDICATE.match(segment)
        if predicate:
            if predicate.group("name"):
                parts.append(_snake(predicate.group("name")))
            parts.append("by_key")
            continue
        parts.append(_snake(segment.lstrip("$")))
    return parts


def _abbreviated(part: str) -> str:
    words = part.split("_")
    if len(words) < 3:
        return part
    return "".join(word[0] for word in words[:-1]) + "_" + words[-1]


def _shortenings(parts: list[str]) -> list[list[str]]:
    """Ever shorter forms: intermediate key parts dropped and intermediate names abbreviated, then the navigation
    prefix ``to_`` of the last part dropped, then the last part abbreviated too."""
    if not parts:
        return []
    middle = [_abbreviated(part) for part in parts[:-1] if not part.startswith("by_")]
    last = parts[-1]
    bare = last[3:] if last.startswith("to_") and len(last) > 3 else last
    return [[*middle, last], [*middle, bare], [*middle, _abbreviated(bare)]]


def _with_hash(prefix: str, body: str, digest: str) -> str:
    """``prefix_<end of body>_<hash>`` within the limit: the end of ``body`` is kept, cut at a word boundary."""
    budget = MAX_KEY - len(prefix) - len(digest) - 2
    words = [word for word in body.split("_") if word]
    kept: list[str] = []
    for word in reversed(words):
        if len("_".join([word, *kept])) > budget:
            break
        kept.insert(0, word)
    middle = "_".join(kept)
    return "_".join(item for item in (prefix, middle, digest) if item)


def derived_key(method: str, path: str) -> str:
    """The key of an operation without ``operationId``: method plus meaningful path parts, at most 32 characters."""
    verb = str(method or "get").lower()
    parts = _parts(path)
    full = "_".join([verb, *parts])
    if len(full) <= MAX_KEY:
        return full
    forms = _shortenings(parts)
    for form in forms:
        short = "_".join([verb, *form])
        if len(short) <= MAX_KEY:
            return short
    return _with_hash(verb, "_".join(forms[0]) if forms else "", _hash(verb, str(path)))


def key_from_operation_id(operation_id: str) -> str:
    """The snake-case ``operationId``; a long one keeps its start (the verb) and gets a hash suffix."""
    full = _snake(operation_id)
    if len(full) <= MAX_KEY:
        return full
    return f"{full[: MAX_KEY - HASH_LEN - 1].rstrip('_')}_{_hash(str(operation_id))}"


def unique_key(base: str, method: str, path: str, taken: set[str]) -> str:
    """``base``, or on a collision the same key with the hash of its own method and path, else a counter."""
    key = base
    if key in taken:
        digest = _hash(str(method).lower(), str(path))
        key = base if len(base) + HASH_LEN + 1 <= MAX_KEY else base[: MAX_KEY - HASH_LEN - 1].rstrip("_")
        key = f"{key}_{digest}"
    counter = 2
    stem = key
    while key in taken:
        suffix = f"_{counter}"
        key = f"{stem[: MAX_KEY - len(suffix)]}{suffix}"
        counter += 1
    taken.add(key)
    return key


__all__ = ["MAX_KEY", "derived_key", "key_from_operation_id", "unique_key"]
