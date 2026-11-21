from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    AuditLog,
    ConnectorWatcher,
    ConnectorWatcherEvent,
    WorkItem,
    WorkItemChangeUnit,
)
from .external_activity_matching import _matching_work_items
from .external_activity_state import (
    _append_external_activity,
    _apply_external_activity_state,
    _apply_jira_update,
    _mark_replan_required,
    _mark_source_stale,
    _state_event,
    _transition_reason,
)
from .external_activity_values import _drop_empty, _list, _string, _string_list, _unique
from .jira_values import object_value


async def link_connector_watcher_event_to_secure_work(
    db: AsyncSession,
    *,
    watcher: ConnectorWatcher,
    event: ConnectorWatcherEvent,
) -> list[dict[str, Any]]:
    normalized = dict(event.normalized_json or {})
    source_payload = object_value(normalized.get(event.provider_type))
    if event.provider_type not in {"bitbucket", "jira", "confluence", "knowledge"} or not source_payload:
        return []
    matches = await _matching_work_items(db, watcher=watcher, event=event, source_payload=source_payload)
    return [
        await _link_item(db, watcher=watcher, event=event, source_payload=source_payload, item=item,
                         matched_by=matched_by, change_units=change_units)
        for item, matched_by, change_units in matches
    ]


async def _link_item(
    db: AsyncSession,
    *,
    watcher: ConnectorWatcher,
    event: ConnectorWatcherEvent,
    source_payload: dict[str, Any],
    item: WorkItem,
    matched_by: list[str],
    change_units: list[WorkItemChangeUnit],
) -> dict[str, Any]:
    if event.provider_type == "jira":
        _apply_jira_update(item, source_payload)
    activity = _activity_summary(
        event=event,
        source_kind=event.provider_type,
        source_payload=source_payload,
        matched_by=matched_by,
        change_units=change_units,
    )
    _append_external_activity(item, activity)
    if activity["source_evidence_stale"]:
        _mark_source_stale(item, activity)
    if activity["requires_replan"]:
        _mark_replan_required(item, activity)
    state_transition = _apply_external_activity_state(item, activity)
    if state_transition is None and (activity["source_evidence_stale"] or activity["requires_replan"]):
        state_transition = {
            "from_state": item.work_state,
            "to_state": item.work_state,
            "reason": _transition_reason(activity),
            "state_changed": False,
        }
    if state_transition:
        db.add(_state_event(item, watcher=watcher, event=event, activity=activity, transition=state_transition))
    db.add(
        AuditLog(
            user_id=watcher.updated_by or watcher.created_by,
            action="secure_work.external_activity.linked",
            resource_type="work_item",
            resource_id=item.id,
            details={
                "event_id": event.id,
                "event_type": event.event_type,
                "matched_by": matched_by,
                "rule_decisions": activity.get("rule_decisions", []),
                "resulting_actions": activity.get("resulting_actions", []),
                "state_transition": state_transition,
            },
        )
    )
    return {
        "work_item_id": item.id,
        "source_key": item.source_key,
        "matched_by": matched_by,
        "change_unit_ids": [unit.id for unit in change_units],
        "source_evidence_stale": activity["source_evidence_stale"],
        "requires_replan": activity["requires_replan"],
        "state_transition": state_transition,
    }


def _activity_summary(
    *,
    event: ConnectorWatcherEvent,
    source_kind: str,
    source_payload: dict[str, Any],
    matched_by: list[str],
    change_units: list[WorkItemChangeUnit],
) -> dict[str, Any]:
    repository = object_value(source_payload.get("repository"))
    pull_request = object_value(source_payload.get("pull_request"))
    commit = object_value(source_payload.get("commit"))
    comment = object_value(source_payload.get("comment"))
    reviewer = object_value(source_payload.get("reviewer"))
    build = object_value(source_payload.get("build"))
    issue = object_value(source_payload.get("issue"))
    page = object_value(source_payload.get("page"))
    document = object_value(source_payload.get("document"))
    rule_decisions = _rule_decision_summary(event)
    return _drop_empty(
        {
            "event_id": event.id,
            "source": source_kind,
            "event_type": event.event_type,
            "external_id": event.external_id,
            "actor": event.actor,
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "received_at": event.received_at.isoformat() if event.received_at else None,
            "repository": repository,
            "branch": source_payload.get("branch"),
            "target_branch": source_payload.get("target_branch"),
            "pull_request": pull_request,
            "commit": commit,
            "comment": comment,
            "reviewer": reviewer,
            "build": build,
            "issue": issue,
            "page": page,
            "document": document,
            "force_push": bool(source_payload.get("force_push")),
            "source_evidence_stale": bool(source_payload.get("source_evidence_stale")),
            "requires_replan": bool(source_payload.get("requires_replan")),
            "rule_decisions": rule_decisions,
            "resulting_actions": _resulting_actions(rule_decisions),
            "matched_by": matched_by,
            "change_unit_ids": [unit.id for unit in change_units],
        }
    )


def _rule_decision_summary(event: ConnectorWatcherEvent) -> list[dict[str, Any]]:
    processing = object_value(event.processing_result_json)
    decisions = processing.get("rule_decisions")
    if not isinstance(decisions, list):
        return []
    compact: list[dict[str, Any]] = []
    for decision in decisions[:10]:
        row = object_value(decision)
        if not row:
            continue
        compact.append(
            _drop_empty(
                {
                    "rule_id": row.get("rule_id"),
                    "rule_name": row.get("rule_name") or row.get("name"),
                    "decision": row.get("decision") or row.get("effect"),
                    "actions": _action_types(row.get("actions")),
                    "status": row.get("status"),
                    "reason": row.get("reason"),
                }
            )
        )
    return compact


def _resulting_actions(rule_decisions: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for decision in rule_decisions:
        actions.extend(_string_list(decision.get("actions")))
    return _unique(actions)


def _action_types(value: Any) -> list[str]:
    actions: list[str] = []
    for item in _list(value):
        current = object_value(item)
        if current.get("type"):
            actions.append(str(current["type"]))
        elif _string(item):
            actions.append(str(item))
    return _unique(actions)
