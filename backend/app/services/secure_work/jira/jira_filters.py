from __future__ import annotations

from typing import Any

from ..jira_values import name_value, object_value, project_key, string_list, user_value

JIRA_SYNC_FILTER_KEYS = {
    "project_keys",
    "board_ids",
    "sprint_ids",
    "sprint_states",
    "labels_include",
    "labels_exclude",
    "components_include",
    "components_exclude",
    "issue_types",
    "statuses",
    "assignees",
    "teams",
    "fix_versions",
    "jql",
}


def normalize_jira_sync_filters(filters: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in JIRA_SYNC_FILTER_KEYS:
        value = filters.get(key)
        if key == "jql":
            text = str(value or "").strip()
            if text:
                normalized[key] = text
            continue
        values = string_list(value)
        if values:
            normalized[key] = values
    return normalized


def build_jira_query_preview(filters: dict[str, Any]) -> str:
    jql = str(filters.get("jql") or "").strip()
    if jql:
        return jql
    clauses: list[str] = []
    _append_in_clause(clauses, "project", filters.get("project_keys"))
    _append_in_clause(clauses, "labels", filters.get("labels_include"))
    _append_not_in_clause(clauses, "labels", filters.get("labels_exclude"))
    _append_in_clause(clauses, "component", filters.get("components_include"))
    _append_not_in_clause(clauses, "component", filters.get("components_exclude"))
    _append_in_clause(clauses, "issuetype", filters.get("issue_types"))
    _append_in_clause(clauses, "status", filters.get("statuses"))
    _append_in_clause(clauses, "assignee", filters.get("assignees"))
    _append_in_clause(clauses, "fixVersion", filters.get("fix_versions"))
    _append_in_clause(clauses, "sprint", filters.get("sprint_ids"))
    _append_in_clause(clauses, "sprintState", filters.get("sprint_states"))
    _append_in_clause(clauses, "team", filters.get("teams"))
    return " AND ".join(clauses) + (" ORDER BY updated DESC" if clauses else "ORDER BY updated DESC")


def issue_matches_filters(issue: dict[str, Any], filters: dict[str, Any]) -> bool:
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    if not _matches_optional_set(project_key(issue, fields), filters.get("project_keys")):
        return False
    if not _matches_optional_set(name_value(issue.get("status") or fields.get("status")), filters.get("statuses")):
        return False
    if not _matches_optional_set(
        name_value(issue.get("issue_type") or fields.get("issuetype")),
        filters.get("issue_types"),
    ):
        return False
    if not _matches_optional_set(user_value(issue.get("assignee") or fields.get("assignee")), filters.get("assignees")):
        return False

    labels = string_list(issue.get("labels") or fields.get("labels"))
    if not _matches_optional_list(labels, filters.get("labels_include")):
        return False
    if _intersects(labels, filters.get("labels_exclude")):
        return False

    components = _named_list(issue.get("components") or fields.get("components"))
    if not _matches_optional_list(components, filters.get("components_include")):
        return False
    if _intersects(components, filters.get("components_exclude")):
        return False

    fix_versions = _named_list(issue.get("fix_versions") or fields.get("fixVersions"))
    if not _matches_optional_list(fix_versions, filters.get("fix_versions")):
        return False

    sprint = object_value(issue.get("sprint") or fields.get("sprint"))
    if not _matches_optional_set(sprint.get("id"), filters.get("sprint_ids")):
        return False
    if not _matches_optional_set(sprint.get("state"), filters.get("sprint_states")):
        return False

    board = object_value(issue.get("board") or fields.get("board"))
    if not _matches_optional_set(board.get("id"), filters.get("board_ids")):
        return False

    team = issue.get("team") or fields.get("team")
    return _matches_optional_set(name_value(team), filters.get("teams"))


def _append_in_clause(clauses: list[str], field: str, values: Any) -> None:
    items = string_list(values)
    if items:
        clauses.append(f"{field} in ({', '.join(_jql_quote(item) for item in items)})")


def _append_not_in_clause(clauses: list[str], field: str, values: Any) -> None:
    items = string_list(values)
    if items:
        clauses.append(f"{field} not in ({', '.join(_jql_quote(item) for item in items)})")


def _jql_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _named_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [normalized for item in value if (normalized := name_value(item))]


def _matches_optional_set(value: Any, allowed: Any) -> bool:
    allowed_values = {item.lower() for item in string_list(allowed)}
    if not allowed_values:
        return True
    normalized = str(value or "").strip().lower()
    return normalized in allowed_values


def _matches_optional_list(values: list[Any], required: Any) -> bool:
    required_values = {item.lower() for item in string_list(required)}
    if not required_values:
        return True
    normalized_values = {str(value or "").strip().lower() for value in values if str(value or "").strip()}
    return bool(normalized_values & required_values)


def _intersects(values: list[Any], blocked: Any) -> bool:
    blocked_values = {item.lower() for item in string_list(blocked)}
    normalized_values = {str(value or "").strip().lower() for value in values if str(value or "").strip()}
    return bool(blocked_values & normalized_values)


def work_item_matches_json_filters(
    row: Any,  # a WorkItem row
    *,
    labels: list[str] | None,
    fix_versions: list[str] | None,
    sprint_ids: list[str] | None,
    sprint_names: list[str] | None,
) -> bool:
    if not _matches_any(row.labels_json or [], labels):
        return False
    if not _matches_any(row.fix_versions_json or [], fix_versions):
        return False
    sprint = object_value(row.sprint_json)
    if not _matches_sprint(sprint, sprint_ids=sprint_ids, sprint_names=sprint_names):
        return False
    return True


def _matches_any(values: Any, requested: list[str] | None) -> bool:
    requested_values = {value.lower() for value in string_list(requested)}
    if not requested_values:
        return True
    current_values = {value.lower() for value in string_list(values)}
    return bool(current_values & requested_values)


def _matches_sprint(
    sprint: dict[str, Any],
    *,
    sprint_ids: list[str] | None,
    sprint_names: list[str] | None,
) -> bool:
    allowed_ids = {value.lower() for value in string_list(sprint_ids)}
    allowed_names = {value.lower() for value in string_list(sprint_names)}
    if not allowed_ids and not allowed_names:
        return True
    sprints = [sprint]
    sprints.extend(item for item in sprint.get("all", []) if isinstance(item, dict))
    for item in sprints:
        sprint_id = str(item.get("id") or "").strip().lower()
        sprint_name = str(item.get("name") or "").strip().lower()
        if allowed_ids and sprint_id in allowed_ids:
            return True
        if allowed_names and sprint_name in allowed_names:
            return True
    return False
