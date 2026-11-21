"""The platform's built-in style, the lowest level under the installation's, the Workspace's and the repository's
own: data in ``built_in.json`` (its limits, excludes, test globs, per-language layout, naming, tools and l10n), never
lists in engine code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DATA: dict[str, Any] = json.loads((Path(__file__).with_name("built_in.json")).read_text(encoding="utf-8"))

TODO_WITH_TICKET: str = _DATA["todo_with_ticket"]
BUILT_IN: dict[str, Any] = _DATA["profile"]
EXTENSIONS: dict[str, str] = _DATA["extensions"]


def language_of(path: str) -> str | None:
    lower = path.lower()
    return next((language for suffix, language in EXTENSIONS.items() if lower.endswith(suffix)), None)


__all__ = ["BUILT_IN", "EXTENSIONS", "TODO_WITH_TICKET", "language_of"]
