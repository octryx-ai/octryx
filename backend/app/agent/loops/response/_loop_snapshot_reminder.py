"""Situational reminder after a successful evidence snapshot.

Claude-Code-style system reminder: when a topology or
code-structure snapshot succeeded in this iteration, remind the model that
the evidence now exists and ``create_diagram`` renders deterministically from
it. Fires at most once per snapshot result; no prompt-text heuristics — it
keys purely on executed tool results.
"""

from __future__ import annotations

from typing import Any

from ....services.prompt_catalog import render_prompt

_SNAPSHOT_TOOL_NAMES = {
    "aws_topology_snapshot",
    "kubernetes_topology_snapshot",
    "code_structure_snapshot",
}
_DIAGRAM_TOOL_NAME = "create_diagram"


def _successful_snapshot_tools(tool_results: list[dict[str, Any]] | None) -> list[str]:
    names: list[str] = []
    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        if tool_name not in _SNAPSHOT_TOOL_NAMES:
            continue
        result = item.get("result")
        if isinstance(result, dict) and not result.get("error"):
            names.append(tool_name)
    return names


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


def append_snapshot_evidence_reminder(
    *,
    messages: list[dict[str, Any]],
    tool_results: list[dict[str, Any]] | None,
    turn_tool_history: list[dict[str, Any]] | None,
    current_allowed_tool_names: set[str] | None,
) -> bool:
    """Append the post-snapshot reminder; returns True when appended."""
    snapshot_tools = _successful_snapshot_tools(tool_results)
    if not snapshot_tools:
        return False
    allowed = current_allowed_tool_names or set()
    if allowed and _DIAGRAM_TOOL_NAME not in allowed:
        return False
    if _diagram_already_created(turn_tool_history):
        return False
    snapshot_tool = snapshot_tools[-1]
    messages.append(
        {
            "role": "system",
            "content": render_prompt("loop.snapshot_evidence_reminder", snapshot_tool=snapshot_tool),
        }
    )
    return True


__all__ = ["append_snapshot_evidence_reminder"]
