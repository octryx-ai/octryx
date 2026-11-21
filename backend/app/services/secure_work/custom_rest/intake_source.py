"""Custom REST as a registered Work source (``intake/registry``): setup, discovery, sample, scheduling, write-back.

The intake's "connection" is the REST definition (``connection_id`` = its key): an active definition the Workspace
has a connection for (its own, else the platform's). Discovery lists the definition's enabled read operations with
the roles their grants name, and its write operations for the write-back; :meth:`CustomRestIntakeSource.sample` maps
one page of a draft's list operation without storing anything (the setup drawer's dry run before saving).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import RestApiOperation, Task, User, WorkItem, WorkItemSyncConfig
from ...rest_connector.authorization import grants_of
from ...rest_connector.common import is_read_operation
from ...rest_connector.connections import connection_for_call
from ..intake.pipeline import PREVIEW_ITEMS, SAMPLE_KEYS
from ..intake.protocol import Listed
from ..intake.runs import TRIGGER_SCHEDULED
from ..jira_values import object_value
from ..servicenow.source import IntakeSourceError, source_error
from ..workflow_mapping import DEFAULT_WORKFLOW_STATES
from . import intake as rest_intake
from .config import LABEL, SOURCE_TYPE, intake_of_row, normalize_config, refused
from .listing import IntakeCallContext, acting_role, definition_by_key, read_pages, resolve_list
from .records import RECORDS
from .write_back import execute_custom_rest_state_sync, will_write, write_effects

WHAT_KEYS = ("operation", "role")
NEW_STATE = "intake"
WORK_STATES = [{"key": state["key"], "label": state["label"]} for state in DEFAULT_WORKFLOW_STATES]
CODE_DEFINITION_NOT_FOUND = "intake_connection_not_found"


def _what(draft: Mapping[str, Any]) -> dict[str, Any]:
    return object_value(draft.get("what"))


def _how(draft: Mapping[str, Any]) -> dict[str, Any]:
    return object_value(draft.get("how"))


class CustomRestIntakeSource:
    source_type = SOURCE_TYPE
    label = LABEL
    connector = None
    key_field = None
    what_keys = WHAT_KEYS
    analyzes_after_sync = False
    state_sync_driver = staticmethod(execute_custom_rest_state_sync)
    will_write = staticmethod(will_write)
    write_effects = staticmethod(write_effects)

    def scope_key(self, item: WorkItem) -> str:
        """The definition key: an item is bound to the REST API it came from, never to another source's key."""
        return str(item.source_instance or "")

    def wants_auto_analysis(self, item: WorkItem, settings: Any, options: Mapping[str, Any]) -> bool:
        """New items of an intake that switched ``auto_analyze_new`` on (per intake, default off)."""
        return bool(options.get("auto_analyze_new")) and str(item.work_state or "") == NEW_STATE

    def draft_what(self, row: WorkItemSyncConfig) -> tuple[dict[str, Any], dict[str, Any]]:
        intake = intake_of_row(row)
        what = {key: intake[key] for key in ("operation", "role", "arguments", "max_items", "max_pages")}
        return what, dict(intake["state_mapping"])

    def draft_how(self, row: WorkItemSyncConfig) -> dict[str, Any]:
        """The ``how`` keys of its own the setup draft carries (``intake/setup.draft_of``)."""
        intake = intake_of_row(row)
        return {"field_mapping": intake["fields"], "closed_statuses": intake["closed_statuses"],
                "auto_analyze_new": intake["auto_analyze_new"], "write_back": intake["write_back"]}

    async def workspace_connections(self, db: AsyncSession, project_id: str) -> list[dict[str, Any]]:
        """The definitions the Workspace can sync from (the overview's "connections" of this source)."""
        from ....models import RestApiDefinition

        rows = (await db.execute(select(RestApiDefinition).where(RestApiDefinition.is_active.is_(True))
                                 .order_by(RestApiDefinition.key))).scalars().all()
        listed = []
        for definition in rows:
            connection = await connection_for_call(db, definition.id, project_id)
            if connection is not None:
                scope = "workspace" if connection.scope_key == project_id else "global"
                listed.append({"id": definition.key, "name": definition.name, "scope": scope})
        return listed

    async def require_connection(self, db: AsyncSession, project_id: str, connection_id: Any) -> None:
        wanted = connection_id.strip() if isinstance(connection_id, str) else ""
        definition = await definition_by_key(db, wanted) if wanted else None
        if definition is None or await connection_for_call(db, definition.id, project_id) is None:
            raise HTTPException(status_code=422, detail={
                "state": "needs_configuration", "code": CODE_DEFINITION_NOT_FOUND, "field": "connection_id",
                "message": "Pick a REST API this Workspace has a connection for (Connections › REST APIs)."})

    async def save(self, db: AsyncSession, *, user: User, project_id: str, draft: dict[str, Any],
                   how: dict[str, Any], name: str, row: WorkItemSyncConfig | None) -> WorkItemSyncConfig:
        definition_key = str(row.source_instance if row is not None else draft.get("connection_id")).strip()
        if row is not None and draft.get("connection_id") not in (None, definition_key):
            raise refused("connection_id", "cannot change: the items' identity is the REST API they came from")
        config = normalize_config(_what(draft), _how(draft), draft.get("schedule"))
        saved = await rest_intake.put_intake(db, project_id=project_id, definition_key=definition_key, name=name,
                                             config=config, user=user, row=row)
        saved.sync_options_json = {**dict(saved.sync_options_json or {}),
                                   "automation_mode": how["automation_mode"],
                                   "automation_labels": how["automation_labels"],
                                   "automation_exclude_labels": how["automation_exclude_labels"]}
        await db.flush()
        return saved

    async def discover(self, db: AsyncSession, project_id: str, connection_id: str) -> dict[str, Any]:
        definition = await definition_by_key(db, connection_id)
        operations = (await db.execute(select(RestApiOperation).where(
            RestApiOperation.definition_id == definition.id, RestApiOperation.enabled.is_(True))
            .order_by(RestApiOperation.op_key))).scalars().all()

        def described(operation: RestApiOperation) -> dict[str, Any]:
            grants = [grant for grant in grants_of(operation) if grant.workspace_id in (None, project_id)]
            return {"op_key": operation.op_key, "name": operation.llm_name or operation.op_key,
                    "method": operation.method, "path": operation.path, "summary": operation.summary,
                    "paginated": str((operation.pagination or {}).get("type") or "none") != "none",
                    "roles": sorted({grant.role for grant in grants}),
                    "scoped_roles": sorted({grant.role for grant in grants if grant.scoped}),
                    "role_required": any(grant.scoped for grant in grants)}

        reads = [described(op) for op in operations if is_read_operation(op.method, bool(op.read_only))]
        writes = [described(op) for op in operations if not is_read_operation(op.method, bool(op.read_only))]
        return {"source_type": SOURCE_TYPE, "work_states": WORK_STATES, "definition": definition.key,
                "name": definition.name, "list_operations": reads, "write_operations": writes,
                "fields": {"required": ["key", "title", "status"],
                           "optional": ["id", "description", "type", "priority", "reporter", "assignee", "url",
                                        "parent", "labels", "updated_at", "created_at"]},
                "template_keys": ["source_key", "source_id", "target_status", "to_state"], "reason": None}

    async def count(self, db: AsyncSession, project_id: str, connection_id: str,
                    what: dict[str, Any]) -> dict[str, Any]:
        return {"count": None, "reason": "not_counted"}

    async def sample(self, db: AsyncSession, *, user: User, project_id: str, draft: dict[str, Any]
                     ) -> dict[str, Any]:
        """One page of the draft's list operation, mapped, nothing stored: what the intake would import."""
        await self.require_connection(db, project_id, draft.get("connection_id"))
        config = normalize_config(_what(draft), _how(draft), draft.get("schedule"))
        key = str(draft["connection_id"]).strip()
        intake = {**config, "definition": key}
        try:
            definition, operation = await resolve_list(db, project_id, key, config["operation"])
            role = acting_role(operation, config["role"], project_id)
            context = IntakeCallContext(user_id=user.id, project_id=project_id, db=db, acting_role=role)
            page = await read_pages(db, definition=definition, operation=operation, context=context,
                                    arguments=config["arguments"], max_items=config["max_items"], max_pages=1)
        except IntakeSourceError as error:
            raise source_error(error) from None
        listed = Listed(entries=[(operation.op_key, record) for record in page.records], complete=page.complete,
                        instance=key)
        row = WorkItemSyncConfig(project_id=project_id, source_type=SOURCE_TYPE, source_instance=key)
        mapped, invalid, closed = [], 0, 0
        for group, record in listed.entries:
            payload = RECORDS.payload(row, listed, group, record, intake)
            if payload is None:
                invalid += 1
                continue
            closed += RECORDS.is_closed(record, intake)
            if len(mapped) < PREVIEW_ITEMS:
                mapped.append({name: payload.get(name) for name in (*SAMPLE_KEYS, "reporter", "assignee",
                                                                    "parent_key", "labels_json")})
        return {"records": len(page.records), "skipped_invalid": invalid, "closed": closed,
                "dropped_out_of_scope": page.dropped, "last_page": page.complete, "role": role, "items": mapped}

    async def preview(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig) -> dict[str, Any]:
        return await rest_intake.run_intake(db, row=row, user=user, dry_run=True)

    async def sync(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig, trigger: str) -> dict[str, Any]:
        return await rest_intake.run_intake(db, row=row, user=user, dry_run=False, trigger=trigger)

    async def reschedule(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig) -> None:
        await rest_intake.schedule(db, row, user)

    async def run_scheduled(self, db: AsyncSession, *, task: Task, task_run: Any) -> dict[str, Any]:
        row = await db.get(WorkItemSyncConfig, str((task.config or {}).get("sync_config_id") or ""))
        owner = await db.get(User, task.owner_id)
        if row is None or owner is None or row.source_type != SOURCE_TYPE:
            raise ValueError("custom_rest intake task without its config or owner")
        result = await self.sync(db, user=owner, row=row, trigger=TRIGGER_SCHEDULED)
        return {"mode": task.task_type, "sync_config_id": row.id, "sync_run_id": result["sync_run"]["id"],
                "summary": result["summary"]}


SOURCE = CustomRestIntakeSource()

__all__ = ["SOURCE", "CustomRestIntakeSource"]
