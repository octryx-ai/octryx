"""Validation of a custom detector set: every rule refuses with an issue, never silently drops."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..knowledge.structured.profile_patterns import (
    MAX_PATTERN_CHARS,
    UnsafePatternError,
    UnsupportedPatternError,
    check_pattern,
)
from .custom_definitions import (
    _FIELDS,
    CHECK_NONE,
    CHECKS,
    EMPTY_DEFINITIONS,
    ERROR_INVALID,
    ISSUE_CATEGORY,
    ISSUE_CATEGORY_ID,
    ISSUE_CHECK,
    ISSUE_CONTEXT,
    ISSUE_DUPLICATE,
    ISSUE_ID,
    ISSUE_LABEL,
    ISSUE_MASK,
    ISSUE_PATTERN_EMPTY,
    ISSUE_PATTERN_LONG,
    ISSUE_PATTERN_SYNTAX,
    ISSUE_PATTERN_UNSAFE,
    ISSUE_PATTERN_UNSUPPORTED,
    ISSUE_SCOPE,
    ISSUE_SHAPE,
    ISSUE_TOO_MANY,
    MAX_CATEGORIES,
    MAX_CONTEXT_WORD_CHARS,
    MAX_CONTEXT_WORDS,
    MAX_DETECTORS,
    MAX_LABEL_CHARS,
    SLUG,
    CustomDetectorDefinition,
    DetectorDefinitions,
    DetectorSetError,
)
from .vocabulary import BUILTIN_CATEGORY_IDS, CUSTOM_MASK_STYLES, CUSTOM_PREFIX, MASK_TYPE_TOKEN, Category


def _issue(target: str, code: str, message: str) -> dict[str, str]:
    return {"detector_id": target, "code": code, "message": message}


def _text(value: Any, limit: int) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text if 0 < len(text) <= limit and "\n" not in text else None


def _categories(raw: Any, issues: list[dict[str, str]]) -> list[Category]:
    items = raw if isinstance(raw, list) else []
    if raw is not None and not isinstance(raw, list):
        issues.append(_issue("", ISSUE_SHAPE, "categories must be a list."))
    if len(items) > MAX_CATEGORIES:
        issues.append(_issue("", ISSUE_TOO_MANY, f"At most {MAX_CATEGORIES} custom categories."))
        return []
    found: list[Category] = []
    for item in items:
        data = item if isinstance(item, Mapping) else {}
        category_id, label = str(data.get("id") or ""), _text(data.get("label"), 60)
        if not SLUG.match(category_id) or category_id in BUILTIN_CATEGORY_IDS or any(
                existing.id == category_id for existing in found):
            issues.append(_issue(category_id, ISSUE_CATEGORY_ID,
                                 "A category id is lower-case letters, digits and _, unique and not built in."))
        elif label is None:
            issues.append(_issue(category_id, ISSUE_LABEL, "Give the category a label (at most 60 characters)."))
        else:
            found.append(Category(category_id, label, builtin=False))
    return found


def _pattern_issue(detector_id: str, pattern: str) -> dict[str, str] | None:
    if not pattern or len(pattern) > MAX_PATTERN_CHARS:
        return _issue(detector_id, ISSUE_PATTERN_LONG, f"Write a pattern of 1 to {MAX_PATTERN_CHARS} characters.")
    try:
        checked = check_pattern(pattern)
    except UnsafePatternError:
        return _issue(detector_id, ISSUE_PATTERN_UNSAFE, "A repeated group repeats something without a fixed "
                      "character of its own; rewrite it without the nested repeat.")
    except UnsupportedPatternError:
        return _issue(detector_id, ISSUE_PATTERN_UNSUPPORTED,
                      "The pattern uses syntax RE2 does not run (look-around, back-references, …).")
    except re.error:
        return _issue(detector_id, ISSUE_PATTERN_SYNTAX, "The pattern does not compile.")
    if checked.fullmatch("") is not None:
        return _issue(detector_id, ISSUE_PATTERN_EMPTY, "The pattern matches empty text; it would match everywhere.")
    return None


def _detector(data: Mapping[str, Any], categories: set[str], issues: list[dict[str, str]]):
    detector_id = str(data.get("id") or "")
    count = len(issues)
    if not detector_id.startswith(CUSTOM_PREFIX) or not SLUG.match(detector_id[len(CUSTOM_PREFIX):]):
        issues.append(_issue(detector_id, ISSUE_ID, "A custom detector id is custom.<lower-case letters, digits, _>."))
    if set(data) - _FIELDS:
        issues.append(_issue(detector_id, ISSUE_SHAPE, "Unknown fields: " + ", ".join(sorted(set(data) - _FIELDS))))
    label = _text(data.get("label"), MAX_LABEL_CHARS)
    if label is None:
        issues.append(_issue(detector_id, ISSUE_LABEL, f"Give the detector a name (at most {MAX_LABEL_CHARS})."))
    category = str(data.get("category") or "")
    if category not in categories:
        issues.append(_issue(detector_id, ISSUE_CATEGORY, "Pick a built-in or custom category."))
    pattern = data.get("pattern") if isinstance(data.get("pattern"), str) else ""
    problem = _pattern_issue(detector_id, pattern)
    if problem:
        issues.append(problem)
    check = str(data.get("check") or CHECK_NONE)
    if check not in CHECKS:
        issues.append(_issue(detector_id, ISSUE_CHECK, "The check is none, mod10 or mod97."))
    raw_words = data.get("context_words") or []
    words = [_text(item, MAX_CONTEXT_WORD_CHARS) for item in raw_words] if isinstance(raw_words, list) else [None]
    if None in words or len(words) > MAX_CONTEXT_WORDS:
        issues.append(_issue(detector_id, ISSUE_CONTEXT, f"Up to {MAX_CONTEXT_WORDS} context words of at most "
                             f"{MAX_CONTEXT_WORD_CHARS} characters, one line each."))
    mask_style = str(data.get("mask_style") or MASK_TYPE_TOKEN)
    if mask_style not in CUSTOM_MASK_STYLES:
        issues.append(_issue(detector_id, ISSUE_MASK, "Mask as type token, last 4 or in full."))
    workspace_id = data.get("workspace_id") or ""
    if not isinstance(workspace_id, str) or len(workspace_id) > 64:
        issues.append(_issue(detector_id, ISSUE_SCOPE, "The scope is one Workspace id or every Workspace."))
    if len(issues) > count:
        return None
    unique_words = tuple(dict.fromkeys(str(item).lower() for item in words if item))
    return CustomDetectorDefinition(detector_id, str(label), category, pattern, check, unique_words, mask_style,
                                    str(workspace_id))


def check_detector_set(raw: Any) -> DetectorDefinitions:
    """The validated definitions of ``raw`` (``None`` or ``{}`` is none); :class:`DetectorSetError` otherwise."""
    if raw is None or raw == {}:
        return EMPTY_DEFINITIONS
    if not isinstance(raw, Mapping) or set(raw) - {"categories", "detectors"}:
        raise DetectorSetError(ERROR_INVALID, [_issue("", ISSUE_SHAPE, "Send {categories, detectors}.")])
    issues: list[dict[str, str]] = []
    categories = _categories(raw.get("categories"), issues)
    items = raw.get("detectors") if isinstance(raw.get("detectors"), list) else []
    if raw.get("detectors") is not None and not isinstance(raw.get("detectors"), list):
        issues.append(_issue("", ISSUE_SHAPE, "detectors must be a list."))
    if len(items) > MAX_DETECTORS:
        raise DetectorSetError(ERROR_INVALID, [_issue("", ISSUE_TOO_MANY, f"At most {MAX_DETECTORS} detectors.")])
    known = set(BUILTIN_CATEGORY_IDS) | {item.id for item in categories}
    detectors: list[CustomDetectorDefinition] = []
    for item in items:
        definition = _detector(item if isinstance(item, Mapping) else {}, known, issues)
        if definition is None:
            continue
        if any(existing.id == definition.id for existing in detectors):
            issues.append(_issue(definition.id, ISSUE_DUPLICATE, "Each detector id must be unique."))
            continue
        detectors.append(definition)
    if issues:
        raise DetectorSetError(ERROR_INVALID, issues)
    return DetectorDefinitions(tuple(sorted(detectors, key=lambda item: item.id)),
                               tuple(sorted(categories, key=lambda item: item.id)))
