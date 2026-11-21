"""The tool name a published workflow is offered under."""

from __future__ import annotations

import re

WORKFLOW_TOOL_PREFIX = "run_flow_"
_TOOL_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")
_PERSON_QUESTION_RE = re.compile(r"\b(?:who is|who's)\s+(.+?)[?.!]*$", re.IGNORECASE)


def workflow_tool_name_for_key(key: str, name: str = "") -> str:
    base = str(key or name or "workflow").strip().lower()
    slug = _TOOL_NAME_RE.sub("_", base).strip("_")
    slug = re.sub(r"_+", "_", slug) or "workflow"
    if slug[:1].isdigit():
        slug = f"flow_{slug}"
    return f"{WORKFLOW_TOOL_PREFIX}{slug}"[:64].rstrip("_")
