"""Elastic per-step iteration sizing with hard guardrails."""

from __future__ import annotations

import json
from typing import Any

from .settings import get_elastic_iteration_settings

# A fixed number of calls can stop a server chat midway (creating six work items, it stops after four). A step
# keeps going while it makes progress; a loop stops it; a hard ceiling stays as the budget guard.
PROGRESS_WINDOW = 4
LOOP_REPEATS = 3
ERROR_STREAK = 4
PROGRESS_HEADROOM = 2
MAX_PROGRESS_EXTENSION = 24


def _signature(item: dict[str, Any]) -> str:
    try:
        params = json.dumps(item.get("params") or {}, sort_keys=True, default=str)
    except (TypeError, ValueError):
        params = str(item.get("params"))
    return f"{item.get('tool_name')}:{params}"


def _failed(item: dict[str, Any]) -> bool:
    result = item.get("result")
    return isinstance(result, dict) and bool(result.get("error"))


def loop_detected(history: list[dict[str, Any]]) -> bool:
    """The same call with the same arguments three times, or four failed calls in a row."""
    counts: dict[str, int] = {}
    for item in history:
        key = _signature(item)
        counts[key] = counts.get(key, 0) + 1
        if counts[key] >= LOOP_REPEATS:
            return True
    tail = history[-ERROR_STREAK:]
    return len(tail) == ERROR_STREAK and all(_failed(item) for item in tail)


def recent_progress(history: list[dict[str, Any]]) -> bool:
    """A successful call with arguments not seen before in this step, within the last calls."""
    seen: set[str] = set()
    new_ok: list[bool] = []
    for item in history:
        key = _signature(item)
        new_ok.append(key not in seen and not _failed(item))
        seen.add(key)
    return any(new_ok[-PROGRESS_WINDOW:])


def _has_explicit_step_iteration_limit(step: dict[str, Any] | None) -> bool:
    if not isinstance(step, dict):
        return False
    step_config = step.get("stepConfig")
    if not isinstance(step_config, dict):
        step_config = step.get("step_config")
    if not isinstance(step_config, dict):
        return False
    try:
        return int(step_config.get("max_iterations")) > 0
    except (TypeError, ValueError):
        return False


def _no_bonus(base_limit: int, reason: str) -> dict[str, Any]:
    return {
        "base_limit": int(base_limit),
        "bonus": 0,
        "effective_limit": int(base_limit),
        "reason": reason,
    }


def _blocked_attempts(recent_history: list[dict[str, Any]]) -> int:
    blocked_attempts = 0
    for item in recent_history:
        result = item.get("result")
        if isinstance(result, dict):
            error_text = str(result.get("error") or "").lower()
            if "not allowed in the current step" in error_text:
                blocked_attempts += 1
    return blocked_attempts


def _multi_tool_bonus(
    step: dict[str, Any], base_limit: int, unique_tools: set[str], settings: dict[str, Any]
) -> dict[str, Any]:
    unique_count = len(unique_tools)
    threshold = settings["unique_tool_threshold"]
    if unique_count < threshold:
        return _no_bonus(base_limit, "insufficient_unique_tools")

    bonus_units = unique_count - threshold + 1
    step_type = str(step.get("stepType") or step.get("step_type") or "").strip().lower()
    bonus = min(settings["max_bonus"], bonus_units * 2)
    if step_type in {"analysis", "knowledge"}:
        bonus = min(settings["max_bonus"], bonus + 1)
    return {
        "base_limit": int(base_limit),
        "bonus": int(bonus),
        "effective_limit": int(base_limit) + int(bonus),
        "reason": "multi_tool_progress",
        "unique_tool_count": unique_count,
        "unique_tools": sorted(unique_tools),
    }


def compute_elastic_step_iteration_limit(
    *,
    step: dict[str, Any] | None,
    base_limit: int,
    step_tool_history: list[dict[str, Any]],
    wrapup_forced: bool,
    runtime_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_elastic_iteration_settings(runtime_settings)
    if not step or wrapup_forced or not settings["enabled"]:
        return _no_bonus(base_limit, "disabled_or_wrapup")
    if _has_explicit_step_iteration_limit(step):
        return _no_bonus(base_limit, "explicit_step_limit")
    if int(base_limit) < 8:
        return _no_bonus(base_limit, "strict_base_limit")

    recent_history = step_tool_history[-8:]
    unique_tools = {
        str(item.get("tool_name") or "").strip() for item in recent_history if str(item.get("tool_name") or "").strip()
    }
    if _blocked_attempts(recent_history) > 0:
        return _no_bonus(base_limit, "blocked_attempts")

    if loop_detected(step_tool_history):
        return _no_bonus(base_limit, "loop_detected")
    if len(step_tool_history) >= int(base_limit) - 1 and recent_progress(step_tool_history):
        # Still making progress at the limit: room for a few more calls, up to the hard ceiling.
        extended = min(int(base_limit) + MAX_PROGRESS_EXTENSION, len(step_tool_history) + PROGRESS_HEADROOM)
        if extended > int(base_limit):
            return {
                "base_limit": int(base_limit),
                "bonus": extended - int(base_limit),
                "effective_limit": extended,
                "reason": "progress",
            }

    return _multi_tool_bonus(step, base_limit, unique_tools, settings)


__all__ = ["compute_elastic_step_iteration_limit", "loop_detected", "recent_progress"]
