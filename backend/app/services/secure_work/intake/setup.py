"""Setting up an intake from one draft per intake, then preview → enable."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkItemSyncConfig, WorkItemSyncRun
from ..jira_values import object_value, string_list
from ..sync_policy import SOURCE_SYNC_MODE_KEY, SYNC_MODES, intake_sync_mode, sync_mode
from ..workspace_immutable import require_unchanged_workspace
from .registry import require_source, source_types
from .runs import TRIGGER_MANUAL
from .schedule import schedule_of

FIELD_KEYS = ("sprint_field", "team_field", "board_field", "story_points_field")
AUTOMATION_MODES = ("needs_review", "direct", "human_only")
CODE_PREVIEW_REQUIRED = "intake_preview_required"


def _refuse(field: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"state": "invalid_request", "field": field,
                                                  "message": f"{field} {message}"})


def _source_type(raw: object) -> str:
    if raw not in source_types():
        raise _refuse("source_type", f"must be one of: {', '.join(source_types())}")
    return str(raw)


def _how(raw: object) -> dict[str, Any]:
    how = object_value(raw)
    mode = str(how.get("automation_mode") or "needs_review")
    if mode not in AUTOMATION_MODES:
        raise _refuse("how.automation_mode", f"must be one of: {', '.join(AUTOMATION_MODES)}")
    fields = object_value(how.get("field_mapping"))
    return {
        "automation_mode": mode,
        "automation_labels": string_list(how.get("automation_labels")),
        "automation_exclude_labels": string_list(how.get("automation_exclude_labels")),
        "status_mapping": {str(key): str(value) for key, value in object_value(how.get("status_mapping")).items()
                           if str(key).strip() and str(value).strip()},
        "field_mapping": {key: str(fields[key]).strip() for key in FIELD_KEYS if str(fields.get(key) or "").strip()},
    }


def _sync_mode(how: dict[str, Any]) -> str:
    # Anything else is a 422, never guessed.
    raw = how.get(SOURCE_SYNC_MODE_KEY)
    if raw in (None, ""):
        return ""
    if raw not in SYNC_MODES:
        raise _refuse("how.sync_mode", f"must be one of: {', '.join(SYNC_MODES)} (or null to follow the workflow)")
    return str(raw)


def _store_sync_mode(row: WorkItemSyncConfig, how: dict[str, Any]) -> None:
    options = {key: value for key, value in dict(row.sync_options_json or {}).items() if key != SOURCE_SYNC_MODE_KEY}
    mode = _sync_mode(how)
    row.sync_options_json = {**options, SOURCE_SYNC_MODE_KEY: mode} if mode else options


def sync_mode_of(row: WorkItemSyncConfig, workflow_policy: Any = None) -> dict[str, Any]:
    own = intake_sync_mode(row.sync_options_json) or None
    workflow = sync_mode(workflow_policy) or None
    return {"own": own, "workflow": workflow, "effective": own or workflow}


def draft_of(row: WorkItemSyncConfig) -> dict[str, Any]:
    mapping = dict(row.field_mapping_json or {})
    options = dict(row.sync_options_json or {})
    source = require_source(row.source_type)
    what, status_mapping = source.draft_what(row)
    # A source's own ``how`` keys (Custom REST: its dotted field mapping, closed statuses, write-back).
    own_how = source.draft_how(row) if hasattr(source, "draft_how") else {}
    return {
        "id": row.id,
        "source_type": row.source_type,
        "name": row.name,
        "connection_id": row.connection_id,
        "is_active": bool(row.is_active),
        "what": what,
        "schedule": schedule_of(options),
        "how": {
            "automation_mode": str(options.get("automation_mode") or "needs_review"),
            "automation_labels": list(options.get("automation_labels") or []),
            "automation_exclude_labels": list(options.get("automation_exclude_labels") or []),
            "status_mapping": status_mapping,
            "field_mapping": {key: mapping[key] for key in FIELD_KEYS if mapping.get(key)},
            SOURCE_SYNC_MODE_KEY: intake_sync_mode(options) or None,
            **own_how,
        },
    }


async def save_intake(
    db: AsyncSession, *, user: User, project_id: str, draft: dict[str, Any], row: WorkItemSyncConfig | None = None
) -> WorkItemSyncConfig:
    if row is not None and "project_id" in draft:
        require_unchanged_workspace(row.project_id, draft["project_id"], what="intake")
    source_type = _source_type(row.source_type if row is not None else draft.get("source_type"))
    name = str(draft.get("name") or "").strip()
    if not name:
        raise _refuse("name", "is required")
    source = require_source(source_type)
    raw_how = object_value(draft.get("how"))
    if SOURCE_SYNC_MODE_KEY in raw_how:
        _sync_mode(raw_how)  # refused before the source stores anything
    await source.require_connection(db, project_id, draft.get("connection_id"))
    saved = await source.save(db, user=user, project_id=project_id, draft=draft, how=_how(draft.get("how")),
                              name=name, row=row)
    if SOURCE_SYNC_MODE_KEY in raw_how:
        _store_sync_mode(saved, raw_how)
        await db.flush()
    return saved


async def preview_intake(db: AsyncSession, *, user: User, row: WorkItemSyncConfig) -> dict[str, Any]:
    return await require_source(row.source_type).preview(db, user=user, row=row)


async def previewed_since_change(db: AsyncSession, row: WorkItemSyncConfig) -> bool:
    latest = (await db.execute(
        select(WorkItemSyncRun).where(WorkItemSyncRun.sync_config_id == row.id, WorkItemSyncRun.mode == "dry_run",
                                      WorkItemSyncRun.status == "completed")
        .order_by(WorkItemSyncRun.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    return latest is not None and (row.updated_at is None or latest.created_at >= row.updated_at)


async def set_intake_active(db: AsyncSession, *, user: User, row: WorkItemSyncConfig, active: bool) -> None:
    # Enabling requires a preview of the current settings.
    if active and not row.is_active and not await previewed_since_change(db, row):
        raise HTTPException(status_code=409, detail={"state": "needs_preview", "code": CODE_PREVIEW_REQUIRED,
                                                     "message": "Run a preview of the current settings first."})
    row.is_active = active
    row.updated_by = user.id
    await require_source(row.source_type).reschedule(db, user=user, row=row)
    await db.flush()


async def first_run(db: AsyncSession, *, user: User, row: WorkItemSyncConfig) -> dict[str, Any]:
    return await require_source(row.source_type).sync(db, user=user, row=row, trigger=TRIGGER_MANUAL)


__all__ = [
    "CODE_PREVIEW_REQUIRED",
    "draft_of",
    "first_run",
    "preview_intake",
    "previewed_since_change",
    "save_intake",
    "set_intake_active",
    "sync_mode_of",
]
