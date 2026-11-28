from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ....models import WorkItemSyncConfig
from ....tools.jira_impl._jira_cloud import readable_body
from ..automation_eligibility import automation_policy_for_sync_config
from ..jira_values import (
    blank_to_none,
    list_value,
    name_value,
    object_value,
    parent_key,
    parse_datetime,
    project_key,
    source_url,
    string_list,
    text_or_none,
    user_value,
    watchers,
)
from .jira_item_details import bounded_raw, jira_detail_fields, status_category
from .stored_types import MappingSource, StoredStatusMapping


def item_preview(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source_fields_json") or {}
    return {
        "source_key": item["source_key"],
        "title": item["title"],
        "source_status": item.get("source_status"),
        # Where the issue lands, how that was decided, and who has it, per sample row.
        "work_state": item.get("work_state"),
        "mapping_source": (source.get("status_mapping") or {}).get("source"),
        "assignee_display": ((source.get("people") or {}).get("assignee") or {}).get("display"),
        "issue_type": item.get("issue_type"),
        "assignee": item.get("assignee"),
        "labels": item.get("labels_json") or [],
        "fix_versions": item.get("fix_versions_json") or [],
        "source_url": item.get("source_url"),
    }


def jira_issue_to_work_item_payload(issue: dict[str, Any], config: WorkItemSyncConfig) -> dict[str, Any]:
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    source_key = str(issue.get("key") or fields.get("key") or "").strip()
    if not source_key:
        raise HTTPException(status_code=422, detail="Jira issue key is required")
    status = issue.get("status") or fields.get("status")
    source_status = name_value(status)
    category = status_category(status)
    work_state, mapping_source = classify_jira_status(source_status, config, category=category)
    browse_url = blank_to_none(issue.get("browse_url") or issue.get("url"))
    status_mapping: StoredStatusMapping = {"source": mapping_source, "category": category}
    source_fields = {
        "raw": bounded_raw(issue),
        "field_mapping": dict(config.field_mapping_json or {}),
        "automation_policy": automation_policy_for_sync_config(dict(config.sync_options_json or {})),
        # Display names, the last comments (read-only) and how the state was chosen.
        **jira_detail_fields(issue, fields, browse_url),
        "status_mapping": status_mapping,
    }
    return {
        "project_id": config.project_id,
        "sync_config_id": config.id,
        "source_type": "jira",
        "source_instance": config.source_instance,
        "source_id": blank_to_none(issue.get("id")),
        "source_project_key": project_key(issue, fields),
        "source_key": source_key,
        "source_url": source_url(issue),
        "title": str(issue.get("summary") or fields.get("summary") or source_key).strip()[:500],
        # Jira Cloud v3 descriptions are ADF documents: read as text (Server/DC text is unchanged).
        "description": text_or_none(readable_body(issue.get("description") or fields.get("description"))),
        "issue_type": name_value(issue.get("issue_type") or fields.get("issuetype")),
        "source_status": source_status,
        "priority": name_value(issue.get("priority") or fields.get("priority")),
        "assignee": user_value(issue.get("assignee") or fields.get("assignee")),
        "reporter": user_value(issue.get("reporter") or fields.get("reporter")),
        "watchers_json": watchers(issue.get("watchers") or fields.get("watcher") or fields.get("watchers")),
        "labels_json": string_list(issue.get("labels") or fields.get("labels")),
        "components_json": _named_list(issue.get("components") or fields.get("components")),
        "fix_versions_json": _named_list(issue.get("fix_versions") or fields.get("fixVersions")),
        "sprint_json": _sprint_value(_mapped_issue_field(issue, fields, config, "sprint", "sprint_field")),
        "board_json": object_value(_mapped_issue_field(issue, fields, config, "board", "board_field")),
        "parent_key": parent_key(issue, fields),
        "epic_key": blank_to_none(
            issue.get("epic_key")
            or fields.get("epic_key")
            or fields.get("customfield_10008")
            or fields.get("epic")
            or _epic_parent(issue, fields)
        ),
        "linked_issues_json": list_value(issue.get("linked_issues") or fields.get("issuelinks")),
        "source_fields_json": source_fields,
        "work_state": work_state,
        "source_created_at": parse_datetime(issue.get("created") or fields.get("created")),
        "last_source_updated_at": parse_datetime(issue.get("updated") or fields.get("updated")),
    }


# Built-in status vocabulary: explicit, inspectable, overridable per config via
# status_state_mapping. Every target is a key of the shared workflow vocabulary
# (``workflow_mapping.DEFAULT_WORKFLOW_STATES``), so the board shows every item.
# A status outside it falls back to Jira's statusCategory (reported as such), else maps
# to "intake" and is REPORTED in the sync summary as unmapped — never a silent guess.
_BUILTIN_STATUS_STATES: dict[str, str] = {
    "closed": "done",
    "done": "done",
    "resolved": "done",
    "verified": "done",
    "in_progress": "development",
    "in_development": "development",
    "development": "development",
    "implementing": "development",
    "in_review": "review",
    "review": "review",
    "code_review": "review",
    "pull_request_review": "review",
    "in_analysis": "clarification",
    "analysis": "clarification",
    "clarification": "clarification",
    "needs_clarification": "clarification",
    "planned": "ready_for_development",
    "ready": "ready_for_development",
    "ready_for_development": "ready_for_development",
    "approved": "ready_for_development",
    "blocked": "blocked",
    "on_hold": "blocked",
    "impediment": "blocked",
}


# Jira's statusCategory keys (the fallback for unmapped or localized statuses).
_CATEGORY_STATES: dict[str, str] = {"new": "intake", "indeterminate": "development", "done": "done"}


def classify_jira_status(
    source_status: str | None, config: WorkItemSyncConfig, *, category: str | None = None
) -> tuple[str, MappingSource]:
    normalized = _status_key(source_status)
    configured = _configured_status_mapping(config)
    if normalized in configured:
        return configured[normalized], "configured"
    if normalized in _BUILTIN_STATUS_STATES:
        return _BUILTIN_STATUS_STATES[normalized], "builtin"
    if category in _CATEGORY_STATES:
        return _CATEGORY_STATES[category], "status_category"
    return "intake", "unmapped"


def suggested_state(source_status: str | None, category: str | None) -> str | None:
    normalized = _status_key(source_status)
    return _BUILTIN_STATUS_STATES.get(normalized) or _CATEGORY_STATES.get(str(category or ""))


def _configured_status_mapping(config: WorkItemSyncConfig) -> dict[str, str]:
    candidates = [object_value(config.sync_options_json).get("status_state_mapping")]
    normalized: dict[str, str] = {}
    for candidate in candidates:
        mapping = object_value(candidate)
        for source_status, work_state in mapping.items():
            source_key = _status_key(source_status)
            target_state = str(work_state or "").strip().lower().replace(" ", "_")
            if source_key and target_state:
                normalized[source_key] = target_state[:80]
    return normalized


def _status_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _epic_parent(issue: dict[str, Any], fields: dict[str, Any]) -> str | None:
    # Jira Cloud has no Epic Link field any more: a story names its epic only as ``parent``. A sub-task's parent (a
    # story) is no epic.
    parent = issue.get("parent") or fields.get("parent")
    if not isinstance(parent, dict):
        return None
    parent_fields = parent.get("fields") if isinstance(parent.get("fields"), dict) else {}
    issue_type = parent_fields.get("issuetype") if isinstance(parent_fields.get("issuetype"), dict) else {}
    is_epic = str(issue_type.get("name") or "").strip().lower() == "epic" or issue_type.get("hierarchyLevel") == 1
    return blank_to_none(parent.get("key")) if is_epic else None


def _named_list(value: Any) -> list[str]:
    return [normalized for item in list_value(value) if (normalized := name_value(item))]


def _mapped_issue_field(
    issue: dict[str, Any],
    fields: dict[str, Any],
    config: WorkItemSyncConfig,
    default_key: str,
    mapping_key: str,
) -> Any:
    mapping = object_value(config.field_mapping_json)
    configured_key = str(mapping.get(mapping_key) or "").strip()
    if configured_key and configured_key in fields:
        return fields.get(configured_key)
    return issue.get(default_key) or fields.get(default_key)


def _sprint_value(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        sprints = [sprint for sprint in (_sprint_value(item) for item in value) if sprint]
        if not sprints:
            return {}
        active = next((sprint for sprint in sprints if str(sprint.get("state") or "").lower() == "active"), None)
        selected = active or sprints[-1]
        return {**selected, "all": sprints}
    if isinstance(value, dict):
        return object_value(value)
    if isinstance(value, str):
        return _sprint_from_legacy_string(value)
    return {}


def _sprint_from_legacy_string(value: str) -> dict[str, Any]:
    text = value.strip()
    if not text:
        return {}
    parsed: dict[str, Any] = {"raw": text}
    for part in text.strip("[]").split(","):
        if "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        normalized_key = key.strip()
        normalized_value = raw_value.strip()
        if normalized_key in {"id", "name", "state", "goal", "rapidViewId"} and normalized_value:
            parsed[normalized_key] = normalized_value
    if "name" not in parsed:
        parsed["name"] = text
    return parsed
