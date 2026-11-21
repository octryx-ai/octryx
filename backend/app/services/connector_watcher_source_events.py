from __future__ import annotations

import re
from typing import Any

from .secure_work.jira_values import blank_to_none, list_value, name_value, object_value, parse_datetime, string_list

JIRA_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")


def normalize_source_event(
    payload: dict[str, Any],
    *,
    provider_type: str,
    watcher_scope: dict[str, Any],
) -> dict[str, Any]:
    if provider_type == "jira":
        return _normalize_jira(payload, watcher_scope=watcher_scope)
    if provider_type == "confluence":
        return _normalize_confluence(payload, watcher_scope=watcher_scope)
    if provider_type == "knowledge":
        return _normalize_knowledge(payload, watcher_scope=watcher_scope)
    return {}


def _normalize_jira(payload: dict[str, Any], *, watcher_scope: dict[str, Any]) -> dict[str, Any]:
    issue = object_value(payload.get("issue"))
    fields = object_value(issue.get("fields"))
    changelog = object_value(payload.get("changelog"))
    changed_fields = _changed_fields(payload, changelog)
    comment = object_value(payload.get("comment"))
    issue_key = blank_to_none(payload.get("issue_key") or issue.get("key") or fields.get("key"))
    action = _jira_action(payload, changed_fields=changed_fields, comment=comment)
    status = name_value(payload.get("status") or issue.get("status") or fields.get("status"))
    assignee = _user(payload.get("assignee") or issue.get("assignee") or fields.get("assignee"))
    labels = string_list(payload.get("labels") or issue.get("labels") or fields.get("labels"))
    fix_versions = _named_list(payload.get("fix_versions") or issue.get("fix_versions") or fields.get("fixVersions"))
    sprint = object_value(payload.get("sprint") or issue.get("sprint") or fields.get("sprint"))
    work_item_keys = _unique([issue_key] if issue_key else [])
    normalized = _drop_empty(
        {
            "action": action,
            "issue": _drop_empty(
                {
                    "id": blank_to_none(payload.get("issue_id") or issue.get("id")),
                    "key": issue_key,
                    "url": blank_to_none(payload.get("issue_url") or issue.get("self")),
                    "summary": payload.get("summary") or fields.get("summary"),
                    "status": status,
                    "assignee": assignee,
                    "labels": labels,
                    "fix_versions": fix_versions,
                    "sprint": sprint,
                }
            ),
            "comment": _drop_empty(
                {
                    "id": blank_to_none(comment.get("id")),
                    "body": comment.get("body") or comment.get("text"),
                    "author": _user(comment.get("author") or payload.get("actor") or payload.get("user")),
                }
            ),
            "changed_fields": changed_fields,
            "work_item_keys": work_item_keys,
            "source_evidence_stale": True,
            "requires_replan": action in {"issue.status_changed", "issue.fix_version_changed", "issue.sprint_changed"},
        }
    )
    scope = {
        **watcher_scope,
        **_drop_empty({"jira_project_key": _project_key(issue, fields), "work_item_keys": work_item_keys}),
    }
    return {
        "event_type": f"jira.{action}",
        "external_id": blank_to_none(payload.get("external_id") or issue_key or issue.get("id")),
        "actor": _user(payload.get("actor") or payload.get("user") or payload.get("author")),
        "occurred_at": parse_datetime(payload.get("occurred_at") or payload.get("timestamp") or issue.get("updated")),
        "scope": scope,
        "normalized": {"jira": normalized},
    }


def _normalize_confluence(payload: dict[str, Any], *, watcher_scope: dict[str, Any]) -> dict[str, Any]:
    page = object_value(payload.get("page") or payload.get("content"))
    space = object_value(page.get("space"))
    action = _source_action(payload, provider="confluence", default="page.updated")
    title = blank_to_none(payload.get("title") or page.get("title"))
    page_id = blank_to_none(payload.get("page_id") or page.get("id"))
    space_key = blank_to_none(payload.get("space_key") or space.get("key"))
    work_item_keys = _work_item_keys(payload, title, page.get("body"), payload.get("comment"))
    normalized = _drop_empty(
        {
            "action": action,
            "page": _drop_empty(
                {
                    "id": page_id,
                    "title": title,
                    "space_key": space_key,
                    "version": payload.get("version") or object_value(page.get("version")).get("number"),
                    "url": blank_to_none(payload.get("url") or page.get("url") or page.get("_links", {}).get("webui")),
                }
            ),
            "comment": payload.get("comment"),
            "work_item_keys": work_item_keys,
            "source_evidence_stale": True,
            "requires_replan": action in {"page.updated", "page.deleted", "page.moved"},
        }
    )
    scope = {
        **watcher_scope,
        **_drop_empty({"space_key": space_key, "page_id": page_id, "work_item_keys": work_item_keys}),
    }
    return {
        "event_type": f"confluence.{action}",
        "external_id": blank_to_none(payload.get("external_id") or page_id),
        "actor": _user(payload.get("actor") or payload.get("user") or page.get("updated_by")),
        "occurred_at": parse_datetime(
            payload.get("occurred_at") or payload.get("timestamp") or payload.get("updated_at")
        ),
        "scope": scope,
        "normalized": {"confluence": normalized},
    }


