"""Atlassian-owned tool result compaction for model context.

Connector-owned module: the agent engine core carries no Jira, Bitbucket, or
Confluence payload knowledge. It resolves these compactors through the generic
registry in ``app.agent.engine.messages._tool_compaction_registry``; which tool
names exist and which payload shapes they produce is Atlassian connector
knowledge and stays here.
"""

from __future__ import annotations

from typing import Any

from app.services.answer_evidence.fields import source_subset

from ...agent.engine.messages._engine_message_helpers import _truncate_for_model
from ..tool_names import ToolName


def _increment_count(values: dict[str, int], value: Any) -> None:
    normalized = str(value or "").strip()
    if not normalized:
        return
    values[normalized] = values.get(normalized, 0) + 1


def _compact_count_map(values: dict[str, int], *, limit: int) -> dict[str, int]:
    return dict(sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit])


def _jira_field_name(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("displayName") or value.get("name") or value.get("emailAddress")
    return value


def compact_jira_ticket_result(result: dict[str, Any]) -> dict[str, Any]:
    fields = result.get("fields") if isinstance(result.get("fields"), dict) else {}
    return {
        "key": result.get("key") or result.get("ticket_id") or fields.get("key"),
        # The model cites what it reads: the source fields survive compaction.
        **source_subset(result),
        "id": result.get("id"),
        "url": result.get("url") or result.get("self"),
        "summary": _truncate_for_model(result.get("summary") or fields.get("summary") or "", 220),
        "description": _truncate_for_model(result.get("description") or fields.get("description") or "", 1400),
        "status": _jira_field_name(result.get("status") or fields.get("status")),
        "issue_type": _jira_field_name(result.get("issue_type") or result.get("issuetype") or fields.get("issuetype")),
        "priority": _jira_field_name(result.get("priority") or fields.get("priority")),
        "assignee": _jira_field_name(result.get("assignee") or fields.get("assignee")),
        "reporter": _jira_field_name(result.get("reporter") or fields.get("reporter")),
        "creator": _jira_field_name(result.get("creator") or fields.get("creator")),
        "labels": (result.get("labels") or fields.get("labels") or [])[:20],
        "fix_versions": [
            _jira_field_name(item)
            for item in (result.get("fix_versions") or result.get("fixVersions") or fields.get("fixVersions") or [])[:12]
        ],
        "updated": result.get("updated") or fields.get("updated"),
        "answer_guidance": {
            "raw_payload_available_as_artifact": True,
            "treat_jira_as_source_of_truth_for_task_scope": True,
        },
    }


def compact_jira_ticket_search_result(result: dict[str, Any]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    issue_type_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    assignee_counts: dict[str, int] = {}
    reporter_counts: dict[str, int] = {}
    creator_counts: dict[str, int] = {}
    compact_results = []
    for item in result.get("results") or []:
        status = _jira_field_name(item.get("status"))
        issue_type = _jira_field_name(item.get("issue_type") or item.get("issuetype"))
        priority = _jira_field_name(item.get("priority"))
        assignee = _jira_field_name(item.get("assignee"))
        reporter = _jira_field_name(item.get("reporter"))
        creator = _jira_field_name(item.get("creator"))
        _increment_count(status_counts, status)
        _increment_count(issue_type_counts, issue_type)
        _increment_count(priority_counts, priority)
        _increment_count(assignee_counts, assignee)
        _increment_count(reporter_counts, reporter)
        _increment_count(creator_counts, creator)
        if len(compact_results) >= 20:
            continue
        compact_results.append(
            {
                "ticket_id": item.get("ticket_id") or item.get("key") or item.get("id"),
                "key": item.get("key") or item.get("ticket_id"),
                **source_subset(item),
                "summary": _truncate_for_model(item.get("summary") or "", 140),
                "status": status,
                "assignee": assignee,
                "reporter": reporter,
                "creator": creator,
                "priority": priority,
                "issue_type": issue_type,
                "created": item.get("created"),
                "updated": item.get("updated"),
            }
        )
    return {
        "query": result.get("query"),
        "jql": _truncate_for_model(result.get("jql") or "", 240),
        "api_version": result.get("api_version"),
        "total": result.get("total"),
        "count": len(result.get("results") or []),
        "returned_count": len(compact_results),
        "omitted_count": max(0, len(result.get("results") or []) - len(compact_results)),
        "status_counts": _compact_count_map(status_counts, limit=12),
        "issue_type_counts": _compact_count_map(issue_type_counts, limit=12),
        "priority_counts": _compact_count_map(priority_counts, limit=8),
        "top_assignees": _compact_count_map(assignee_counts, limit=10),
        "top_reporters": _compact_count_map(reporter_counts, limit=10),
        "top_creators": _compact_count_map(creator_counts, limit=10),
        "results": compact_results,
        "answer_guidance": {
            "use_counts_before_examples": True,
            "raw_payload_available_as_artifact": True,
        },
    }


def compact_jira_release_bundle_result(result: dict[str, Any]) -> dict[str, Any]:
    created_tickets = []
    for item in (result.get("created_tickets") or [])[:20]:
        if not isinstance(item, dict):
            continue
        created_tickets.append(
            {
                "ticket_id": item.get("ticket_id"),
                "summary": item.get("summary"),
                "issue_type": item.get("issue_type"),
            }
        )
    updated_tickets = []
    for item in (result.get("updated_tickets") or [])[:20]:
        if not isinstance(item, dict):
            continue
        updated_tickets.append(
            {
                "ticket_id": item.get("ticket_id"),
                "updated_fields": list(item.get("updated_fields") or [])[:10],
            }
        )
    return {
        "project_key": result.get("project_key"),
        "release_name": result.get("release_name"),
        "release_date": result.get("release_date"),
        "version_id": result.get("version_id"),
        "version_created": bool(result.get("version_created")),
        "release_status": result.get("release_status"),
        "release_now": bool(result.get("release_now")),
        "created_ticket_count": result.get("created_ticket_count"),
        "updated_ticket_count": result.get("updated_ticket_count"),
        "created_tickets": created_tickets,
        "updated_tickets": updated_tickets,
    }


def compact_jira_version_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_key": result.get("project_key"),
        "name": result.get("name"),
        "version_id": result.get("version_id"),
        "release_date": result.get("release_date"),
        "status": result.get("status"),
    }


def register_result_compactors() -> None:
    """Register every Atlassian tool result compactor with the engine registry."""
    from ...agent.engine.messages._tool_compaction_registry import register_tool_result_compactor
    from .bitbucket_result_compaction import (
        compact_bitbucket_pull_request_result,
        compact_prepare_repository_result,
        compact_recent_bitbucket_commits_result,
    )

    register_tool_result_compactor("get_jira_ticket", compact_jira_ticket_result)
    register_tool_result_compactor("get_jira_ticket_details", compact_jira_ticket_result)
    register_tool_result_compactor(ToolName.SEARCH_JIRA_TICKETS, compact_jira_ticket_search_result)
    register_tool_result_compactor(ToolName.CREATE_JIRA_RELEASE_BUNDLE, compact_jira_release_bundle_result)
    register_tool_result_compactor(ToolName.CREATE_JIRA_VERSION, compact_jira_version_result)
    register_tool_result_compactor("get_bitbucket_pull_request", compact_bitbucket_pull_request_result)
    register_tool_result_compactor(ToolName.PREPARE_BITBUCKET_REPOSITORY, compact_prepare_repository_result)
    register_tool_result_compactor(ToolName.LIST_RECENT_BITBUCKET_COMMITS, compact_recent_bitbucket_commits_result)
