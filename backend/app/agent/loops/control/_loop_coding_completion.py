"""Helpers for concluding successful direct coding runs."""

from __future__ import annotations

import re
from typing import Any

from app.services.prompt_catalog import render_prompt

_CODING_CHANGE_TOOL_NAMES = {
    "write_workspace_file",
    "edit_workspace_file",
    "multi_edit_workspace_file",
    "apply_patch_workspace",
    "run_openrewrite_recipe",
}
_VERIFICATION_COMMAND_PATTERN = re.compile(r"\bmvn\b.*\b(clean\s+)?(package|verify|install)\b", re.IGNORECASE)


def _latest_green_test_result(tool_results: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for item in reversed(tool_results or []):
        if str((item or {}).get("tool_name") or "").strip() != "run_test_suite":
            continue
        result = (item or {}).get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        if result.get("all_green") is True:
            return result
    return None


def _command_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(part).strip() for part in value if str(part).strip())
    return str(value or "").strip()


def _latest_successful_verification_result(tool_results: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for item in reversed(tool_results or []):
        if str((item or {}).get("tool_name") or "").strip() != "run_cli_command":
            continue
        result = (item or {}).get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        exit_code = result.get("exit_code")
        if exit_code is None:
            exit_code = result.get("returncode")
        if int(exit_code or 0) != 0:
            continue
        command_text = _command_text(result.get("effective_command") or result.get("command"))
        if not _VERIFICATION_COMMAND_PATTERN.search(command_text):
            continue
        payload = dict(result)
        payload["command_text"] = command_text
        return payload
    return None


def _extract_changed_paths(turn_tool_history: list[dict[str, Any]] | None) -> list[str]:
    changed_paths: list[str] = []
    for item in turn_tool_history or []:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        if tool_name not in _CODING_CHANGE_TOOL_NAMES:
            continue
        result = item.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        path = str(result.get("relative_path") or result.get("path") or "").strip()
        if not path:
            continue
        if path not in changed_paths:
            changed_paths.append(path)
    return changed_paths


def build_direct_coding_completion_message(
    *,
    tool_results: list[dict[str, Any]] | None,
    turn_tool_history: list[dict[str, Any]] | None,
) -> str | None:
    green_test_result = _latest_green_test_result(tool_results)
    verification_result = _latest_successful_verification_result(tool_results)
    if not green_test_result and not verification_result:
        return None

    changed_paths = _extract_changed_paths(turn_tool_history)
    if not changed_paths:
        return None

    lines = [render_prompt("answer.coding.completed")]
    lines.append("")
    lines.append(render_prompt("answer.coding.updated_files"))
    for path in changed_paths[:8]:
        lines.append(f"- {path}")

    lines.append("")
    lines.append(render_prompt("answer.coding.verification"))
    if green_test_result:
        command_text = _command_text(green_test_result.get("command"))
        passed = int(green_test_result.get("passed") or 0)
        failed = int(green_test_result.get("failed") or 0)
        errors = int(green_test_result.get("errors") or 0)
        if command_text:
            lines.append(render_prompt("answer.coding.test_command", command_text=command_text))
        lines.append(render_prompt("answer.coding.test_counts", passed=passed, failed=failed, errors=errors))
    if verification_result:
        command_text = str(verification_result.get("command_text") or "").strip()
        if command_text:
            lines.append(render_prompt("answer.coding.verification_command", command_text=command_text))
    return "\n".join(lines)


__all__ = ["build_direct_coding_completion_message"]
