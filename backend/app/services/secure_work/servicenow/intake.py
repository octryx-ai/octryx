"""ServiceNow incidents and changes into the Workspace's work items, modelled on the Jira intake.

- **Config:** one ``WorkItemSyncConfig`` (``source_type`` ``servicenow``) per Workspace (``config.py``), saved by
  a Workspace admin or owner and audited.
- **Preview:** a dry run with counts and the first 10 records, recorded as a ``dry_run`` sync run.
- **Sync:** creates or updates work items, deduplicated by ``sys_id`` (``source_id``; the number is the
  ``source_key``): title, description, priority, assignment group, assignee, opened at, the ``nav_to`` link,
  and the mapped work state. A state set by an applied platform transition is never regressed by a sync. The
  item's own ``source_fields_json`` entries (e.g. ``platform_notes``) are kept; ServiceNow's live under
  ``servicenow``.
- **Closing:** a listed record in a closed state, a record closed since the last successful sync (Table API,
  ``changed_since``), or (only when the listing is complete) an item whose record left the open set, moves to
  ``done`` with a state event and the record's state as ``source_status``. A closed record without an item is
  not imported. With a record limit (``source.effective_limit``: groups and/or services) only items inside it
  can leave the open set: an item outside it (reassigned, or listed before the limit, or stored without the
  limited field) is out of scope and stays as it is. Closed records of a Scripted REST listing are looked up
  in one query per chunk, not one per record (the listing pages the whole endpoint).
- **Schedule:** every 15 minutes by default (``manual`` turns it off); a deterministic
  ``secure_work_servicenow_sync`` task runs the sync on the intake's schedule preset.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, Scheduler, Task, User, WorkItemSyncConfig, WorkItemSyncRun
from ....models.project.task import TASK_DEFINITION_BINDING
from ...servicenow_record_limit import FIELDS, describe, record_limit
from ..intake import pipeline
from ..intake.connections import intake_connection_config, named_intake_connection
from ..intake.runs import TRIGGER_MANUAL
from ..intake.schedule import PRESET_CRONS, cron_of
from ..serializers import serialize_sync_config, serialize_sync_run
from ..sync_policy import SOURCE_SYNC_MODE_KEY
from .config import SOURCE_TYPE, normalize_intake, refused
from .records import RECORDS, intake_connection, intake_of
from .source import IntakeSourceError, connector_config, effective_limit

SERVICENOW_SYNC_TASK_TYPE = "secure_work_servicenow_sync"
CONFIG_AUDIT_ACTION = "secure_work.servicenow_intake.configured"
PREVIEW_ITEMS = pipeline.PREVIEW_ITEMS
MAX_RUNS_LISTED = 20


def describe_intake(row: WorkItemSyncConfig) -> dict[str, Any]:
    return {**serialize_sync_config(row), "intake": intake_of(row)}


async def get_intake(db: AsyncSession, project_id: str) -> WorkItemSyncConfig | None:
    return (
        await db.execute(
            select(WorkItemSyncConfig).where(
                WorkItemSyncConfig.project_id == project_id, WorkItemSyncConfig.source_type == SOURCE_TYPE
            ).order_by(WorkItemSyncConfig.created_at).limit(1)
        )
    ).scalar_one_or_none()


async def put_intake(
    db: AsyncSession, *, project_id: str, payload: Mapping[str, Any], user: User, activate_new: bool = True
) -> WorkItemSyncConfig:
    """Save the Workspace's intake; a new one is active unless ``activate_new`` is off (the setup drawer enables it
    only after a preview, ``intake/setup.py``)."""
    intake = normalize_intake(payload)
    row = await get_intake(db, project_id)
    # One of the Workspace's ServiceNow connections; without one in the payload the stored one is kept.
    wanted = payload.get("connection_id") or (row.connection_id if row is not None else None)
    connection_id = named_intake_connection(project_id, wanted)
    if row is None:
        row = WorkItemSyncConfig(name="ServiceNow intake", project_id=project_id, source_type=SOURCE_TYPE,
                                 created_by=user.id, is_active=activate_new)
        db.add(row)
    row.connection_id = connection_id
    try:  # an override must stay inside the connection's own limit (it may only narrow it)
        effective_limit(await intake_connection(db, row), intake)
    except IntakeSourceError as error:
        raise refused(error.field or "assignment_groups", str(error).split(": ", 1)[-1]) from None
    row.filters_json = {key: intake[key] for key in ("tables", "excluded_states", "sysparm_query",
                                                    "assignment_groups", "services")}
    row.field_mapping_json = {"state_mapping": intake["state_mapping"]}
    kept = {key: value for key, value in dict(row.sync_options_json or {}).items()
            if key.startswith("automation_") or key == SOURCE_SYNC_MODE_KEY}  # the intake's own (``intake/setup``)
    row.sync_options_json = {**kept, **{key: intake[key] for key in ("schedule", "max_items")}}
    row.updated_by = user.id
    await db.flush()
    await _schedule(db, row, intake, user)
    db.add(AuditLog(user_id=user.id, action=CONFIG_AUDIT_ACTION, resource_type="work_item_sync_config",
                    resource_id=row.id, details={"project_id": project_id, "tables": intake["tables"],
                                                 "connection_id": row.connection_id,
                                                 "schedule": intake["schedule"]["preset"]}))
    await db.flush()
    return row


async def limit_scope(db: AsyncSession, project_id: str, intake: Mapping[str, Any],
                      row: WorkItemSyncConfig | None = None) -> dict[str, Any]:
    """For the intake card, per limited field (``assignment_group_scope``, ``service_scope``): the connector's
    list, the intake's and the effective one (``None`` with ``code`` when an override is outside the connector's
    limit), plus the connector's ``filter_mode``; empty lists mean no condition."""
    config = (await intake_connection_config(db, row, SOURCE_TYPE) if row is not None else None) \
        or await connector_config(db, project_id)
    connector = describe(record_limit(config))
    try:
        effective: dict[str, Any] | None = describe(effective_limit(config, intake))
        code = None
    except IntakeSourceError as error:
        effective, code = None, error.code
    scopes: dict[str, Any] = {"filter_mode": connector["filter_mode"]}
    for spec, name in zip(FIELDS, ("assignment_group_scope", "service_scope"), strict=True):
        scope = {"connector": connector[spec.key], "intake": list(intake.get(spec.intake_field) or []),
                 "effective": effective[spec.key] if effective is not None else None}
        scopes[name] = scope if code is None else {**scope, "code": code}
    return scopes


