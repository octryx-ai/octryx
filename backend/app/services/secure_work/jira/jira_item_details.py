"""What a Jira item shows besides its fields: people, comments, sprint/board, status mapping."""

from __future__ import annotations

from typing import Any

from ....time_utils import ensure_utc
from ....tools.jira_impl._jira_cloud import readable_body
from ..jira_values import blank_to_none, list_value, object_value, parse_datetime, user_value
from .stored_types import StatusCategory, StoredJiraComment, StoredJiraDetails, StoredJiraPerson

MAX_COMMENTS = 20
MAX_COMMENT_CHARS = 4000
STATUS_CATEGORIES = ("new", "indeterminate", "done")


def _person(value: Any) -> StoredJiraPerson | None:
    identifier = user_value(value)
    if identifier is None:
        return None
    display = blank_to_none(value.get("displayName")) if isinstance(value, dict) else None
    return {"id": identifier, "display": display}


def _watchers(value: Any) -> list[StoredJiraPerson]:
    raw = value.get("watchers") or value.get("items") or value.get("values") if isinstance(value, dict) else value
    return [person for item in list_value(raw) if (person := _person(item))]


def _utc_iso(value: Any) -> str | None:
    parsed = parse_datetime(value)
    return ensure_utc(parsed).isoformat() if parsed else None


def status_category(status: Any) -> StatusCategory | None:
    category = object_value(object_value(status).get("statusCategory")).get("key")
    return category if category in STATUS_CATEGORIES else None


def _comments(value: Any, browse_url: str | None) -> tuple[list[StoredJiraComment], int | None]:
    container = object_value(value)
    raw = container.get("comments") if container else value
    entries = [entry for entry in list_value(raw) if isinstance(entry, dict)][-MAX_COMMENTS:]
    total = container.get("total") if isinstance(container.get("total"), int) else None
    comments: list[StoredJiraComment] = []
    for entry in entries:
        comment_id = blank_to_none(entry.get("id"))
        author = _person(entry.get("author"))
        body = readable_body(entry.get("body"))
        comments.append({
            "id": comment_id,
            "author": author["id"] if author else None,
            "author_display": author["display"] if author else None,
            "created": _utc_iso(entry.get("created")),
            "body": (body if isinstance(body, str) else "")[:MAX_COMMENT_CHARS],
            "url": f"{browse_url}?focusedCommentId={comment_id}" if browse_url and comment_id else None,
        })
    return comments, total


def bounded_raw(issue: dict[str, Any]) -> dict[str, Any]:
    # Links live, scoped to the allowlist, in ``linked_issues_json``, never in the raw copy; the
    # parent lives in ``parent_key`` (masked outside the allowlist), never with its summary here.
    dropped = {"comment", "issuelinks", "linked_issues", "parent"}
    raw = {key: value for key, value in issue.items() if key not in dropped}
    if isinstance(issue.get("fields"), dict):
        raw["fields"] = {key: value for key, value in issue["fields"].items() if key not in dropped}
    return raw


def jira_detail_fields(issue: dict[str, Any], fields: dict[str, Any], browse_url: str | None) -> StoredJiraDetails:
    comments, total = _comments(issue.get("comment") or fields.get("comment"), browse_url)
    return {
        "people": {
            "assignee": _person(issue.get("assignee") or fields.get("assignee")),
            "reporter": _person(issue.get("reporter") or fields.get("reporter")),
            "watchers": _watchers(issue.get("watchers") or fields.get("watcher") or fields.get("watchers")),
        },
        "comments": comments,
        "comments_total": total,
    }


def _sprint(value: Any) -> dict[str, Any] | None:
    sprint = object_value(value)
    if not sprint or not (sprint.get("name") or sprint.get("id")):
        return None
    return {key: sprint.get(key) for key in ("id", "name", "state", "goal")}


def _board(value: Any) -> dict[str, Any] | None:
    board = object_value(value)
    if not board or not (board.get("name") or board.get("id")):
        return None
    return {"id": board.get("id"), "name": board.get("name")}


def work_item_detail_fields(row: Any) -> dict[str, Any]:
    source = object_value(row.source_fields_json)
    people = object_value(source.get("people"))
    displays = {person["id"]: person.get("display") for person in list_value(people.get("watchers"))
                if isinstance(person, dict) and person.get("id")}
    mapping = object_value(source.get("status_mapping"))
    return {
        "assignee_display": object_value(people.get("assignee")).get("display"),
        "reporter_display": object_value(people.get("reporter")).get("display"),
        "watchers_display": [{"id": watcher, "display": displays.get(watcher)} for watcher in row.watchers_json or []],
        "comments": [comment for comment in list_value(source.get("comments")) if isinstance(comment, dict)],
        "comments_total": source.get("comments_total") if isinstance(source.get("comments_total"), int) else None,
        "sprint": _sprint(row.sprint_json),
        "board": _board(row.board_json),
        "status_mapping": {"source": mapping.get("source"), "category": mapping.get("category")},
    }


__all__ = ["MAX_COMMENTS", "bounded_raw", "jira_detail_fields", "status_category", "work_item_detail_fields"]
