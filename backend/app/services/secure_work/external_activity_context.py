from __future__ import annotations

import json
from typing import Any

from ..prompt_catalog import render_prompt
from .jira_values import object_value

MAX_CONTEXT_BYTES = 6500
MAX_EVENTS = 16


def build_external_activity_context(source_fields: dict[str, Any]) -> dict[str, Any]:
    activities = [object_value(entry) for entry in _list(source_fields.get("external_activity"))]
    activities = [entry for entry in activities if entry]
    compact_events = [_compact_activity(entry) for entry in activities[:MAX_EVENTS]]
    context = {
        "event_count": len(activities),
        "requires_replan_count": sum(1 for entry in activities if entry.get("requires_replan")),
        "source_evidence_stale_count": sum(1 for entry in activities if entry.get("source_evidence_stale")),
        "sources": sorted({_string(entry.get("source")) for entry in activities if _string(entry.get("source"))}),
        "latest_events": compact_events,
        "current_flags": {
            "requires_replan": bool(source_fields.get("requires_replan")),
            "source_evidence_stale": bool(source_fields.get("source_evidence_stale")),
            "externally_modified": bool(source_fields.get("externally_modified")),
        },
        "replan_reason": object_value(source_fields.get("external_replan_reason")),
        "agent_instruction": render_prompt("secure_work.external_activity.instruction"),
    }
    return _bound_context(context)


def _compact_activity(activity: dict[str, Any]) -> dict[str, Any]:
    issue = object_value(activity.get("issue"))
    page = object_value(activity.get("page"))
    document = object_value(activity.get("document"))
    repository = object_value(activity.get("repository"))
    pull_request = object_value(activity.get("pull_request"))
    commit = object_value(activity.get("commit"))
    return _drop_empty(
        {
            "event_id": activity.get("event_id"),
            "source": activity.get("source"),
            "event_type": activity.get("event_type"),
            "external_id": activity.get("external_id"),
            "actor": activity.get("actor"),
            "occurred_at": activity.get("occurred_at"),
            "received_at": activity.get("received_at"),
            "affected_object": _affected_object(
                issue=issue,
                page=page,
                document=document,
                repository=repository,
                branch=activity.get("branch"),
                pull_request=pull_request,
            ),
            "commit": _drop_empty({"hash": commit.get("hash"), "message": _bounded_text(commit.get("message"), 240)}),
            "matched_by": _string_list(activity.get("matched_by")),
            "rule_decisions": _compact_rule_decisions(activity.get("rule_decisions")),
            "resulting_actions": _string_list(activity.get("resulting_actions")),
            "source_evidence_stale": bool(activity.get("source_evidence_stale")),
            "requires_replan": bool(activity.get("requires_replan")),
        }
    )


def _affected_object(
    *,
    issue: dict[str, Any],
    page: dict[str, Any],
    document: dict[str, Any],
    repository: dict[str, Any],
    branch: Any,
    pull_request: dict[str, Any],
) -> dict[str, Any]:
    if issue:
        return _drop_empty({"type": "jira_issue", "key": issue.get("key"), "title": issue.get("summary")})
    if page:
        return _drop_empty({"type": "confluence_page", "id": page.get("id"), "title": page.get("title")})
    if document:
        return _drop_empty({"type": "knowledge_document", "key": document.get("key"), "title": document.get("title")})
    if repository or branch or pull_request:
        return _drop_empty(
            {
                "type": "code",
                "repository": repository.get("slug") or repository.get("name"),
                "branch": branch,
                "pull_request": pull_request.get("url") or pull_request.get("id"),
            }
        )
    return {}


def _compact_rule_decisions(value: Any) -> list[dict[str, Any]]:
    decisions = [object_value(entry) for entry in _list(value)]
    return [
        _drop_empty(
            {
                "rule_id": decision.get("rule_id"),
                "rule_name": decision.get("rule_name"),
                "decision": decision.get("decision"),
                "actions": _string_list(decision.get("actions")),
                "status": decision.get("status"),
            }
        )
        for decision in decisions[:8]
        if decision
    ]


def _bound_context(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(value, default=str)
    if len(encoded.encode("utf-8")) <= MAX_CONTEXT_BYTES:
        return value
    bounded = dict(value)
    events = list(bounded.get("latest_events") or [])
    while (
        events
        and len(json.dumps({**bounded, "latest_events": events}, default=str).encode("utf-8")) > MAX_CONTEXT_BYTES
    ):
        events.pop()
    bounded["latest_events"] = events
    bounded["truncated"] = True
    return bounded


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    return [_string(entry) for entry in _list(value) if _string(entry)]


def _bounded_text(value: Any, limit: int) -> str | None:
    text = _string(value)
    if text is None:
        return None
    return text[:limit]


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: current for key, current in value.items() if current not in (None, "", [], {})}
