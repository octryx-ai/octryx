"""Workflow steps, strict or guided."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

STEP_STRICT = "strict"
STEP_GUIDED = "guided"
STEP_MODES = (STEP_STRICT, STEP_GUIDED)
MAX_STRICT_REMINDERS = 2


def default_step_mode(capability_class: str | None) -> str:
    return STEP_GUIDED if str(capability_class or "read_only") == "read_only" else STEP_STRICT


def workflow_steps(contract: Any) -> list[dict[str, Any]]:
    body = contract if isinstance(contract, Mapping) else {}
    raw = body.get("source_steps")
    default = default_step_mode(str(body.get("capability_class") or ""))
    steps = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, Mapping) or not str(item.get("tool") or "").strip():
            continue
        mode = str(item.get("mode") or "")
        steps.append({
            "tool": str(item["tool"]).strip(),
            "label": str(item.get("evidence_label") or item.get("label") or ""),
            "required": item.get("required") is not False,
            "mode": mode if mode in STEP_MODES else default,
        })
    return steps


def step_checks(contract: Any) -> list[dict[str, Any]]:
    return [
        {
            "type": "tool_called",
            "params": {"tools": [step["tool"]]},
            "blocking": step["mode"] == STEP_STRICT,
            "step_mode": step["mode"],
            "description": f"Step: {step['label'] or step['tool']} ({step['mode']})",
        }
        for step in workflow_steps(contract)
        if step["required"]
    ]


def validate_steps(contract: Any) -> list[dict[str, str]]:
    raw = contract.get("source_steps") if isinstance(contract, Mapping) else None
    errors = []
    for index, item in enumerate(raw if isinstance(raw, list) else []):
        mode = item.get("mode") if isinstance(item, Mapping) else None
        if mode is not None and mode not in STEP_MODES:
            message = f"source_steps[{index}].mode must be strict or guided"
            errors.append({"code": "invalid_step_mode", "message": message})
    return errors


__all__ = [
    "MAX_STRICT_REMINDERS",
    "STEP_GUIDED",
    "STEP_MODES",
    "STEP_STRICT",
    "default_step_mode",
    "step_checks",
    "validate_steps",
    "workflow_steps",
]
