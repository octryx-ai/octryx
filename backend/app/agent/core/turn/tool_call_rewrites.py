"""Rewrites of a tool call's name and arguments before it is dispatched."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.tools.context import ToolContext

from ....models.json_text import safe_json_dict
from ....services.prompt_catalog import render_prompt
from ....services.request_analysis import sanitize_implicit_limit_params
from ....services.turn_tool_guards_code_structure import (
    enforce_code_structure_snapshot_full_scope as _enforce_code_structure_snapshot_full_scope,
)


def parse_tool_call_arguments(tool_args_str: Any) -> dict[str, Any]:
    if isinstance(tool_args_str, str):
        return safe_json_dict(tool_args_str)
    if isinstance(tool_args_str, dict):
        return tool_args_str
    return {}


def _enforce_evidence_diagrams(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    turn_tool_history: list[dict[str, Any]],
    allowed_tool_names: set[str],
    context_snapshot: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    from ...loops.request._loop_evidence_diagrams import enforce_evidence_backed_diagrams

    enforced = enforce_evidence_backed_diagrams(
        tool_calls=[{"function": {"name": tool_name, "arguments": tool_args}}],
        turn_tool_history=turn_tool_history,
        allowed_tool_names=allowed_tool_names,
    )
    if enforced is None:
        return None
    replacement_calls, diagram_audit = enforced
    context_snapshot["evidence_diagram_enforcement"] = diagram_audit
    if replacement_calls:
        replacement = replacement_calls[0].get("function", {})
        return str(replacement.get("name") or tool_name), safe_json_dict(replacement.get("arguments", "{}"))
    # Every evidence section is already rendered; a freehand duplicate must not dispatch.
    # The empty-xml error tells the model to stop drawing.
    return tool_name, {"title": render_prompt("tool_guard.turn.diagram_stop_title"), "xml": ""}


def enforce_evidence_bound_tool_call(
    *,
    func: Any,
    tool_name: str,
    tool_args: dict[str, Any],
    turn_tool_history: list[dict[str, Any]] | None,
    allowed_tool_names: set[str],
    context_snapshot: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Replace a freehand diagram by its deterministic evidence render; the tool call is renamed in place.

    Every loop goes through the per-call executor, so the binding evidence rule lives here: once the turn holds an
    AWS topology or code-structure snapshot, freehand diagram XML is replaced.
    """
    if turn_tool_history is None:
        return tool_name, tool_args
    rewrites = (
        ({"create_diagram", "append_diagram"}, _enforce_evidence_diagrams),
    )
    for tool_names, enforce in rewrites:
        if tool_name not in tool_names:
            continue
        rewritten = enforce(
            tool_name=tool_name,
            tool_args=tool_args,
            turn_tool_history=turn_tool_history,
            allowed_tool_names=allowed_tool_names,
            context_snapshot=context_snapshot,
        )
        if rewritten is not None:
            tool_name, tool_args = rewritten
            if isinstance(func, dict):
                func["name"] = tool_name
    return tool_name, tool_args


def prepare_tool_arguments(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_context: ToolContext,
    latest_repo_state: dict[str, str],
    infer_repo_tool_args: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]],
    context_snapshot: dict[str, Any],
    turn_tool_history: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    tool_args = infer_repo_tool_args(tool_name, tool_args, latest_repo_state)
    tool_context.turn_context_snapshot = dict(context_snapshot or {})
    tool_context.turn_tool_history = [item for item in (turn_tool_history or []) if isinstance(item, dict)]
    tool_args = sanitize_implicit_limit_params(
        tool_name=tool_name,
        params=tool_args,
        snapshot=tool_context.turn_context_snapshot,
        fallback_user_message=tool_context.current_user_message,
    )
    # Evidence-bound structure snapshots always scan the full repository:
    # scope (paths/symbol bounds) is enforced, not model discretion.
    tool_args, scope_trace = _enforce_code_structure_snapshot_full_scope(
        tool_name=tool_name,
        tool_args=tool_args,
        context_snapshot=context_snapshot,
    )
    if scope_trace is not None:
        context_snapshot["code_structure_scope_enforcement"] = scope_trace
    return tool_args
