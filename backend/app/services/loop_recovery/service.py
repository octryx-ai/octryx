"""Structured recovery planning for detected loop events."""

from __future__ import annotations

from typing import Any

from ...agent.core.guards.stop_text import agent_stop_text
from ..prompt_catalog import render_prompt


def _step_name(step: dict[str, Any] | None) -> str:
    return str((step or {}).get("name") or "").strip() or "current step"


def plan_loop_recovery(
    *,
    event: dict[str, Any] | None,
    step: dict[str, Any] | None,
    has_followup_steps: bool,
    wrapup_forced: bool,
) -> dict[str, Any]:
    step_name = _step_name(step)
    kind = str((event or {}).get("kind") or "").strip().lower()
    message = str((event or {}).get("message") or "").strip() or render_prompt(
        "guard.recovery.stuck_default", step_name=step_name
    )
    if kind == "repeated_previous_step_summary":
        return {
            "action": "continue_current_step",
            "system_message": render_prompt("guard.recovery.previous_step_summary"),
            "final_content": "",
        }
    if kind == "duplicate_no_tool_response":
        return {
            "action": "stop_run",
            "system_message": "",
            "final_content": agent_stop_text("guard.recovery.duplicate_no_tool_stop", step_name=step_name),
        }
    if kind == "repetitive_empty_search_loop" and not has_followup_steps:
        return {
            "action": "stop_run",
            "system_message": "",
            "final_content": agent_stop_text("guard.recovery.empty_search_stop", step_name=step_name),
        }
    if has_followup_steps:
        return {
            "action": "move_to_next_step",
            "system_message": render_prompt("guard.recovery.move_to_next_step", message=message),
            "final_content": "",
        }
    if wrapup_forced:
        stop_key = (
            "guard.recovery.iteration_ceiling_stop" if kind == "iteration_ceiling" else "guard.recovery.looping_stop"
        )
        return {
            "action": "stop_run",
            "system_message": "",
            "final_content": agent_stop_text(stop_key, step_name=step_name),
        }
    if kind == "iteration_ceiling":
        system_message = render_prompt("guard.recovery.iteration_ceiling_wrapup", step_name=step_name)
    else:
        system_message = render_prompt("guard.recovery.force_wrapup", message=message)
    return {
        "action": "force_wrapup",
        "system_message": system_message,
        "final_content": "",
    }
