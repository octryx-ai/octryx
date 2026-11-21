"""Document flow summary of a coordinator run, read from its successful tool calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import Session, ToolCall
from .sub_agent_group.evidence import extract_sub_agent_evidence_counts


def _successful_tool_call_rows(tool_calls: list[ToolCall], tool_name: str) -> list[ToolCall]:
    return [
        row
        for row in tool_calls
        if str(row.tool_name or "").strip() == tool_name and str(row.status or "").strip().lower() == "success"
    ]


def _coordinator_path_from_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("relative_path", "file_path", "path", "output_path"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _is_document_plan_path(path: str) -> bool:
    normalized = str(path or "").strip().lower()
    if not normalized.endswith(".json"):
        return False
    name = Path(normalized).name
    return "plan" in name and ("document" in name or "report" in name or "research" in name)


def _build_document_flow_summary(
    root_session: Session,
    *,
    tool_calls: list[ToolCall],
) -> dict[str, str | int | bool | None] | None:
    metadata = dict(root_session.metadata_ or {})
    routing_intent = str(metadata.get("routing_intent") or "").strip().lower()
    source_bundle_count = len(_successful_tool_call_rows(tool_calls, "ingest_document_source"))
    build_rows = _successful_tool_call_rows(tool_calls, "build_word_template_script")
    if routing_intent != "documentation" and source_bundle_count == 0 and not build_rows:
        return None

    artifact_path = ""
    if build_rows:
        artifact_path = _coordinator_path_from_payload(build_rows[-1].result) or _coordinator_path_from_payload(
            build_rows[-1].parameters
        )

    plan_written = any(
        _is_document_plan_path(
            _coordinator_path_from_payload(row.parameters) or _coordinator_path_from_payload(row.result)
        )
        for row in _successful_tool_call_rows(tool_calls, "write_workspace_file")
    )
    document_validated = False
    accepted_subthread_count: int | None = None
    rejected_subthread_count: int | None = None
    validation_tool_names = ("validate_office_document", "get_office_document_info", "read_office_document")
    for tool_name in validation_tool_names:
        for row in _successful_tool_call_rows(tool_calls, tool_name):
            candidate_path = _coordinator_path_from_payload(row.parameters) or _coordinator_path_from_payload(
                row.result
            )
            if artifact_path and candidate_path and candidate_path != artifact_path:
                continue
            document_validated = True
            break
        if document_validated:
            break

    subthread_context_rows = _successful_tool_call_rows(tool_calls, "get_context_from_subthreads")
    if subthread_context_rows:
        accepted_subthread_count, rejected_subthread_count = extract_sub_agent_evidence_counts(
            subthread_context_rows[-1].result
        )

    summary = {
        "flow_type": "research_document" if source_bundle_count > 0 else "generic_document",
        "source_bundle_count": source_bundle_count,
        "plan_written": plan_written,
        "document_built": bool(build_rows),
        "document_validated": document_validated,
        "artifact_path": artifact_path or None,
    }
    if accepted_subthread_count is not None:
        summary["accepted_subthread_count"] = accepted_subthread_count
    if rejected_subthread_count is not None:
        summary["rejected_subthread_count"] = rejected_subthread_count
    return summary
