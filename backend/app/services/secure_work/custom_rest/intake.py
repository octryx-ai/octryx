"""Saving, scheduling and running a Custom REST intake."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, Scheduler, Task, User, WorkItemSyncConfig
from ....models.project.task import TASK_DEFINITION_BINDING
from ...rest_connector.common import is_read_operation
from ..intake import pipeline
from ..intake.registry import GENERIC_SYNC_TASK_TYPE
from ..intake.runs import TRIGGER_MANUAL
from ..intake.schedule import PRESET_CRONS, cron_of
from ..servicenow.source import IntakeSourceError
from ..sync_policy import SOURCE_SYNC_MODE_KEY
from .config import SOURCE_TYPE, refused
from .listing import acting_role, operation_of, resolve_list
from .records import RECORDS

CONFIG_AUDIT_ACTION = "secure_work.custom_rest_intake.configured"


def _refused_from(error: IntakeSourceError, field: str):  # noqa: ANN202 - an HTTPException
    return refused(field, str(error).split(": ", 1)[-1], code=error.code)


async def check_config(db: AsyncSession, project_id: str, definition_key: str, config: Mapping[str, Any]) -> None:
    try:
        definition, operation = await resolve_list(db, project_id, definition_key, config["operation"])
        acting_role(operation, config["role"], project_id)
    except IntakeSourceError as error:
        raise _refused_from(error, "what.role" if "role" in error.code else "what.operation") from None
    write_back = config.get("write_back")
    if write_back:
        target = await operation_of(db, definition, write_back["operation"])
        if target is None or is_read_operation(target.method, bool(target.read_only)):
            raise refused("how.write_back.operation", "must be an enabled write operation of the same API",
                          code="custom_rest_write_back_operation_invalid")


def _stored(row: WorkItemSyncConfig, config: Mapping[str, Any]) -> None:
    row.filters_json = {"operation": config["operation"], "role": config["role"], "arguments": config["arguments"]}
    row.field_mapping_json = {"fields": config["fields"], "state_mapping": config["state_mapping"],
                              "closed_statuses": config["closed_statuses"]}
    kept = {key: value for key, value in dict(row.sync_options_json or {}).items()
            if key.startswith("automation_") or key == SOURCE_SYNC_MODE_KEY}  # the intake's own (``intake/setup``)
    row.sync_options_json = {**kept, **{key: config[key] for key in ("schedule", "max_items", "max_pages",
                                                                     "auto_analyze_new", "write_back")}}


async def put_intake(db: AsyncSession, *, project_id: str, definition_key: str, name: str, config: Mapping[str, Any],
                     user: User, row: WorkItemSyncConfig | None) -> WorkItemSyncConfig:
    await check_config(db, project_id, definition_key, config)
    if row is None:
        row = WorkItemSyncConfig(name=name[:220], project_id=project_id, source_type=SOURCE_TYPE,
                                 source_instance=definition_key, connection_id=definition_key, created_by=user.id,
                                 is_active=False)
        db.add(row)
    row.name = name[:220]
    _stored(row, config)
    row.updated_by = user.id
    await db.flush()
    await schedule(db, row, user)
    db.add(AuditLog(user_id=user.id, action=CONFIG_AUDIT_ACTION, resource_type="work_item_sync_config",
                    project_id=row.project_id,
                    resource_id=row.id, details={"project_id": project_id, "definition": definition_key,
                                                 "operation": config["operation"], "role": config["role"],
                                                 "schedule": config["schedule"]["preset"]}))
    await db.flush()
    return row


async def sync_task(db: AsyncSession, row: WorkItemSyncConfig) -> Task | None:
    tasks = (await db.execute(select(Task).where(Task.task_type == GENERIC_SYNC_TASK_TYPE))).scalars().all()
    return next((task for task in tasks if (task.config or {}).get("sync_config_id") == row.id), None)


async def schedule(db: AsyncSession, row: WorkItemSyncConfig, user: User) -> Task:
    task = await sync_task(db, row)
    if task is None:
        task = Task(name=f"Custom REST intake · {row.name}", task_type=GENERIC_SYNC_TASK_TYPE,
                    agent_type="operations", project_id=row.project_id, owner_id=user.id, config={},
                    dispatch_binding=TASK_DEFINITION_BINDING)
        db.add(task)
    task.config = {"sync_config_id": row.id, "local_execution": "deterministic", "requires_worker": False,
                   "required_domain": SOURCE_TYPE}
    cron = cron_of(dict(row.sync_options_json or {}).get("schedule") or {}) if row.is_active else None
    task.is_active = cron is not None
    await db.flush()
    scheduler = (await db.execute(select(Scheduler).where(Scheduler.task_id == task.id))).scalars().first()
    if scheduler is None:
        scheduler = Scheduler(name=f"Custom REST intake · {row.name}", task_id=task.id, owner_id=user.id,
                              cron_expression="")
        db.add(scheduler)
    scheduler.cron_expression = cron or PRESET_CRONS["every_15_min"]
    scheduler.is_active = cron is not None
    await db.flush()
    return task


async def run_intake(db: AsyncSession, *, row: WorkItemSyncConfig, user: User, dry_run: bool,
                     trigger: str = TRIGGER_MANUAL) -> dict[str, Any]:
    return await pipeline.run_intake(db, source=RECORDS, row=row, user=user, dry_run=dry_run, trigger=trigger)


__all__ = ["CONFIG_AUDIT_ACTION", "check_config", "put_intake", "run_intake", "schedule", "sync_task"]
