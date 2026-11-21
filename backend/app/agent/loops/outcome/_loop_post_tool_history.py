"""Pure tool-history helpers for post-tool outcome handling.

Successful-result lookups, child evidence-path extraction, sub-agent depth,
read-only child wrap-up, and the diagram artifact success message. Moved
unchanged from ``app/agent/loops/_loop_post_tool.py``.
"""

from __future__ import annotations

from typing import Any

from app.services.prompt_catalog import render_prompt


def _latest_successful_tool_result_from_history(
    turn_tool_history: list[dict[str, Any]],
    tool_name: str,
) -> dict[str, Any] | None:
    for item in reversed(turn_tool_history or []):
        if str((item or {}).get("tool_name") or "").strip() != tool_name:
            continue
        result = (item or {}).get("result")
        if isinstance(result, dict) and not result.get("error"):
            return result
    return None


def _context_sub_agent_depth(context_snapshot: dict[str, Any] | None) -> int:
    if not isinstance(context_snapshot, dict):
        return 0
    try:
        return max(0, int(context_snapshot.get("sub_agent_depth") or 0))
    except (TypeError, ValueError):
        return 0


_READ_ONLY_CHILD_MUTATION_TOOLS = {
    "apply_patch_workspace",
    "edit_workspace_file",
    "multi_edit_workspace_file",
    "run_openrewrite_recipe",
    "write_workspace_file",
}


def _successful_tool_items(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    successful: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        if isinstance(result, dict) and result.get("error"):
            continue
        successful.append(item)
    return successful


def _extract_child_evidence_paths(items: list[dict[str, Any]] | None) -> list[str]:
    paths: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in paths and "\n" not in text and len(paths) < 12:
            paths.append(text)

    def walk(value: Any) -> None:
        if len(paths) >= 12:
            return
        if isinstance(value, dict):
            for key in ("path", "relative_path", "file", "file_path"):
                add(value.get(key))
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value[:25]:
                walk(nested)
        elif isinstance(value, str) and ("/" in value or value.endswith((".java", ".xml", ".yml", ".yaml", ".md"))):
            add(value)

    for item in items or []:
        if not isinstance(item, dict):
            continue
        walk(item.get("parameters"))
        walk(item.get("result"))
    return paths


def _latest_successful_tool(history: list[dict[str, Any]], tool_name: str) -> dict[str, Any] | None:
    for item in reversed(history or []):
        if not isinstance(item, dict) or str(item.get("tool_name") or "").strip() != tool_name:
            continue
        result = item.get("result")
        if isinstance(result, dict) and not result.get("error"):
            return item
    return None


def _read_only_child_wrapup_content(
    *,
    current_user_message: str,
    history: list[dict[str, Any]],
) -> str:
    successful_tools = _successful_tool_items(history)
    tool_names: list[str] = []
    for item in successful_tools:
        name = str(item.get("tool_name") or "").strip()
        if name and name not in tool_names:
            tool_names.append(name)
    paths = _extract_child_evidence_paths(successful_tools)
    lines = [
        render_prompt(
            "answer.child_wrapup.summary",
            scope=str(current_user_message or "").strip()[:500],
            tool_count=len(successful_tools),
        )
    ]
    if tool_names:
        lines.append(render_prompt("answer.child_wrapup.tools", tool_names=", ".join(tool_names[:10])))
    if paths:
        lines.append(render_prompt("answer.child_wrapup.paths_header"))
        lines.extend(f"- {path}" for path in paths[:12])
    lines.extend(["", render_prompt("answer.child_wrapup.closing")])
    return "\n".join(lines)


def _should_finish_read_only_child(
    *,
    context_snapshot: dict[str, Any],
    current_allowed_tool_names: set[str],
    history: list[dict[str, Any]],
) -> bool:
    if _context_sub_agent_depth(context_snapshot) <= 0:
        return False
    allowed = {str(tool).strip() for tool in (current_allowed_tool_names or set()) if str(tool).strip()}
    if allowed.intersection(_READ_ONLY_CHILD_MUTATION_TOOLS):
        return False
    successful_tools = _successful_tool_items(history)
    if len(successful_tools) >= 12:
        return True
    repeated_grep_count = sum(1 for item in successful_tools if str(item.get("tool_name") or "") == "grep_workspace")
    return repeated_grep_count >= 8
