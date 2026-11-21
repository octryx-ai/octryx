from __future__ import annotations

from typing import Any

from app.services.answer_evidence.fields import source_subset
from app.services.tool_result_compression.budget import COMPACT_RESULT_TOKEN_BUDGET_KEY
from app.services.tool_result_compression.config import build_truncated_excerpt, clamp_config_int
from app.services.tool_result_compression.support import _extract_html_headings, _strip_html


def _truncate_knowledge_value(value: Any, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def _jira_user_name(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("displayName") or value.get("name") or value.get("emailAddress")
    return value


def _compact_count_map(values: dict[str, int], *, limit: int) -> dict[str, int]:
    return dict(sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit])


def _increment_count(values: dict[str, int], value: Any) -> None:
    normalized = str(value or "").strip()
    if not normalized:
        return
    values[normalized] = values.get(normalized, 0) + 1


def _compress_jira_search(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    max_items = clamp_config_int(config, "max_items", default=20, minimum=1, maximum=60)
    max_summary_chars = clamp_config_int(config, "max_summary_chars", default=140, minimum=80, maximum=400)
    compact_token_budget = clamp_config_int(
        config,
        "compact_token_budget",
        default=4500,
        minimum=3000,
        maximum=8000,
    )
    items: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    issue_type_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    assignee_counts: dict[str, int] = {}
    reporter_counts: dict[str, int] = {}
    creator_counts: dict[str, int] = {}
    for ticket in result.get("results") or []:
        ticket_key = ticket.get("key") or ticket.get("ticket_id") or ticket.get("id")
        status = (
            (ticket.get("status") or {}).get("name") if isinstance(ticket.get("status"), dict) else ticket.get("status")
        )
        assignee = _jira_user_name(ticket.get("assignee"))
        reporter = _jira_user_name(ticket.get("reporter"))
        creator = _jira_user_name(ticket.get("creator"))
        priority = (
            (ticket.get("priority") or {}).get("name")
            if isinstance(ticket.get("priority"), dict)
            else ticket.get("priority")
        )
        issue_type = (
            (ticket.get("issue_type") or ticket.get("issuetype") or {}).get("name")
            if isinstance(ticket.get("issue_type") or ticket.get("issuetype"), dict)
            else ticket.get("issue_type") or ticket.get("issuetype")
        )
        _increment_count(status_counts, status)
        _increment_count(issue_type_counts, issue_type)
        _increment_count(priority_counts, priority)
        _increment_count(assignee_counts, assignee)
        _increment_count(reporter_counts, reporter)
        _increment_count(creator_counts, creator)
        items.append(
            {
                "id": ticket.get("id") or ticket_key,
                "ticket_id": ticket.get("ticket_id") or ticket_key,
                "key": ticket_key,
                # The model cites what it reads: the source fields survive compression.
                **source_subset(ticket),
                "summary": _truncate_knowledge_value(ticket.get("summary"), max_chars=max_summary_chars),
                "status": status,
                "assignee": assignee,
                "reporter": reporter,
                "creator": creator,
                "priority": priority,
                "issue_type": issue_type,
                "created": ticket.get("created"),
                "updated": ticket.get("updated"),
            }
        )
    return {
        "query": result.get("query"),
        "jql": result.get("jql"),
        "api_version": result.get("api_version"),
        "total": result.get("total"),
        "count": len(items),
        "returned_count": min(len(items), max_items),
        "omitted_count": max(0, len(items) - max_items),
        "status_counts": _compact_count_map(status_counts, limit=12),
        "issue_type_counts": _compact_count_map(issue_type_counts, limit=12),
        "priority_counts": _compact_count_map(priority_counts, limit=8),
        "top_assignees": _compact_count_map(assignee_counts, limit=10),
        "top_reporters": _compact_count_map(reporter_counts, limit=10),
        "top_creators": _compact_count_map(creator_counts, limit=10),
        "results": items[:max_items],
        "answer_guidance": {
            "use_counts_before_examples": True,
            "raw_payload_available_as_artifact": True,
            "interpretation": "Counts describe the full returned Jira result set; results are representative examples.",
        },
        COMPACT_RESULT_TOKEN_BUDGET_KEY: compact_token_budget,
    }


def _compress_confluence_search(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    max_results = clamp_config_int(config, "max_results", default=8, minimum=1, maximum=20)
    items: list[dict[str, Any]] = []
    for item in (result.get("results") or [])[:max_results]:
        items.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "space_key": item.get("space_key"),
                "version": item.get("version"),
                "updated_by": item.get("updated_by"),
                "updated_when": item.get("updated_when"),
                "child_count": item.get("child_count"),
                "child_listing_complete": item.get("child_listing_complete"),
                "children": [
                    {
                        "id": child.get("id"),
                        "title": child.get("title"),
                        "version": child.get("version"),
                        "updated_by": child.get("updated_by"),
                        "updated_when": child.get("updated_when"),
                        **source_subset(child),
                    }
                    for child in (item.get("children") or [])[:3]
                    if isinstance(child, dict)
                ],
                "url": item.get("url"),
                **source_subset(item),
            }
        )
    return {
        "query": result.get("query"),
        "cql": result.get("cql"),
        "total": result.get("total"),
        "result_count": len(result.get("results") or []),
        "results": items,
    }


def _compress_confluence_page(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    max_headings = clamp_config_int(config, "max_headings", default=10, minimum=1, maximum=20)
    max_excerpt_chars = clamp_config_int(
        config,
        "max_excerpt_chars",
        default=1200,
        minimum=200,
        maximum=3000,
    )
    content = str(result.get("content") or "")
    text = _strip_html(content)
    return {
        "id": result.get("id"),
        "title": result.get("title"),
        "space_key": result.get("space_key"),
        "version": result.get("version"),
        "url": result.get("url"),
        **source_subset(result),
        "headings": _extract_html_headings(content, max_headings=max_headings),
        "excerpt": build_truncated_excerpt(text, max_chars=max_excerpt_chars),
        "text_length": len(text),
    }
