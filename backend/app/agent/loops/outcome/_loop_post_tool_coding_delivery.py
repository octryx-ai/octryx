"""Governed-coding delivery helpers for post-tool outcome handling.

Expected-path checks, the fresh read after a failed edit and the evidence budget guard for governed
coding runs; the forced delivery steps live in ``_loop_post_tool_delivery_progress``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ....services.secure_work.coding.verification_contract import is_governed_coding_contract
from ..control._loop_progress_quality import detect_tool_activity_stall
from ._loop_post_tool_history import _successful_tool_items

_GOVERNED_CODING_EVIDENCE_TOOLS = {
    "analyze_workspace_repository",
    "bash",
    "code_search",
    "get_git_diff",
    "grep_workspace",
    "list_workspace_directory",
    "prepare_bitbucket_repository",
    "read_workspace_file",
    "run_cli_command",
}
_GOVERNED_CODING_DELIVERY_TOOLS = {
    "apply_patch_workspace",
    "ask_clarification",
    "commit_and_push_repository_branch",
    "create_bitbucket_pull_request",
    "edit_workspace_file",
    "multi_edit_workspace_file",
    "run_openrewrite_recipe",
    "write_workspace_file",
}


def _governed_expected_paths(workflow_contract: Any) -> list[str]:
    """The approved expected paths: the workflow contract's (the secure-work applier writes them from the change
    units, ``verification_contract``)."""
    if not isinstance(workflow_contract, dict):
        return []
    return [str(path or "").strip() for path in (workflow_contract.get("expected_paths") or [])
            if str(path or "").strip()]


def _result_contains_path(result: dict[str, Any], expected_path: str) -> bool:
    expected = expected_path.strip().lstrip("/")
    if not expected:
        return False
    for key in ("relative_path", "path"):
        value = str(result.get(key) or "").strip().lstrip("/")
        if value == expected or value.endswith(f"/{expected}"):
            return True
    return False


def _governed_coding_expected_paths_ready(
    *,
    history: list[dict[str, Any]],
    workflow_contract: Any,
) -> dict[str, Any] | None:
    if not is_governed_coding_contract(workflow_contract):
        return None
    expected_paths = _governed_expected_paths(workflow_contract)
    if not expected_paths:
        return None
    successful = _successful_tool_items(history)
    if any(str(item.get("tool_name") or "").strip() in _GOVERNED_CODING_DELIVERY_TOOLS for item in successful):
        return None
    read_results = [
        item.get("result")
        for item in successful
        if str(item.get("tool_name") or "").strip() == "read_workspace_file" and isinstance(item.get("result"), dict)
    ]
    read_paths: list[str] = []
    for result in read_results:
        value = str(result.get("relative_path") or result.get("path") or "").strip()
        if value and value not in read_paths:
            read_paths.append(value)
    missing = [
        expected_path
        for expected_path in expected_paths
        if not any(_result_contains_path(result, expected_path) for result in read_results)
    ]
    if missing:
        return None
    return {"expected_paths": expected_paths, "read_paths": read_paths}


def _forced_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


def _forced_read_after_failed_governed_coding_edit(
    *,
    history: list[dict[str, Any]],
    workflow_contract: Any,
) -> list[dict[str, Any]] | None:
    if not is_governed_coding_contract(workflow_contract) or not history:
        return None
    latest = history[-1]
    if not isinstance(latest, dict):
        return None
    tool_name = str(latest.get("tool_name") or "").strip()
    if tool_name not in {"edit_workspace_file", "multi_edit_workspace_file"}:
        return None
    result = latest.get("result")
    if not isinstance(result, dict) or not result.get("error"):
        return None
    error = str(result.get("error") or "").lower()
    if "old_string not found" not in error and "edit 0 failed" not in error:
        return None
    params = latest.get("parameters") if isinstance(latest.get("parameters"), dict) else {}
    path = str(params.get("path") or params.get("file_path") or "").strip()
    if not path:
        return None
    return [_forced_tool_call("read_workspace_file", {"path": path, "max_chars": 24000})]


def _governed_coding_evidence_budget_exceeded(
    *,
    history: list[dict[str, Any]],
    limit: int,
    workflow_contract: Any,
    hard_limit: int | None = None,
) -> dict[str, Any] | None:
    if not is_governed_coding_contract(workflow_contract):
        return None
    stall = detect_tool_activity_stall(
        history=history,
        activity_tool_names=_GOVERNED_CODING_EVIDENCE_TOOLS,
        productive_tool_names=_GOVERNED_CODING_DELIVERY_TOOLS,
        limit=limit,
        hard_limit=hard_limit,
    )
    if stall is None:
        return None
    return {
        "evidence_tool_calls": stall["activity_tool_calls"],
        "limit": stall["limit"],
        "hard_limit": stall["hard_limit"],
        "hard_stop": stall["hard_stop"],
        "tool_counts": stall["tool_counts"],
        "progress_quality_event": stall,
    }
