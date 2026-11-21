"""Code-structure diagram evidence guard for turn-level tool execution.

Service-owned module (same family as ``turn_tool_guards_aws``): when the
turn's workflow contract declares ``diagram_source == "code_structure_snapshot"``,
a ``create_diagram``/``append_diagram`` call must not dispatch before the turn
holds a successful ``code_structure_snapshot`` with at least one selected
node. The gate applies even when a runtime submits multiple tools at once.
"""

from __future__ import annotations

from typing import Any

from .prompt_catalog import render_prompt
from .turn_tool_guards import _active_guard_rule, _guard_result

_DIAGRAM_AUTHORING_TOOL_NAMES = {"create_diagram", "append_diagram"}
_CODE_STRUCTURE_SNAPSHOT_TOOL = "code_structure_snapshot"
_GUARD_RULE_ID = "code_structure_diagram_evidence_required"


def _workflow_contract_from_snapshot(context_snapshot: dict[str, Any]) -> dict[str, Any]:
    request_analysis = context_snapshot.get("request_analysis")
    if not isinstance(request_analysis, dict):
        return {}
    workflow_contract = request_analysis.get("workflow_contract")
    return workflow_contract if isinstance(workflow_contract, dict) else {}


def _snapshot_has_renderable_nodes(result: Any) -> bool:
    if not isinstance(result, dict) or result.get("error"):
        return False
    diagram_brief = result.get("diagram_brief")
    if not isinstance(diagram_brief, dict):
        return False
    selected_nodes = diagram_brief.get("selected_nodes")
    return isinstance(selected_nodes, list) and len(selected_nodes) > 0


def code_structure_diagram_evidence_guard_result(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    turn_tool_history: list[dict[str, Any]] | None,
    context_snapshot: dict[str, Any] | None,
    exec_policy_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    guard_rule = _active_guard_rule(exec_policy_config, _GUARD_RULE_ID)
    if guard_rule is None:
        return None
    if str(tool_name or "").strip() not in _DIAGRAM_AUTHORING_TOOL_NAMES:
        return None
    workflow_contract = _workflow_contract_from_snapshot(context_snapshot or {})
    if str(workflow_contract.get("diagram_source") or "").strip() != _CODE_STRUCTURE_SNAPSHOT_TOOL:
        return None

    for item in reversed(turn_tool_history or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() != _CODE_STRUCTURE_SNAPSHOT_TOOL:
            continue
        if _snapshot_has_renderable_nodes(item.get("result")):
            return None

    return _guard_result(
        {
            "error": render_prompt("tool_guard.code_structure.error"),
            "guardrail": _GUARD_RULE_ID,
            "tool_name": tool_name,
            "suggested_next_step": render_prompt("tool_guard.code_structure.next_step"),
        },
        guard_rule,
    )


_FULL_SCAN_MAX_SYMBOLS = 400  # tool cap: the brief carries every block of real repos
_FULL_SCAN_MAX_FILES = 2000  # tool cap: bounds govern the size, not model discretion


def enforce_code_structure_snapshot_full_scope(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    context_snapshot: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Force the full-repository scan for evidence-bound structure snapshots.

    In a code-structure diagram workflow the snapshot IS the evidence base:
    a model-chosen ``paths`` narrowing or a small ``max_symbols`` silently
    can omit modules from every downstream diagram. Scope
    is therefore not model discretion — paths are cleared and the symbol/file
    bounds are raised to the tool caps; the tool's own bounds govern the
    size. The language filter stays untouched (a DSL filter is a declared
    evidence choice, not a scope narrowing).

    Returns ``(effective_args, trace)``; trace is None when nothing changed.
    """
    if str(tool_name or "").strip() != _CODE_STRUCTURE_SNAPSHOT_TOOL:
        return tool_args, None
    workflow_contract = _workflow_contract_from_snapshot(context_snapshot or {})
    if str(workflow_contract.get("diagram_source") or "").strip() != _CODE_STRUCTURE_SNAPSHOT_TOOL:
        return tool_args, None
    effective = dict(tool_args or {})
    changes: dict[str, Any] = {}
    dropped_paths = [str(item) for item in (effective.get("paths") or []) if str(item).strip()]
    if dropped_paths:
        changes["dropped_paths"] = dropped_paths
    effective.pop("paths", None)
    for key, forced in (("max_symbols", _FULL_SCAN_MAX_SYMBOLS), ("max_files", _FULL_SCAN_MAX_FILES)):
        try:
            current = int(effective.get(key)) if effective.get(key) is not None else None
        except (TypeError, ValueError):
            current = None
        if current != forced:
            if current is not None:
                changes[f"previous_{key}"] = current
            effective[key] = forced
            changes[key] = forced
    if not changes:
        return effective, None
    return effective, {
        "rule": "code_structure_snapshot_full_scope",
        "reason": "evidence-bound structure snapshots always scan the full repository (bounds govern size)",
        **changes,
    }


__all__ = [
    "code_structure_diagram_evidence_guard_result",
    "enforce_code_structure_snapshot_full_scope",
]
