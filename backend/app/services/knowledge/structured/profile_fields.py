"""Field validators of a structured profile document, one per kind of value."""

from __future__ import annotations

import re
from typing import Any

from .profile_patterns import ProfilePattern, UnsafePatternError, UnsupportedPatternError, check_pattern
from .profile_types import (
    FILE_FORMATS,
    RELATIONS,
    Component,
    ConfigFileRule,
    ReferencePattern,
    StructuredProfileError,
    fold,
)

_LINE_PREFIX = re.compile(r"[^\w\s]{1,3}")


def _fields(raw: object, expected: frozenset[str], what: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != expected:
        raise StructuredProfileError(f"structured profile: {what} must have exactly the fields {sorted(expected)}")
    return raw


def _strings(raw: object, what: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise StructuredProfileError(f"structured profile: {what} must be a list of non-empty strings")
    return tuple(raw)


def _patterns(raw: object, what: str) -> tuple[ProfilePattern, ...]:
    try:
        return tuple(check_pattern(item) for item in _strings(raw, what))
    except re.error:
        raise StructuredProfileError(f"structured profile: {what} has a pattern that does not compile") from None
    except UnsafePatternError:
        raise StructuredProfileError(
            f"structured profile: {what} has a pattern that is too long or could backtrack without bound"
        ) from None
    except UnsupportedPatternError:
        raise StructuredProfileError(
            f"structured profile: {what} has a pattern the linear-time engine (RE2) does not support"
        ) from None


def _grouped(raw: object, group: str, what: str) -> ProfilePattern:
    pattern = _patterns([raw], what)[0]
    if group not in pattern.groupindex:
        raise StructuredProfileError(f"structured profile: {what} must have the named group {group!r}")
    return pattern


def _flag(raw: object, what: str) -> bool:
    if type(raw) is not bool:
        raise StructuredProfileError(f"structured profile: {what} must be a boolean")
    return raw


def _bounded(raw: object, low: int, high: int, what: str) -> int:
    if type(raw) is not int or not low <= raw <= high:
        raise StructuredProfileError(f"structured profile: {what} must be an integer from {low} to {high}")
    return raw


def _config_files(raw: object) -> tuple[ConfigFileRule, ...]:
    if not isinstance(raw, list) or not raw:
        raise StructuredProfileError("structured profile: configuration files must be a non-empty list")
    rules = []
    for item in raw:
        item = _fields(item, frozenset({"glob", "format", "manual_documented"}), "a configuration file rule")
        if not isinstance(item["glob"], str) or item["format"] not in FILE_FORMATS:
            raise StructuredProfileError("structured profile: a file rule needs a glob and a known format")
        if type(item["manual_documented"]) is not bool:
            raise StructuredProfileError("structured profile: manual_documented must be a boolean")
        rules.append(ConfigFileRule(item["glob"], item["format"], item["manual_documented"]))
    return tuple(rules)


def _components(raw: object) -> tuple[Component, ...]:
    if not isinstance(raw, list) or not raw:
        raise StructuredProfileError("structured profile: components must be a non-empty list")
    items = []
    for item in raw:
        item = _fields(item, frozenset({"name", "relation"}), "a component")
        if not isinstance(item["name"], str) or not fold(item["name"]) or item["relation"] not in RELATIONS:
            raise StructuredProfileError("structured profile: a component needs a name and requires/supports")
        items.append(Component(item["name"], item["relation"]))
    if len({item.folded for item in items}) != len(items):
        raise StructuredProfileError("structured profile: a component is listed twice")
    return tuple(items)


def _line_prefixes(raw: object, what: str) -> tuple[str, ...]:
    # A prefix that may contain letters (``password=``) would fold a secret line into a comment or
    # into the previous value, past the per-key redaction: only 1-3 punctuation characters.
    prefixes = _strings(raw, what)
    if not all(_LINE_PREFIX.fullmatch(prefix) for prefix in prefixes):
        raise StructuredProfileError(f"structured profile: {what} must be 1 to 3 punctuation characters each")
    return prefixes


def _comment_prefixes(raw: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, dict) or set(raw) != FILE_FORMATS:
        raise StructuredProfileError(f"structured profile: comment_prefixes must name exactly {sorted(FILE_FORMATS)}")
    return {fmt: _line_prefixes(raw[fmt], f"comment_prefixes of {fmt}") for fmt in sorted(raw)}


def _variant_patterns(raw: object) -> tuple[ProfilePattern, ...]:
    patterns = _patterns(raw, "variant_patterns")
    if not all({"base", "variant"} <= set(pattern.groupindex) for pattern in patterns):
        raise StructuredProfileError("structured profile: a variant pattern needs the named groups base and variant")
    return patterns


def _references(raw: object) -> tuple[ReferencePattern, ...]:
    if not isinstance(raw, list):
        raise StructuredProfileError("structured profile: reference_patterns must be a list")
    items = []
    for item in raw:
        item = _fields(item, frozenset({"kind", "pattern"}), "a reference pattern")
        if item["kind"] not in ("section", "named_page", "page"):
            raise StructuredProfileError("structured profile: a reference kind is unknown")
        items.append(ReferencePattern(item["kind"], _patterns([item["pattern"]], "a reference pattern")[0]))
    return tuple(items)
