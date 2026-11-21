"""The field names, bounds and error of a style profile, and the two value checks every section uses (``schema``)."""

from __future__ import annotations

import re
from typing import Any

LANGUAGES = ("dart", "python", "typescript", "javascript", "kotlin", "swift", "java", "go", "rust")
LINE_FIELDS = ("max_lines_per_file", "tests_max_lines", "max_function_lines", "max_line_length")
EXCLUDE_REASONS = ("generated", "l10n", "fixtures", "lockfile", "assets", "vendored", "documentation", "stylesheet",
                   "other")
# The rules an exclude row may keep judging (``keep``: a stylesheet keeps its line length).
KEEPABLE_RULES = ("max_lines_per_file", "tests_max_lines", "max_function_lines", "max_line_length", "naming", "layout",
                  "todo_requires_ticket", "no_commented_code")
COMMENT_FLAGS = ("public_api_doc", "no_commented_code", "todo_requires_ticket")
TOOL_FIELDS = ("formatter", "linter")
FIELDS = (*LINE_FIELDS, "exclude", "include", "test_globs", "comments", "layout", "naming", *TOOL_FIELDS, "l10n",
          "rules", "missing_tool", "diagrams")
DIAGRAM_KINDS = ("architecture", "navigation", "data_flow")
MISSING_TOOL_LEVELS = ("warning", "error")
L10N_FORMATS = ("arb", "i18next", "gettext", "properties", "fluent")
HARDCODED_LEVELS = ("warning", "error", "off")
MAX_COMMAND = 300
MAX_GLOBS = 60
MAX_TEXT = 3000
MAX_PATTERN = 300


class CodeStyleError(ValueError):
    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.reason = reason
        self.path = path


def _globs(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_GLOBS or any(
            not isinstance(item, str) or not item.strip() or len(item) > 200 for item in value):
        raise CodeStyleError("invalid_globs", path)
    return [item.strip() for item in value]


def _regex(value: Any, path: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_PATTERN:
        raise CodeStyleError("invalid_pattern", path)
    try:
        re.compile(value)
    except re.error:
        raise CodeStyleError("invalid_pattern", path) from None
    return value
