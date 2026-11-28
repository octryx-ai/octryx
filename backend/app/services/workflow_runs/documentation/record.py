"""The ``feature_documentation`` output: what the documentation phase's agent drafts
(``submit_feature_documentation``)."""

from __future__ import annotations

from typing import Any

KIND = "feature_documentation"
TOOL = "submit_feature_documentation"
MAX_TITLE = 200
MAX_SECTION = 6000
REQUIRED = ("title", "what", "why", "how_to_use")


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def validate_feature_documentation(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    record = {
        "title": _text(raw.get("title"), MAX_TITLE),
        "what": _text(raw.get("what"), MAX_SECTION),
        "why": _text(raw.get("why"), MAX_SECTION),
        "how_to_use": _text(raw.get("how_to_use"), MAX_SECTION),
        "notes": _text(raw.get("notes"), MAX_SECTION),
    }
    problems = [f"{field}: missing" for field in REQUIRED if not record[field]]
    return record, problems
