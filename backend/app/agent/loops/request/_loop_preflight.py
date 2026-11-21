"""Coding preflight analysis helpers for the standard agent loop.

Explicit-first: coding preflight tool planning is driven by the turn's capability/agent mode
(``change``/``coding``) and the workspace state, never by prompt-text regex matching; a workflow
is selected explicitly.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from ....tools.tool_names import CODING_PREFLIGHT_TOOL_NAMES, ToolName

_CODING_PREFLIGHT_TOOLS: frozenset[ToolName] = CODING_PREFLIGHT_TOOL_NAMES
_IDENTIFIER_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
_IDENTIFIER_STOPWORDS = {
    "about", "after", "agent", "analysis", "change", "code", "coding", "create", "file", "function", "implement",
    "implementation", "local", "make", "project", "repo", "repository", "source", "symbol", "test", "tests", "turn",
    "user", "workspace",
}
_CODING_CHANGE_TOOL_NAMES = {
    "write_workspace_file",
    "edit_workspace_file",
    "multi_edit_workspace_file",
    "apply_patch_workspace",
    "run_openrewrite_recipe",
}
_CODING_DISCOVERY_PREFLIGHT_TOOL_NAMES = _CODING_PREFLIGHT_TOOLS - {
    ToolName.BOOTSTRAP_WORKSPACE_REPOSITORY,
    ToolName.PREPARE_BITBUCKET_REPOSITORY,
}


def _workspace_has_reasonable_repo_root(workspace_root: str | None) -> bool:
    if not workspace_root:
        return False
    try:
        root = Path(workspace_root).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    if not root.exists() or not root.is_dir():
        return False
    if (root / ".git").exists():
        return True
    # Empty workspaces still need repository-first bootstrapping for new coding tasks.
    if not any(root.iterdir()):
        return True
    for marker in ("src", "app", "tests", "test", "package.json", "pyproject.toml", "pom.xml", "go.mod", "Cargo.toml"):
        if (root / marker).exists():
            return True
    return any(root.iterdir())


def _workspace_root_needs_bootstrap(workspace_root: str | None) -> bool:
    if not workspace_root:
        return False
    try:
        root = Path(workspace_root).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    if not root.exists() or not root.is_dir():
        return False
    if (root / ".git").exists():
        return False
    return True


def _is_probable_coding_change_request(
    *,
    capability_type: str,
    user_message: str,
    workspace_root: str | None,
) -> bool:
    """Whether the turn is a coding change turn.

    Mode-driven only: the capability/agent mode must be ``change``/``coding``
    and the workspace must look like a repository. The prompt text is never
    inspected (there is no keyword gating).
    """
    if str(capability_type or "").strip().lower() not in {"change", "coding"}:
        return False
    if not _workspace_has_reasonable_repo_root(workspace_root):
        return False
    return bool(str(user_message or "").strip())


def _extract_code_search_seed(user_message: str) -> str:
    text = str(user_message or "").strip()
    if not text:
        return ""
    candidates = _IDENTIFIER_PATTERN.findall(text)
    ranked: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip()
        lowered = normalized.lower()
        if lowered in _IDENTIFIER_STOPWORDS:
            continue
        if lowered.startswith(("http", "www")):
            continue
        if normalized not in ranked:
            ranked.append(normalized)
    return ranked[0] if ranked else ""


def _is_governed_work_plan_execution(user_message: str) -> bool:
    normalized = str(user_message or "").strip().lower()
    return (
        "governed coding agent" in normalized
        and "approved work plan" in normalized
        and "approved repositories and paths" in normalized
    )


def _preflight_tool_call(name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": str(uuid.uuid4()), "function": {"name": name, "arguments": json.dumps(arguments)}}]


def _has_untested_change(turn_tool_history: list[dict[str, Any]]) -> bool:
    """Whether the latest successful change comes after the latest test-suite run."""
    last_change_index = -1
    last_test_index = -1
    for index, item in enumerate(turn_tool_history or []):
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        result = item.get("result")
        if tool_name in _CODING_CHANGE_TOOL_NAMES:
            if isinstance(result, dict) and result.get("error"):
                continue
            last_change_index = index
            continue
        if tool_name != "run_test_suite" or not isinstance(result, dict):
            continue
        last_test_index = index
    return last_change_index >= 0 and last_test_index < last_change_index


def _plan_discovery_preflight_call(
    *,
    user_message: str,
    workspace_root: str | None,
    allowed_tool_names: set[str],
    seen_tool_names: set[str],
) -> list[dict[str, Any]] | None:
    if (
        _workspace_root_needs_bootstrap(workspace_root)
        and ToolName.BOOTSTRAP_WORKSPACE_REPOSITORY in allowed_tool_names
        and ToolName.BOOTSTRAP_WORKSPACE_REPOSITORY not in seen_tool_names
    ):
        return _preflight_tool_call(ToolName.BOOTSTRAP_WORKSPACE_REPOSITORY, {})
    if seen_tool_names & (_CODING_DISCOVERY_PREFLIGHT_TOOL_NAMES - {ToolName.ANALYZE_WORKSPACE_REPOSITORY}):
        return None
    if "analyze_workspace_repository" in allowed_tool_names and "analyze_workspace_repository" not in seen_tool_names:
        return _preflight_tool_call("analyze_workspace_repository", {"path": "."})
    if (
        "code_search" in allowed_tool_names
        and "analyze_workspace_repository" in seen_tool_names
        and not seen_tool_names.intersection(
            _CODING_DISCOVERY_PREFLIGHT_TOOL_NAMES - {ToolName.ANALYZE_WORKSPACE_REPOSITORY}
        )
    ):
        seed = _extract_code_search_seed(user_message)
        if seed:
            return _preflight_tool_call("code_search", {"query": seed, "cwd": "."})
    return None


def _plan_coding_preflight_tool_calls(
    *,
    capability_type: str,
    user_message: str,
    workspace_root: str | None,
    allowed_tool_names: set[str],
    turn_tool_history: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    if not _is_probable_coding_change_request(
        capability_type=capability_type,
        user_message=user_message,
        workspace_root=workspace_root,
    ):
        return None
    seen_tool_names = {
        str((item or {}).get("tool_name") or "").strip() for item in (turn_tool_history or []) if isinstance(item, dict)
    }
    if "run_test_suite" in allowed_tool_names and _has_untested_change(turn_tool_history):
        return _preflight_tool_call("run_test_suite", {"path": "."})
    if _is_governed_work_plan_execution(user_message):
        return None
    return _plan_discovery_preflight_call(
        user_message=user_message,
        workspace_root=workspace_root,
        allowed_tool_names=allowed_tool_names,
        seen_tool_names=seen_tool_names,
    )


def _has_meaningful_coding_execution(turn_tool_history: list[dict[str, Any]] | None) -> bool:
    for item in turn_tool_history or []:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        if not tool_name or tool_name in _CODING_PREFLIGHT_TOOLS:
            continue
        result = item.get("result")
        if isinstance(result, dict) and result.get("error"):
            continue
        return True
    return False


def _has_attempted_knowledge_lookup(turn_tool_history: list[dict[str, Any]] | None) -> bool:
    for item in turn_tool_history or []:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        if tool_name not in {"knowledge_search"}:
            continue
        return True
    return False


def _skip_missing_evidence_for_workflow(
    workflow_contract: dict[str, Any] | None,
    *,
    turn_tool_history: list[dict[str, Any]] | None,
) -> bool:
    if not isinstance(workflow_contract, dict) or not workflow_contract:
        return False
    workflow_id = str(workflow_contract.get("workflow_id") or "").strip()
    if workflow_id == "knowledge_request" and _has_attempted_knowledge_lookup(turn_tool_history):
        return True
    return False


def _latest_successful_tool_result_from_history(
    turn_tool_history: list[dict[str, Any]] | None, tool_name: str
) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for item in turn_tool_history or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() != tool_name:
            continue
        result = item.get("result")
        if isinstance(result, dict) and not result.get("error"):
            latest = result
    return latest


def _latest_successful_tool_result_from_results(
    tool_results: list[dict[str, Any]] | None,
    tool_name: str,
) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() != tool_name:
            continue
        result = item.get("result")
        if isinstance(result, dict) and not result.get("error"):
            latest = result
    return latest


__all__ = [
    "_workspace_has_reasonable_repo_root",
    "_is_probable_coding_change_request",
    "_extract_code_search_seed",
    "_plan_coding_preflight_tool_calls",
    "_has_meaningful_coding_execution",
    "_skip_missing_evidence_for_workflow",
    "_latest_successful_tool_result_from_history",
    "_latest_successful_tool_result_from_results",
]