def _normalize_knowledge(payload: dict[str, Any], *, watcher_scope: dict[str, Any]) -> dict[str, Any]:
    action = _source_action(payload, provider="knowledge", default="document.updated")
    key = blank_to_none(payload.get("key") or payload.get("knowledge_key"))
    category = blank_to_none(payload.get("category"))
    source = blank_to_none(payload.get("source") or payload.get("canonical_source"))
    title = blank_to_none(payload.get("title") or payload.get("name") or key)
    work_item_keys = _work_item_keys(payload, title, key, source)
    normalized = _drop_empty(
        {
            "action": action,
            "document": _drop_empty(
                {
                    "id": blank_to_none(payload.get("knowledge_id") or payload.get("id")),
                    "key": key,
                    "category": category,
                    "title": title,
                    "source": source,
                    "layer": payload.get("knowledge_layer"),
                }
            ),
            "work_item_keys": work_item_keys,
            "source_evidence_stale": True,
            "requires_replan": action in {"document.updated", "document.deleted", "metadata.changed"},
        }
    )
    scope = {
        **watcher_scope,
        **_drop_empty({"knowledge_key": key, "category": category, "work_item_keys": work_item_keys}),
    }
    return {
        "event_type": f"knowledge.{action}",
        "external_id": blank_to_none(payload.get("external_id") or key or payload.get("id")),
        "actor": _user(payload.get("actor") or payload.get("user") or payload.get("updated_by")),
        "occurred_at": parse_datetime(
            payload.get("occurred_at") or payload.get("timestamp") or payload.get("updated_at")
        ),
        "scope": scope,
        "normalized": {"knowledge": normalized},
    }


def _jira_action(payload: dict[str, Any], *, changed_fields: list[str], comment: dict[str, Any]) -> str:
    explicit = blank_to_none(payload.get("jira_action") or payload.get("action"))
    if explicit:
        return str(explicit).replace(":", ".").replace("_", ".").lower()
    event_name = str(payload.get("webhookEvent") or payload.get("issue_event_type_name") or "").lower()
    if comment or "comment" in event_name:
        return "issue.comment_added"
    if "status" in changed_fields:
        return "issue.status_changed"
    if "fixversion" in changed_fields or "fixversions" in changed_fields:
        return "issue.fix_version_changed"
    if "sprint" in changed_fields:
        return "issue.sprint_changed"
    if "assignee" in changed_fields:
        return "issue.assignee_changed"
    if "labels" in changed_fields:
        return "issue.labels_changed"
    return "issue.updated"


def _source_action(payload: dict[str, Any], *, provider: str, default: str) -> str:
    explicit = blank_to_none(payload.get(f"{provider}_action") or payload.get("action"))
    if explicit:
        return str(explicit).replace(":", ".").replace("_", ".").lower()
    event_type = str(payload.get("event_type") or payload.get("type") or "").lower()
    if provider == "confluence":
        if "created" in event_type:
            return "page.created"
        if "comment" in event_type:
            return "page.commented"
        if "moved" in event_type:
            return "page.moved"
        if "deleted" in event_type or "removed" in event_type:
            return "page.deleted"
    if provider == "knowledge":
        if "added" in event_type or "created" in event_type:
            return "document.added"
        if "deleted" in event_type or "removed" in event_type:
            return "document.deleted"
        if "metadata" in event_type:
            return "metadata.changed"
    return default


def _changed_fields(payload: dict[str, Any], changelog: dict[str, Any]) -> list[str]:
    explicit = string_list(payload.get("changed_fields"))
    if explicit:
        return [field.lower() for field in explicit]
    items = list_value(changelog.get("items"))
    return [str(item.get("field") or "").lower() for item in items if isinstance(item, dict) and item.get("field")]


def _work_item_keys(payload: dict[str, Any], *values: Any) -> list[str]:
    explicit = string_list(payload.get("work_item_keys"))
    keys = list(explicit)
    for value in values:
        if value is None:
            continue
        for match in JIRA_KEY_RE.findall(str(value)):
            keys.append(match)
    return _unique(keys)[:20]


def _user(value: Any) -> str | None:
    if isinstance(value, dict):
        return blank_to_none(
            value.get("displayName")
            or value.get("display_name")
            or value.get("name")
            or value.get("emailAddress")
        )
    return blank_to_none(value)


def _project_key(issue: dict[str, Any], fields: dict[str, Any]) -> str | None:
    project = object_value(issue.get("project") or fields.get("project"))
    return blank_to_none(project.get("key"))


def _named_list(value: Any) -> list[str]:
    return [normalized for item in list_value(value) if (normalized := name_value(item))]


def _unique(values: list[str | None]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return unique


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: current for key, current in value.items() if current not in (None, "", [], {})}
