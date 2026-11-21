"""ServiceNow as a registered Work source (``intake/registry``): the setup, discovery and scheduling hooks.

The behaviour is the one ``intake/setup.py``, ``intake/discovery.py`` and the scheduler had in their ServiceNow
branches; only where it lives changed. One intake per Workspace stays ServiceNow's own rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Task, User, WorkItem, WorkItemSyncConfig
from ..intake.connections import connection_config_of, require_intake_connection
from ..intake.runs import TRIGGER_SCHEDULED
from ..jira_values import object_value, string_list
from ..workflow_mapping import DEFAULT_WORKFLOW_STATES
from . import intake as servicenow_intake
from .config import DEFAULT_EXCLUDED_STATES, DEFAULT_STATE_MAPPING, SOURCE_TYPE, TABLES
from .known_values import known_values
from .source import IntakeSourceError

WHAT_KEYS = ("tables", "excluded_states", "assignment_groups", "services")
INCIDENT_TABLE = "incident"
NEW_STATE = "intake"
WORK_STATES = [{"key": state["key"], "label": state["label"]} for state in DEFAULT_WORKFLOW_STATES]


def _payload(draft: dict[str, Any], how: dict[str, Any]) -> dict[str, Any]:
    what = object_value(draft.get("what"))
    payload: dict[str, Any] = {key: string_list(what.get(key)) for key in WHAT_KEYS}
    if not payload["tables"]:
        payload["tables"] = ["incident"]
    if str(what.get("sysparm_query") or "").strip():
        payload["sysparm_query"] = str(what["sysparm_query"]).strip()
    if how["status_mapping"]:
        payload["state_mapping"] = how["status_mapping"]
    return {**payload, "schedule": draft.get("schedule"), "connection_id": draft.get("connection_id")}


class ServiceNowIntakeSource:
    source_type = SOURCE_TYPE
    label = "ServiceNow"
    connector = SOURCE_TYPE
    key_field = "tables"
    what_keys = WHAT_KEYS
    analyzes_after_sync = False

    def scope_key(self, item: WorkItem) -> str:
        """The ServiceNow table of its record: the binding key of a named connection."""
        fields = dict((item.source_fields_json or {}).get(SOURCE_TYPE) or {})
        return str(fields.get("table") or item.issue_type or "")

    def wants_auto_analysis(self, item: WorkItem, settings: Any, options: Mapping[str, Any]) -> bool:
        return bool(settings.servicenow_new_incidents and str(item.issue_type or "") == INCIDENT_TABLE
                    and str(item.work_state or "") == NEW_STATE)

    def draft_what(self, row: WorkItemSyncConfig) -> tuple[dict[str, Any], dict[str, Any]]:
        intake = servicenow_intake.intake_of(row)
        what = {key: list(intake.get(key) or []) for key in WHAT_KEYS}
        what["sysparm_query"] = intake.get("sysparm_query") or ""
        return what, dict(intake.get("state_mapping") or {})

    async def require_connection(self, db: AsyncSession, project_id: str, connection_id: Any) -> None:
        await require_intake_connection(db, project_id, SOURCE_TYPE, connection_id)

    async def save(self, db: AsyncSession, *, user: User, project_id: str, draft: dict[str, Any],
                   how: dict[str, Any], name: str, row: WorkItemSyncConfig | None) -> WorkItemSyncConfig:
        if row is None and await servicenow_intake.get_intake(db, project_id) is not None:
            raise HTTPException(status_code=409, detail={
                "state": "refused", "code": "servicenow_intake_exists",
                "message": "This Workspace already has a ServiceNow intake."})
        saved = await servicenow_intake.put_intake(db, project_id=project_id, payload=_payload(draft, how),
                                                   user=user, activate_new=False)
        saved.name = name[:220]
        options = dict(saved.sync_options_json or {})
        saved.sync_options_json = {**options, "automation_mode": how["automation_mode"],
                                   "automation_labels": how["automation_labels"],
                                   "automation_exclude_labels": how["automation_exclude_labels"]}
        await db.flush()
        return saved

    async def discover(self, db: AsyncSession, project_id: str, connection_id: str) -> dict[str, Any]:
        """The tables, the default open-state filter and mapping, and the groups and services seen in recent
        records inside the connection's limit (suggestions; the drawer works without them)."""
        config = await connection_config_of(db, project_id, SOURCE_TYPE, connection_id)
        suggestions: dict[str, Any] = {"assignment_groups": [], "services": []}
        reason = None
        if config is None:
            reason = "connection_unavailable"
        else:
            try:
                values = await known_values(config, limited=True, table="incident")
                suggestions = {key: [entry.get("name") if isinstance(entry, dict) else entry
                                     for entry in values.get(key) or []] for key in suggestions}
            except IntakeSourceError as error:
                reason = error.code
            except Exception:  # noqa: BLE001 - suggestions only; the drawer still works without them
                reason = "servicenow_request_failed"
        return {"source_type": SOURCE_TYPE, "work_states": WORK_STATES, "tables": list(TABLES),
                "excluded_states": list(DEFAULT_EXCLUDED_STATES[:3]),
                "statuses": [{"name": name.title(), "state": state} for name, state in DEFAULT_STATE_MAPPING.items()
                             if name != "canceled"],
                **suggestions, "reason": reason}

    async def count(self, db: AsyncSession, project_id: str, connection_id: str,
                    what: dict[str, Any]) -> dict[str, Any]:
        return {"count": None, "reason": "not_counted"}

    async def preview(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig) -> dict[str, Any]:
        return await servicenow_intake.run_intake(db, row=row, user=user, dry_run=True)

    async def sync(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig, trigger: str) -> dict[str, Any]:
        return await servicenow_intake.run_intake(db, row=row, user=user, dry_run=False, trigger=trigger)

    async def reschedule(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig) -> None:
        await servicenow_intake.reschedule(db, row, user)

    async def run_scheduled(self, db: AsyncSession, *, task: Task, task_run: Any) -> dict[str, Any]:
        row = await db.get(WorkItemSyncConfig, str((task.config or {}).get("sync_config_id") or ""))
        owner = await db.get(User, task.owner_id)
        if row is None or owner is None or row.source_type != SOURCE_TYPE:
            raise ValueError("servicenow intake task without its config or owner")
        result = await self.sync(db, user=owner, row=row, trigger=TRIGGER_SCHEDULED)
        output = {"mode": servicenow_intake.SERVICENOW_SYNC_TASK_TYPE, "sync_config_id": row.id,
                  "sync_run_id": result["sync_run"]["id"], "summary": result["summary"]}
        if task_run is not None:
            task_run.output = output
        return output


SOURCE = ServiceNowIntakeSource()

__all__ = ["SOURCE", "ServiceNowIntakeSource"]
