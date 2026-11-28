"""Custom detectors and categories of a policy-set version."""

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
    return CompiledCustomDetector(definition, re2.compile(to_re2(definition.pattern), _OPTIONS))


__all__ = [
    "CompiledCustomDetector",
    "compile_detector",
]
