"""How linked external activity changes a Work Item: activity log, stale or replan flags and state events."""

from __future__ import annotations

from typing import Any

from ...models import (
    ConnectorWatcher,
    ConnectorWatcherEvent,
    WorkItem,
    WorkItemStateEvent,
)
from ...time_utils import utc_now
from .external_activity_values import EVENT_REVIEW_STATES, MAX_EXTERNAL_ACTIVITY, TERMINAL_WORK_STATES, _list
from .jira_values import object_value


def _append_external_activity(item: WorkItem, activity: dict[str, Any]) -> None:
    source_fields = object_value(item.source_fields_json)
    existing = [
        entry
        for entry in _list(source_fields.get("external_activity"))
        if object_value(entry).get("event_id") != activity["event_id"]
    ]
    source_fields["external_activity"] = [activity, *existing][:MAX_EXTERNAL_ACTIVITY]
    source_fields["latest_external_activity"] = activity
    item.source_fields_json = source_fields
    item.updated_at = utc_now()


def _mark_replan_required(item: WorkItem, activity: dict[str, Any]) -> None:
    source_fields = object_value(item.source_fields_json)
    source_fields["externally_modified"] = True
    source_fields["requires_replan"] = True
    source_fields["external_replan_reason"] = {
        "event_id": activity["event_id"],
        "event_type": activity["event_type"],
        "branch": activity.get("branch"),
        "actor": activity.get("actor"),
        "force_push": activity.get("force_push"),
    }
    item.source_fields_json = source_fields


def _mark_source_stale(item: WorkItem, activity: dict[str, Any]) -> None:
    source_fields = object_value(item.source_fields_json)
    source_fields["source_evidence_stale"] = True
    source_fields["latest_source_stale_event"] = {
        "event_id": activity["event_id"],
        "source": activity["source"],
        "event_type": activity["event_type"],
        "actor": activity.get("actor"),
        "requires_replan": activity.get("requires_replan"),
    }
    item.source_fields_json = source_fields


def _apply_external_activity_state(item: WorkItem, activity: dict[str, Any]) -> dict[str, Any] | None:
    previous = str(item.work_state or "").strip() or "intake"
    if previous in TERMINAL_WORK_STATES:
        return None
    if activity.get("requires_replan"):
        target = "needs_replan"
    elif activity.get("source_evidence_stale"):
        target = "needs_human_review"
    else:
        return None
    if previous == target or previous in EVENT_REVIEW_STATES:
        return None
    item.work_state = target
    item.updated_at = utc_now()
    return {"from_state": previous, "to_state": target, "reason": _transition_reason(activity), "state_changed": True}


def _state_event(
    item: WorkItem,
    *,
    watcher: ConnectorWatcher,
    event: ConnectorWatcherEvent,
    activity: dict[str, Any],
    transition: dict[str, Any],
) -> WorkItemStateEvent:
    return WorkItemStateEvent(
        work_item_id=item.id,
        from_state=transition["from_state"],
        to_state=transition["to_state"],
        actor_id=watcher.updated_by or watcher.created_by,
        reason=transition["reason"],
        source=f"{event.provider_type}_watcher",
        dry_run=False,
        jira_sync_preview_json={"mode": "local_only", "will_mutate_jira": False},
        conflict_json={
            "external_event_id": event.id,
            "source_evidence_stale": bool(activity.get("source_evidence_stale")),
            "requires_replan": bool(activity.get("requires_replan")),
            "rule_decisions": activity.get("rule_decisions", []),
            "resulting_actions": activity.get("resulting_actions", []),
            "state_changed": bool(transition.get("state_changed")),
        },
    )


def _transition_reason(activity: dict[str, Any]) -> str:
    if activity.get("requires_replan"):
        return (
            f"External {activity.get('source')} event {activity.get('event_type')} conflicts with the current plan; "
            "agent must re-read evidence and replan before continuing."
        )
    return (
        f"External {activity.get('source')} event {activity.get('event_type')} changed linked source evidence; "
        "human review is required before continuing."
    )


def _apply_jira_update(item: WorkItem, source_payload: dict[str, Any]) -> None:
    issue = object_value(source_payload.get("issue"))
    changed_fields = {str(field).lower() for field in _list(source_payload.get("changed_fields"))}
    update_all = not changed_fields
    if issue.get("status") and (update_all or "status" in changed_fields):
        item.source_status = str(issue["status"])[:120]
    if issue.get("assignee") and (update_all or "assignee" in changed_fields):
        item.assignee = str(issue["assignee"])[:220]
    if isinstance(issue.get("labels"), list) and (update_all or "labels" in changed_fields):
        item.labels_json = issue["labels"]
    if isinstance(issue.get("fix_versions"), list) and (
        update_all or bool({"fixversion", "fixversions"} & changed_fields)
    ):
        item.fix_versions_json = issue["fix_versions"]
    if isinstance(issue.get("sprint"), dict) and (update_all or "sprint" in changed_fields):
        item.sprint_json = issue["sprint"]
