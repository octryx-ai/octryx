"""Jira as a registered Work source (``intake/registry``): setup, discovery and scheduling hooks over ``jira_sync``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Task, User, WorkItem, WorkItemSyncConfig
from ...named_connections.descriptors.atlassian import issue_project
from ..intake.connections import require_intake_connection
from ..intake.jira_discovery import count_jira, discover_jira
from ..jira_values import object_value, string_list
from ..workflow_mapping import DEFAULT_WORKFLOW_STATES
from . import jira_sync, jira_sync_config, jira_sync_schedule, jira_sync_task

SOURCE_TYPE = "jira"
WHAT_KEYS = ("project_keys", "issue_types", "labels_include", "labels_exclude", "components_include")
WORK_STATES = [{"key": state["key"], "label": state["label"]} for state in DEFAULT_WORKFLOW_STATES]


def _payload(draft: dict[str, Any], how: dict[str, Any], row: WorkItemSyncConfig | None) -> dict[str, Any]:
    what = object_value(draft.get("what"))
    filters = {key: string_list(what.get(key)) for key in WHAT_KEYS}
    if str(what.get("jql") or "").strip():
        filters["jql"] = str(what["jql"]).strip()
    fields = dict(how["field_mapping"])
    extra = [fields["story_points_field"]] if fields.get("story_points_field") else []
    options = {**(dict(row.sync_options_json or {}) if row is not None else {}),
               "schedule": draft.get("schedule"), "automation_mode": how["automation_mode"],
               "automation_labels": how["automation_labels"] or ["octryx"],
               "automation_exclude_labels": how["automation_exclude_labels"],
               "status_state_mapping": how["status_mapping"]}
    return {"name": draft.get("name"), "connection_id": draft.get("connection_id"), "filters": filters,
            "field_mapping": {**fields, "extra_fields": extra}, "sync_options": options}


class JiraIntakeSource:
    source_type = SOURCE_TYPE
    label = "Jira"
    connector = SOURCE_TYPE
    key_field = "project_keys"
    what_keys = WHAT_KEYS
    analyzes_after_sync = True

    def scope_key(self, item: WorkItem) -> str:
        return issue_project(item.source_key) or ""

    def wants_auto_analysis(self, item: WorkItem, settings: Any, options: Mapping[str, Any]) -> bool:
        if not settings.jira_label:
            return False
        labels = {str(label).casefold() for label in (item.labels_json or [])}
        return settings.jira_label.casefold() in labels

    def draft_what(self, row: WorkItemSyncConfig) -> tuple[dict[str, Any], dict[str, Any]]:
        filters = dict(row.filters_json or {})
        options = dict(row.sync_options_json or {})
        what: dict[str, Any] = {key: list(filters.get(key) or []) for key in WHAT_KEYS}
        what["jql"] = str(filters.get("jql") or "")
        return what, dict(options.get("status_state_mapping") or {})

    async def require_connection(self, db: AsyncSession, project_id: str, connection_id: Any) -> None:
        await require_intake_connection(db, project_id, SOURCE_TYPE, connection_id)

    async def save(self, db: AsyncSession, *, user: User, project_id: str, draft: dict[str, Any],
                   how: dict[str, Any], name: str, row: WorkItemSyncConfig | None) -> WorkItemSyncConfig:
        payload = _payload(draft, how, row)
        if row is None:
            saved = await jira_sync_config.create_jira_sync_config(
                db, current_user=user, payload={**payload, "project_id": project_id, "is_active": False})
            return await db.get(WorkItemSyncConfig, saved["id"])
        await jira_sync_config.update_jira_sync_config(db, config_id=row.id, current_user=user, payload=payload)
        return row

    async def discover(self, db: AsyncSession, project_id: str, connection_id: str) -> dict[str, Any]:
        return {"source_type": SOURCE_TYPE, "work_states": WORK_STATES,
                **await discover_jira(db, project_id, connection_id)}

    async def count(self, db: AsyncSession, project_id: str, connection_id: str,
                    what: dict[str, Any]) -> dict[str, Any]:
        return await count_jira(db, project_id, connection_id, what)

    async def preview(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig) -> dict[str, Any]:
        return await jira_sync.run_jira_work_item_sync(db, config_id=row.id, current_user=user, payload={},
                                                       dry_run=True)

    async def sync(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig, trigger: str) -> dict[str, Any]:
        payload = {"trigger": "scheduler"} if trigger == "scheduled" else {}
        return await jira_sync.run_jira_work_item_sync(db, config_id=row.id, current_user=user, payload=payload,
                                                       dry_run=False)

    async def reschedule(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig) -> None:
        await jira_sync_schedule.sync_jira_work_item_scheduler(db, config=row, current_user=user)

    async def run_scheduled(self, db: AsyncSession, *, task: Task, task_run: Any) -> dict[str, Any]:
        return await jira_sync_task.run_scheduled_jira_work_item_sync(db, task=task, task_run=task_run)


SOURCE = JiraIntakeSource()

__all__ = ["SOURCE", "WHAT_KEYS", "JiraIntakeSource"]
