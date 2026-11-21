"""Parser and normalizer for model-authored tool plan JSON."""

from __future__ import annotations

import json
import re
from typing import Any

from .contract import CONTRACT_VERSION, PLAN_MODE, validate_tool_plan_contract

_FENCED_JSON_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json_object(raw_content: str) -> dict[str, Any] | None:
    content = str(raw_content or "").strip()
    if not content:
        return None
    candidates = [content]
    fenced = _FENCED_JSON_PATTERN.search(content)
    if fenced:
        candidates.insert(0, fenced.group(1))
    first_brace = content.find("{")
    last_brace = content.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidates.append(content[first_brace : last_brace + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _normalize_selected_tools(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            tool_name = item.strip()
            if tool_name:
                normalized.append({"tool": tool_name, "reason": "", "expected_evidence": []})
            continue
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool") or item.get("name") or "").strip()
        if not tool_name:
            continue
        evidence = item.get("expected_evidence")
        if not isinstance(evidence, list):
            evidence = []
        normalized.append(
            {
                "tool": tool_name,
                "reason": str(item.get("reason") or "").strip(),
                "expected_evidence": [str(entry) for entry in evidence if str(entry).strip()],
            }
        )
    return normalized


def parse_model_tool_plan_contract(
    raw_content: str,
    *,
    session_tool_catalog: dict[str, Any] | None,
) -> dict[str, Any]:
    """Parse model-authored planner JSON and validate it without executing it."""

    parsed = _extract_json_object(raw_content)
    if parsed is None:
        return {
            "version": CONTRACT_VERSION,
            "mode": PLAN_MODE,
            "source": "model_response_parse_error",
            "intent_class": "unknown",
            "confidence": 0.0,
            "selected_tools": [],
            "stop_criteria": [],
            "max_tool_calls": 0,
            "requires_clarification": True,
            "validation": {
                "valid": False,
                "errors": ["planner_response_not_json"],
                "warnings": [],
            },
        }

    plan = {
        "version": parsed.get("version", CONTRACT_VERSION),
        "mode": parsed.get("mode", PLAN_MODE),
        "source": "model_response",
        "intent_class": str(parsed.get("intent_class") or "unknown").strip(),
        "confidence": parsed.get("confidence", 0),
        "selected_tools": _normalize_selected_tools(parsed.get("selected_tools")),
        "stop_criteria": parsed.get("stop_criteria") if isinstance(parsed.get("stop_criteria"), list) else [],
        "max_tool_calls": parsed.get("max_tool_calls", 0),
        "requires_clarification": bool(parsed.get("requires_clarification")),
    }
    plan["validation"] = validate_tool_plan_contract(plan, session_tool_catalog=session_tool_catalog)
    return plan


__all__ = ["parse_model_tool_plan_contract"]
