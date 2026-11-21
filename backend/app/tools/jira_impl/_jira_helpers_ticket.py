"""Ticket-focused Jira helpers."""

import re

from app.tools.context import ToolContext

from ...services.approval import ensure_approval_request
from ...services.change_preview import (
    build_change_request_fingerprint,
    build_tool_change_preview,
    consume_change_preview_grant,
    upsert_change_preview,
)
from ...services.request_analysis import effective_limit_from_request_analysis


def _ticket_summary(issue: dict[str, object]) -> dict[str, object]:
    fields = issue.get("fields", {})
    reporter = fields.get("reporter") or {}
    creator = fields.get("creator") or {}
    return {
        "ticket_id": issue.get("key"),
        "summary": fields.get("summary"),
        "status": (fields.get("status") or {}).get("name"),
        "assignee": (fields.get("assignee") or {}).get("displayName"),
        "reporter": reporter.get("displayName") if isinstance(reporter, dict) else None,
        "creator": creator.get("displayName") if isinstance(creator, dict) else None,
        "priority": (fields.get("priority") or {}).get("name"),
        "issue_type": (fields.get("issuetype") or {}).get("name"),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
    }


_REFERENCE_URL_PATTERN = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)


def _extract_ticket_references(ticket: dict[str, object], description: str) -> list[str]:
    references: list[str] = []
    raw_references = ticket.get("references")
    if isinstance(raw_references, list):
        for item in raw_references:
            value = str(item).strip()
            if value and value not in references:
                references.append(value)
    elif raw_references:
        value = str(raw_references).strip()
        if value:
            references.append(value)

    for match in _REFERENCE_URL_PATTERN.findall(description or ""):
        value = str(match).strip().rstrip(".,;")
        if value and value not in references:
            references.append(value)
    return references[:6]


def _effective_search_limit(params: dict[str, object], context: ToolContext) -> int:
    return effective_limit_from_request_analysis(
        snapshot=context.turn_context_snapshot,
        fallback_user_message=context.current_user_message,
        requested_limit=params.get("limit"),
        default_if_unspecified=100,
        hard_max=100,
    )


def _requires_change_approval(context: ToolContext) -> bool:
    mode = str(context.agent_mode_key or context.capability_type or "").strip().lower()
    return mode == "diagnosis"


async def _maybe_block_change_with_approval(
    tool_name: str,
    params: dict[str, object],
    context: ToolContext,
    *,
    action_title: str,
) -> dict[str, object] | None:
    if not _requires_change_approval(context):
        return None
    if await consume_change_preview_grant(
        context.db,
        session_id=context.session_id,
        tool_name=tool_name,
        payload=params,
        context=context,
    ):
        return None
    if context.db is None or not context.user_id:
        return None

    preview_payload = await build_tool_change_preview(tool_name, params, context)
    if preview_payload is None:
        preview_payload = {
            "kind": "jira",
            "title": action_title,
            "summary": action_title,
            "details": ["This Jira change requires approval before execution."],
        }
    approval = await ensure_approval_request(
        context.db,
        requested_by=context.user_id,
        session_id=context.session_id,
        action=f"Approve Jira change for {tool_name}",
        reason=preview_payload.get("summary") or action_title,
    )
    preview = await upsert_change_preview(
        context.db,
        tool_name=tool_name,
        preview_payload=preview_payload,
        request_fingerprint=build_change_request_fingerprint(tool_name, params),
        session_id=context.session_id,
        approval_id=approval.id,
    )
    return {
        "error": "Execution blocked pending Jira change approval.",
        "approval_required": True,
        "approval_id": approval.id,
        "approval_status": approval.status,
        "change_preview_id": preview.id,
        "change_preview": preview_payload,
        "tool_name": tool_name,
    }
