"""Situational reminder when the model answers with a mermaid code fence.

Same category as the post-snapshot reminder: the
trigger is a LITERAL signal, not intent guessing — a ```` ```mermaid ````
fence in the final answer means the model already decided to draw a diagram
and only picked the wrong medium (chat text instead of a platform artifact).
The reminder points at the catalog/select_workflow + create_diagram path and
fires at most once per turn, so an insisting model can still answer with
text afterwards (no forced loop).
"""

from __future__ import annotations

from typing import Any

from ....services.prompt_catalog import render_prompt

_MERMAID_FENCE = "```mermaid"
_REMINDER_FIRED_KEY = "mermaid_artifact_reminder_fired"
_DIAGRAM_TOOL_NAME = "create_diagram"


def _diagram_already_created(turn_tool_history: list[dict[str, Any]] | None) -> bool:
    for item in turn_tool_history or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() != _DIAGRAM_TOOL_NAME:
            continue
        result = item.get("result")
        if isinstance(result, dict) and not result.get("error"):
            return True
    return False


def detect_mermaid_instead_of_artifact(
    *,
    assistant_content: str,
    turn_tool_history: list[dict[str, Any]] | None,
    context_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a reminder event when the answer ships a mermaid fence instead
    of a diagram artifact; None when the answer passes untouched."""
    content = str(assistant_content or "")
    if _MERMAID_FENCE not in content:
        return None
    if _diagram_already_created(turn_tool_history):
        return None
    snapshot = context_snapshot if isinstance(context_snapshot, dict) else {}
    if snapshot.get(_REMINDER_FIRED_KEY):
        return None
    snapshot[_REMINDER_FIRED_KEY] = True
    return {
        "rule": "mermaid_instead_of_diagram_artifact",
        "message": render_prompt("loop.mermaid_instead_of_diagram"),
    }


__all__ = ["detect_mermaid_instead_of_artifact"]
