"""Forced delivery progress of governed coding runs.

Once a governed coding run has changed the workspace, the delivery steps are forced in order: git diff check,
diff, commit and push, pull request. The commit and pull request texts are built here as well.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.prompt_catalog import render_prompt

from ....services.secure_work.coding.verification_contract import is_governed_coding_contract
from ._loop_post_tool_coding_delivery import _forced_tool_call
from ._loop_post_tool_history import _latest_successful_tool

_WORKSPACE_CHANGE_TOOLS = {
    "apply_patch_workspace",
    "edit_workspace_file",
    "multi_edit_workspace_file",
    "write_workspace_file",
}


def _has_successful_governed_coding_change(history: list[dict[str, Any]]) -> bool:
    for item in history or []:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        if tool_name not in _WORKSPACE_CHANGE_TOOLS:
            continue
        result = item.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        if tool_name == "apply_patch_workspace" and int(result.get("errors") or 0) > 0:
            continue
        return True
    return False


def _prepared_repo_result(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    item = _latest_successful_tool(history, "prepare_bitbucket_repository")
    result = item.get("result") if item else None
    return result if isinstance(result, dict) else None


def _has_successful_git_diff_check(history: list[dict[str, Any]], repo_path: str) -> bool:
    for item in history or []:
        if not isinstance(item, dict) or str(item.get("tool_name") or "").strip() != "run_cli_command":
            continue
        params = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        command = str(params.get("command") or result.get("command") or "").strip()
        cwd = str(params.get("cwd") or result.get("cwd") or "").strip()
        if command == "git diff --check" and cwd == repo_path and int(result.get("exit_code") or 0) == 0:
            return True
    return False


def _has_repo_diff(history: list[dict[str, Any]], repo_path: str) -> bool:
    for item in history or []:
        if not isinstance(item, dict) or str(item.get("tool_name") or "").strip() != "get_git_diff":
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if str(result.get("cwd") or "").strip() == repo_path and str(result.get("diff") or "").strip():
            return True
    return False


def _latest_pushed_commit(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    item = _latest_successful_tool(history, "commit_and_push_repository_branch")
    result = item.get("result") if item else None
    if isinstance(result, dict) and result.get("status") == "pushed":
        return result
    return None


def _has_created_pr(history: list[dict[str, Any]]) -> bool:
    item = _latest_successful_tool(history, "create_bitbucket_pull_request")
    result = item.get("result") if item else None
    return isinstance(result, dict) and str(result.get("status") or "").strip() == "created"


def _governed_coding_commit_message(current_user_message: str) -> str:
    source_key = re.search(r"Work Item:\s*([A-Z][A-Z0-9]+-\d+)", str(current_user_message or ""))
    title = re.search(r"Title:\s*([^\n]+)", str(current_user_message or ""))
    key_text = source_key.group(1).strip() if source_key else render_prompt("answer.delivery.commit_default_key")
    title_text = title.group(1).strip() if title else render_prompt("answer.delivery.commit_default_title")
    return f"{key_text}: {title_text}"[:120]


def _governed_coding_pr_title(current_user_message: str) -> str:
    return _governed_coding_commit_message(current_user_message)


def _governed_coding_pr_description(current_user_message: str, commit_result: dict[str, Any]) -> str:
    source_url = re.search(r"Source URL:\s*(\S+)", str(current_user_message or ""))
    lines = [
        render_prompt("answer.delivery.pr_header"),
        "",
        render_prompt("answer.delivery.pr_commit", head_commit=commit_result.get("head_commit")),
    ]
    if source_url:
        lines.extend(["", render_prompt("answer.delivery.pr_source", source_url=source_url.group(1).strip())])
    lines.extend(["", render_prompt("answer.delivery.pr_validation")])
    return "\n".join(lines)


def _forced_governed_coding_delivery_progress(
    *,
    current_user_message: str,
    history: list[dict[str, Any]],
    workflow_contract: Any,
) -> list[dict[str, Any]] | None:
    if not is_governed_coding_contract(workflow_contract):
        return None
    if not _has_successful_governed_coding_change(history):
        return None
    repo = _prepared_repo_result(history)
    repo_path = str((repo or {}).get("local_path") or "").strip()
    if not repo_path:
        return None
    if not _has_successful_git_diff_check(history, repo_path):
        return [_forced_tool_call("run_cli_command", {"command": "git diff --check", "cwd": repo_path})]
    if not _has_repo_diff(history, repo_path):
        return [_forced_tool_call("get_git_diff", {"cwd": repo_path})]
    pushed = _latest_pushed_commit(history)
    if not pushed:
        return [
            _forced_tool_call(
                "commit_and_push_repository_branch",
                {
                    "local_path": repo_path,
                    "branch_name": str((repo or {}).get("branch_name") or "").strip(),
                    "commit_message": _governed_coding_commit_message(current_user_message),
                },
            )
        ]
    if not _has_created_pr(history):
        return [
            _forced_tool_call(
                "create_bitbucket_pull_request",
                {
                    "project_key": str((repo or {}).get("project_key") or "").strip(),
                    "repo_slug": str((repo or {}).get("repo_slug") or "").strip(),
                    "from_branch": str(pushed.get("branch_name") or (repo or {}).get("branch_name") or "").strip(),
                    "title": _governed_coding_pr_title(current_user_message),
                    "description": _governed_coding_pr_description(current_user_message, pushed),
                },
            )
        ]
    return None
