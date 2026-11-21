"""The agent setup fields as request input: capability ceiling, default workflow, execution mode.

Each value is checked against a closed set; an unknown value is refused (422), never remapped.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .agent_definition_payload import EXECUTION_MODES
from .run_capability.classes import CAPABILITY_CLASSES

DEFAULT_CEILING = "read_only"
MAX_WORKFLOW_KEY_CHARS = 180


def _field(payload: dict[str, Any], snake: str, camel: str) -> tuple[bool, Any]:
    for name in (snake, camel):
        if name in payload:
            return True, payload[name]
    return False, None


def capability_ceiling_from(payload: dict[str, Any], *, current: str | None) -> str:
    present, value = _field(payload, "capability_ceiling", "capabilityCeiling")
    if not present:
        return current or DEFAULT_CEILING
    clean = str(value or "").strip()
    if clean not in CAPABILITY_CLASSES:
        raise HTTPException(status_code=422, detail={
            "code": "capability_ceiling_invalid", "field": "capability_ceiling",
            "message": f"The capability ceiling must be one of: {', '.join(CAPABILITY_CLASSES)}.",
        })
    return clean


def default_workflow_key_from(payload: dict[str, Any], *, current: str | None) -> str | None:
    present, value = _field(payload, "default_workflow_key", "defaultWorkflowKey")
    if not present:
        return current
    clean = str(value or "").strip()
    if len(clean) > MAX_WORKFLOW_KEY_CHARS:
        raise HTTPException(status_code=422, detail={
            "code": "default_workflow_key_invalid", "field": "default_workflow_key",
            "message": "The default workflow key is too long.",
        })
    return clean or None


def execution_mode_from(payload: dict[str, Any], *, current: str | None) -> str | None:
    present, value = _field(payload, "execution_mode", "executionMode")
    if not present:
        return current
    clean = str(value or "").strip()
    if clean and clean not in EXECUTION_MODES:
        raise HTTPException(status_code=422, detail={
            "code": "execution_mode_invalid", "field": "execution_mode",
            "message": f"The execution mode must be empty or one of: {', '.join(sorted(EXECUTION_MODES))}.",
        })
    return clean or None


__all__ = ["capability_ceiling_from", "default_workflow_key_from", "execution_mode_from"]
