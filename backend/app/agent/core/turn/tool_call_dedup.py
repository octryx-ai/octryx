"""Skip a read-only workspace tool call that repeats an identical earlier read in the same turn."""

from __future__ import annotations

import json
from typing import Any

from ....services.prompt_catalog import render_prompt
from ....tools.tool_names import ToolName
from ...loops.control._loop_progress_quality import duplicate_read_only_progress_event

_READ_ONLY_DEDUP_TOOL_NAMES = {
    ToolName.LIST_WORKSPACE_DIRECTORY,
    ToolName.READ_WORKSPACE_FILE,
    ToolName.GLOB_WORKSPACE_FILES,
    ToolName.GREP_WORKSPACE,
    ToolName.LIST_WORKSPACE_GIT_COMMITS,
}

# A workspace change after a read makes its earlier result stale; a fresh read is then never skipped.
_WORKSPACE_MUTATING_TOOL_NAMES = {
    ToolName.WRITE_WORKSPACE_FILE,
    ToolName.EDIT_WORKSPACE_FILE,
    ToolName.MULTI_EDIT_WORKSPACE_FILE,
    ToolName.APPLY_PATCH_WORKSPACE,
    ToolName.LINT_AND_FORMAT_WORKSPACE,
    ToolName.RUN_CLI_COMMAND,
    ToolName.BOOTSTRAP_WORKSPACE_REPOSITORY,
}
_DUPLICATE_EXCERPT_CHARS = 4000


def _canonical_tool_args(tool_args: dict[str, Any]) -> str:
    return json.dumps(tool_args or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _compact_duplicate_prior_result(prior_result: dict[str, Any]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for key in (
        "path",
        "relative_path",
        "query",
        "pattern",
        "count",
        "returned_count",
        "omitted_count",
        "content_truncated",
        "returned_chars",
        "returned_line_count",
        "size_bytes",
    ):
        if key in prior_result:
            evidence[key] = prior_result[key]

    content = prior_result.get("content_excerpt")
    if content is None:
        content = prior_result.get("content")
    if isinstance(content, str) and content:
        evidence["content_excerpt"] = content[:_DUPLICATE_EXCERPT_CHARS]

    entries = prior_result.get("entries")
    if isinstance(entries, list) and entries:
        evidence["entries"] = entries[:30]

    matches = prior_result.get("matches")
    if isinstance(matches, list) and matches:
        evidence["matches"] = matches[:30]

    return evidence


def duplicate_read_only_tool_result(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    turn_tool_history: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if tool_name not in _READ_ONLY_DEDUP_TOOL_NAMES:
        return None
    current_signature = _canonical_tool_args(tool_args)
    for item in reversed(turn_tool_history or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "") in _WORKSPACE_MUTATING_TOOL_NAMES:
            return None  # the workspace changed since any earlier identical read
        if str(item.get("tool_name") or "") != tool_name:
            continue
        prior_params = item.get("params") if isinstance(item.get("params"), dict) else {}
        if _canonical_tool_args(prior_params) != current_signature:
            continue
        prior_result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if prior_result.get("error"):
            return None
        content = prior_result.get("content")
        if isinstance(content, str) and len(content) > _DUPLICATE_EXCERPT_CHARS:
            return None  # a skip would hand back less than the read returned; reread instead
        prior_evidence = _compact_duplicate_prior_result(prior_result)
        return {
            "status": "duplicate_skipped",
            "tool_name": tool_name,
            "parameters": tool_args,
            "progress_quality_event": duplicate_read_only_progress_event(tool_name=tool_name, tool_args=tool_args),
            "message": render_prompt("tool_guard.turn.duplicate_read_only"),
            "prior_evidence": prior_evidence,
            "prior_result_keys": sorted(str(key) for key in prior_result.keys())[:12],
        }
    return None
