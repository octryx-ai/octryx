"""Message builder helpers for the standard agent loop."""

from __future__ import annotations

import json
import re
from typing import Any

from ....services.prompt_catalog import render_prompt
from ....services.response_guard_policy import CODING_INTENT_ONLY_PATTERN
from ....tools.tool_names import ToolName
from ._loop_message_response_policy import build_tool_execution_status_message


def _looks_like_coding_intent_only_response(content: str) -> bool:
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    if not text:
        return False
    if "```" in text:
        return False
    return bool(CODING_INTENT_ONLY_PATTERN.search(text))


def _has_awaiting_subagent_result(tool_results: list[dict[str, Any]]) -> bool:
    for item in tool_results:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        result = item.get("result")
        if not isinstance(result, dict):
            continue
        if str(result.get("status") or "").strip().lower() == "awaiting_subagents":
            return True
        if tool_name == "spawn_sub_agent" and str(result.get("sub_agent_group_id") or "").strip():
            return True
    return False


def _has_pending_clarification_result(tool_results: list[dict[str, Any]]) -> bool:
    """Detect if any tool returned a clarification pause status."""
    for item in tool_results:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        if not isinstance(result, dict):
            continue
        if result.get("status") == "paused" and result.get("paused"):
            return True
    return False


def _build_tool_execution_status_message(tool_calls: list[dict[str, Any]] | None) -> str:
    tool_names: list[str] = []
    for tool_call in tool_calls or []:
        function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        tool_name = str(function.get("name") or "").strip()
        if tool_name == ToolName.BATCH:
            raw_arguments = function.get("arguments")
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else {}
            except json.JSONDecodeError:
                arguments = {}
            invocations = arguments.get("invocations") if isinstance(arguments, dict) else []
            if isinstance(invocations, list):
                for invocation in invocations:
                    if not isinstance(invocation, dict):
                        continue
                    nested_name = str(invocation.get("tool_name") or "").strip()
                    if (
                        nested_name
                        and nested_name not in {"batch", "load_tool_artifact", "release_context"}
                        and nested_name not in tool_names
                    ):
                        tool_names.append(nested_name)
            continue
        if tool_name in {"load_tool_artifact", "release_context"}:
            continue
        if tool_name and tool_name not in tool_names:
            tool_names.append(tool_name)
    return build_tool_execution_status_message(tool_names=tool_names)


def _build_workflow_artifact_ready_message(workflow_contract: dict[str, Any] | None) -> str:
    workflow_id = (
        str((workflow_contract or {}).get("workflow_id") or "").strip().lower()
        if isinstance(workflow_contract, dict)
        else ""
    )
    if workflow_id == "knowledge_request":
        return render_prompt("loop.artifact_ready.knowledge")
    artifact_path = (
        str((workflow_contract or {}).get("artifact_path") or "").strip() if isinstance(workflow_contract, dict) else ""
    )
    if artifact_path:
        return render_prompt("loop.artifact_ready.at_path", artifact_path=artifact_path)
    return render_prompt("loop.artifact_ready.no_path")


__all__ = [
    "_looks_like_coding_intent_only_response",
    "_has_awaiting_subagent_result",
    "_build_tool_execution_status_message",
    "_build_workflow_artifact_ready_message",
]
