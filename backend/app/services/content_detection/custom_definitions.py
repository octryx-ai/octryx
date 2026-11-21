"""Custom detector definitions of a policy-set version: limits, issue codes and the definition types."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .vocabulary import (
    BUILTIN_CATEGORIES,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CUSTOM_MASK_STYLES,
    CUSTOM_PREFIX,
    MASK_TYPE_TOKEN,
    Category,
    DetectorInfo,
)

MAX_DETECTORS = 50
MAX_CATEGORIES = 20
MAX_CONTEXT_WORDS = 10
MAX_CONTEXT_WORD_CHARS = 40
MAX_LABEL_CHARS = 80
CONTEXT_WINDOW = 32
CHECK_NONE = "none"
CHECK_MOD10 = "mod10"
CHECK_MOD97 = "mod97"
CHECKS: tuple[str, ...] = (CHECK_NONE, CHECK_MOD10, CHECK_MOD97)
SLUG = re.compile(r"^[a-z][a-z0-9_]{1,39}$")

ERROR_INVALID = "content_detectors_invalid"
ISSUE_SHAPE = "detector_set_shape"
ISSUE_TOO_MANY = "detector_set_too_many"
ISSUE_ID = "detector_id_invalid"
ISSUE_DUPLICATE = "detector_id_duplicate"
ISSUE_LABEL = "detector_label_invalid"
ISSUE_CATEGORY = "detector_category_unknown"
ISSUE_CATEGORY_ID = "category_id_invalid"
ISSUE_PATTERN_LONG = "pattern_too_long"
ISSUE_PATTERN_UNSAFE = "pattern_unsafe"
ISSUE_PATTERN_UNSUPPORTED = "pattern_not_re2"
ISSUE_PATTERN_SYNTAX = "pattern_syntax"
ISSUE_PATTERN_EMPTY = "pattern_matches_empty"
ISSUE_CHECK = "detector_check_invalid"
ISSUE_CONTEXT = "context_words_invalid"
ISSUE_MASK = "mask_style_invalid"
ISSUE_SCOPE = "workspace_scope_invalid"
_FIELDS = frozenset({"id", "label", "category", "pattern", "check", "context_words", "mask_style", "workspace_id"})


class DetectorSetError(ValueError):
    def __init__(self, code: str, issues: list[dict[str, str]] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.issues = list(issues or [])[:50]


@dataclass(frozen=True, slots=True)
class CustomDetectorDefinition:
    id: str
    label: str
    category: str
    pattern: str
    check: str = CHECK_NONE
    context_words: tuple[str, ...] = ()
    mask_style: str = MASK_TYPE_TOKEN
    workspace_id: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "category": self.category, "pattern": self.pattern,
                "check": self.check, "context_words": list(self.context_words), "mask_style": self.mask_style,
                "workspace_id": self.workspace_id or None}

    @property
    def confidence(self) -> str:
        return CONFIDENCE_HIGH if self.check != CHECK_NONE or self.context_words else CONFIDENCE_MEDIUM

    def info(self) -> DetectorInfo:
        token = self.id[len(CUSTOM_PREFIX):].upper()
        method = "RE2 pattern" + (f", {self.check} check" if self.check != CHECK_NONE else "") + (
            ", near " + ", ".join(self.context_words) if self.context_words else "")
        styles = (self.mask_style, *(item for item in CUSTOM_MASK_STYLES if item != self.mask_style))
        return DetectorInfo(self.id, self.category, self.label, token, method, self.confidence, styles, False)


@dataclass(frozen=True, slots=True)
class DetectorDefinitions:
    """The custom detectors and categories of one policy-set version."""

    detectors: tuple[CustomDetectorDefinition, ...] = ()
    categories: tuple[Category, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"categories": [{"id": item.id, "label": item.label} for item in self.categories],
                "detectors": [item.to_json() for item in self.detectors]}

    @property
    def empty(self) -> bool:
        return not self.detectors and not self.categories

    def digest(self) -> str:
        canonical = json.dumps(self.to_json(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def all_categories(self) -> tuple[Category, ...]:
        return (*BUILTIN_CATEGORIES, *self.categories)


EMPTY_DEFINITIONS = DetectorDefinitions()
