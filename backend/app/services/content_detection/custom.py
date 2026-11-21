"""Custom detectors and categories of a policy-set version.

A Workspace (or the whole instance) defines its own identifiers as custom detectors. They change what a
policy means, so they live in the policy-set version beside the Cedar text: the set digest covers them, and the
draft → review → four-eyes publish lifecycle, the saved test cases and rollback cover them too.

A definition (:func:`check_detector_set` validates; every rule refuses with an issue, never silently drops):

- ``id`` ``custom.<slug>`` (unique), ``label``, ``category`` (built-in or a custom category of the same set);
- ``pattern``: RE2 only, checked like a structured-profile pattern (``knowledge/structured/profile_patterns``:
  at most 300 characters, no ambiguous nested repeat, compiles on RE2) and it may not match the empty text;
- ``check``: ``none`` | ``mod10`` | ``mod97`` (the match must pass it);
- ``context_words``: optional; when given, a match counts only with one of them within
  :data:`CONTEXT_WINDOW` characters before or after it (case-insensitive);
- ``mask_style``: ``type_token`` | ``last4`` | ``full``;
- ``workspace_id``: the Workspace it applies to, or empty for every Workspace. Outside its scope it never runs.

Confidence: high with a check or context words, medium for the pattern alone. Custom categories
(``categories``: ``id``, ``label``) extend the built-in ones for the set's detectors and the alias field
"approved for sensitive data". Sample texts are never part of a definition: the preview takes them per
request and keeps nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import re2

from ..knowledge.structured.profile_patterns import to_re2
from .builtin import _matches
from .custom_definitions import CHECK_MOD10, CHECK_MOD97, CONTEXT_WINDOW, CustomDetectorDefinition
from .findings import Finding
from .validators import iban_valid, mod10_valid
from .vocabulary import DetectorInfo


def _options() -> re2.Options:
    options = re2.Options()
    options.log_errors = False
    return options


_OPTIONS = _options()


@dataclass(frozen=True, slots=True)
class CompiledCustomDetector:
    """A custom detector ready to scan (``scanner.CustomMatcher``)."""

    definition: CustomDetectorDefinition
    regexp: Any = field(repr=False)

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def category(self) -> str:
        return self.definition.category

    @property
    def info(self) -> DetectorInfo:
        return self.definition.info()

    def _checked(self, value: str) -> bool:
        if self.definition.check == CHECK_MOD10:
            return mod10_valid("".join(char for char in value if char.isdigit()))
        if self.definition.check == CHECK_MOD97:
            return iban_valid("".join(char for char in value if char.isalnum()).upper())
        return True

    def _near_word(self, text: str, start: int, end: int) -> bool:
        if not self.definition.context_words:
            return True
        window = text[max(0, start - CONTEXT_WINDOW):end + CONTEXT_WINDOW].lower()
        return any(word in window for word in self.definition.context_words)

    def find(self, text: str) -> list[Finding]:
        found: list[Finding] = []
        for match in _matches(self.regexp, text):
            start, end = match.start(), match.end()
            if end == start or not self._checked(text[start:end]) or not self._near_word(text, start, end):
                continue
            found.append(Finding(self.id, self.category, self.definition.confidence, start, end))
        return found


def compile_detector(definition: CustomDetectorDefinition) -> CompiledCustomDetector:
    """The RE2 program of a validated definition (``check_detector_set`` ran first)."""
    return CompiledCustomDetector(definition, re2.compile(to_re2(definition.pattern), _OPTIONS))


__all__ = [
    "CompiledCustomDetector",
    "compile_detector",
]
