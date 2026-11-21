"""Runtime-failure salvage from the office, presentation and summary artifacts a failed turn produced."""

from __future__ import annotations

from typing import Any

from ....models.runtime.audit import ToolCall
from ._loop_message_response_policy import (
    build_runtime_salvage_office_artifact_message,
    build_runtime_salvage_outline_from_evidence_message,
    build_runtime_salvage_presentation_message,
    build_runtime_salvage_weekly_summary_message,
)

_PRESENTATION_MARKERS = ("presentation", "powerpoint", "ppt", "slide", "slides", "deck")
_KNOWLEDGE_EVIDENCE_TOOLS = {"knowledge_search", "search_confluence", "get_confluence_page", "read_bitbucket_file"}
_OFFICE_INSPECTION_TOOLS = ("validate_office_document", "get_office_document_info", "read_office_document")


def tool_result_payload(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    preview = result.get("preview")
    compact_result = preview.get("compact_result") if isinstance(preview, dict) else None
    return compact_result if isinstance(compact_result, dict) else result


def _latest_successful_tool_result(tool_calls: list[ToolCall], tool_name: str) -> dict[str, Any]:
    for tool_call in tool_calls:
        if str(tool_call.tool_name or "").strip() != tool_name:
            continue
        result = tool_result_payload(tool_call.result)
        if result:
            return result
    return {}


def _first_call_with_result(tool_calls: list[ToolCall], tool_name: str) -> ToolCall | None:
    return next(
        (
            tool_call
            for tool_call in tool_calls
            if str(tool_call.tool_name or "").strip() == tool_name and isinstance(tool_call.result, dict)
        ),
        None,
    )


def _office_artifact_paths(recent_tool_calls: list[ToolCall]) -> tuple[str, str, str]:
    """Doc type and path of the latest office document, and the path of the latest Word build."""
    create_office_call = _first_call_with_result(recent_tool_calls, "create_office_document")
    parameters = (
        create_office_call.parameters
        if create_office_call is not None and isinstance(create_office_call.parameters, dict)
        else {}
    )
    result = tool_result_payload(create_office_call.result if create_office_call is not None else None)
    document_build_call = _first_call_with_result(recent_tool_calls, "build_word_template_script")
    document_build_result = tool_result_payload(
        document_build_call.result if document_build_call is not None else None
    )
    document_relative_path = str(
        document_build_result.get("relative_path") or document_build_result.get("file_path") or ""
    ).strip()
    doc_type = str(parameters.get("doc_type") or result.get("file_type") or "").strip().lower()
    relative_path = str(result.get("relative_path") or result.get("file_path") or "").strip()
    return doc_type, relative_path, document_relative_path


def _count_items(result: dict[str, Any]) -> int:
    if not isinstance(result, dict):
        return 0
    for key in ("items", "results", "tickets", "commits", "pages", "updates"):
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _weekly_summary_salvage(recent_tool_calls: list[ToolCall]) -> str:
    jira_result = _latest_successful_tool_result(recent_tool_calls, "search_jira_tickets")
    bitbucket_result = _latest_successful_tool_result(recent_tool_calls, "list_recent_bitbucket_commits")
    confluence_result = _latest_successful_tool_result(recent_tool_calls, "search_confluence")
    return build_runtime_salvage_weekly_summary_message(
        jira_count=_count_items(jira_result),
        bitbucket_count=_count_items(bitbucket_result),
        confluence_count=_count_items(confluence_result),
    )


def build_artifact_salvage_answer(*, user_request: str, recent_tool_calls: list[ToolCall]) -> str:
    """The salvage answer for a turn that produced (or asked for) an office artifact, or ``""``."""
    doc_type, relative_path, document_relative_path = _office_artifact_paths(recent_tool_calls)
    tool_names = {
        str(tool_call.tool_name or "").strip()
        for tool_call in recent_tool_calls
        if str(tool_call.tool_name or "").strip()
    }
    normalized_request = user_request.lower()
    wants_presentation = any(marker in normalized_request for marker in _PRESENTATION_MARKERS)
    has_knowledge_evidence = bool(tool_names.intersection(_KNOWLEDGE_EVIDENCE_TOOLS))
    if doc_type == "pptx" or relative_path.lower().endswith(".pptx"):
        topic = user_request or "the requested topic"
        return build_runtime_salvage_presentation_message(topic=topic, relative_path=relative_path)
    if wants_presentation and has_knowledge_evidence:
        return build_runtime_salvage_outline_from_evidence_message()
    wants_weekly_summary = all(marker in normalized_request for marker in ("jira", "bitbucket", "confluence")) and any(
        marker in normalized_request for marker in ("summary", "weekly", "week")
    )
    if wants_weekly_summary:
        return _weekly_summary_salvage(recent_tool_calls)
    if document_relative_path and any(tool_name in tool_names for tool_name in _OFFICE_INSPECTION_TOOLS):
        return build_runtime_salvage_office_artifact_message(relative_path=document_relative_path)
    if relative_path:
        return build_runtime_salvage_office_artifact_message(relative_path=relative_path)
    return ""


__all__ = ["build_artifact_salvage_answer", "tool_result_payload"]