async def _schedule(db: AsyncSession, row: WorkItemSyncConfig, intake: Mapping[str, Any], user: User) -> None:
    tasks = (await db.execute(select(Task).where(Task.task_type == SERVICENOW_SYNC_TASK_TYPE))).scalars().all()
    task = next((task for task in tasks if (task.config or {}).get("sync_config_id") == row.id), None)
    if task is None:
        task = Task(name="ServiceNow intake", task_type=SERVICENOW_SYNC_TASK_TYPE, agent_type="operations",
                    project_id=row.project_id, owner_id=user.id, config={}, dispatch_binding=TASK_DEFINITION_BINDING)
        db.add(task)
    task.config = {"sync_config_id": row.id, "local_execution": "deterministic", "requires_worker": False,
                   "required_domain": SOURCE_TYPE}
    cron = cron_of(intake["schedule"]) if row.is_active is not False else None
    task.is_active = cron is not None
    await db.flush()
    scheduler = (await db.execute(select(Scheduler).where(Scheduler.task_id == task.id))).scalars().first()
    if scheduler is None:
        scheduler = Scheduler(name="ServiceNow intake", task_id=task.id, owner_id=user.id, cron_expression="")
        db.add(scheduler)
    scheduler.cron_expression = cron or PRESET_CRONS["every_15_min"]
    scheduler.is_active = cron is not None
    await db.flush()


async def reschedule(db: AsyncSession, row: WorkItemSyncConfig, user: User) -> None:
    """Apply the stored schedule (and the intake's active state) to its scheduler."""
    await _schedule(db, row, intake_of(row), user)


async def run_intake(db: AsyncSession, *, row: WorkItemSyncConfig, user: User, dry_run: bool,
                     trigger: str = TRIGGER_MANUAL) -> dict[str, Any]:
    """Preview (``dry_run``) or sync the intake on the shared pipeline (``intake/pipeline``); the recorded run.
    Raises ``IntakeSourceError``."""
    return await pipeline.run_intake(db, source=RECORDS, row=row, user=user, dry_run=dry_run, trigger=trigger)


async def list_runs(db: AsyncSession, row: WorkItemSyncConfig) -> list[dict[str, Any]]:
    rows = (await db.execute(select(WorkItemSyncRun).where(WorkItemSyncRun.sync_config_id == row.id)
                             .order_by(WorkItemSyncRun.created_at.desc()).limit(MAX_RUNS_LISTED))).scalars()
    return [serialize_sync_run(run) for run in rows]


__all__ = [
    "SERVICENOW_SYNC_TASK_TYPE",
    "describe_intake",
    "get_intake",
    "limit_scope",
    "list_runs",
    "put_intake",
    "reschedule",
    "run_intake",
]
