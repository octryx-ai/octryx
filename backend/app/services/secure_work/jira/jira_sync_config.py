"""Jira intake configurations: create, update and read (the run itself lives in ``jira_sync``)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    User,
    WorkItemSyncConfig,
)
from ...access_control import require_existing_workspace
from ..intake.connections import named_intake_connection
from ..jira_values import blank_to_none, object_value
from ..serializers import serialize_sync_config
from ..workflow_access import require_project_access
from ..workspace_immutable import require_unchanged_workspace
from .jira_filters import (
    normalize_jira_sync_filters,
)
from .jira_scope import (
    check_intake_config,
)
from .jira_sync_schedule import normalize_jira_sync_options, sync_jira_work_item_scheduler


async def create_jira_sync_config(
    db: AsyncSession,
    *,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    project_id = blank_to_none(payload.get("project_id"))
    await require_existing_workspace(db, current_user.id, project_id)
    await require_project_access(db, current_user, project_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    # One Workspace and the connection it names (the setup checked it is one of the Workspace's).
    connection_id = named_intake_connection(project_id, payload.get("connection_id"))
    filters = normalize_jira_sync_filters(payload.get("filters") if isinstance(payload.get("filters"), dict) else {})
    row = WorkItemSyncConfig(
        name=name[:220],
        description=str(payload.get("description") or "").strip() or None,
        project_id=project_id,
        source_type="jira",
        source_instance=connection_id,
        connection_id=connection_id,
        filters_json=filters,
        field_mapping_json=object_value(payload.get("field_mapping")),
        sync_options_json=object_value(payload.get("sync_options")),
        is_active=bool(payload.get("is_active", True)),
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(row)
    await db.flush()
    await check_intake_config(db, row)  # allowlist, status mapping targets
    await sync_jira_work_item_scheduler(db, config=row, current_user=current_user)
    return serialize_sync_config(row)


async def update_jira_sync_config(
    db: AsyncSession,
    *,
    config_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    row = await get_jira_sync_config(db, config_id)
    if "project_id" in payload:
        require_unchanged_workspace(row.project_id, blank_to_none(payload.get("project_id")), what="intake")
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name is required")
        row.name = name[:220]
    if "description" in payload:
        row.description = str(payload.get("description") or "").strip() or None
    if "connection_id" in payload:
        # The item identity (``source_instance``) of an existing intake stays; only the connection changes.
        wanted = payload.get("connection_id", row.connection_id)
        row.connection_id = named_intake_connection(row.project_id, wanted)
    if "filters" in payload:
        row.filters_json = normalize_jira_sync_filters(
            payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
        )
    if "field_mapping" in payload:
        row.field_mapping_json = object_value(payload.get("field_mapping"))
    if "sync_options" in payload:
        incoming = object_value(payload.get("sync_options"))
        row.sync_options_json = normalize_jira_sync_options({**object_value(row.sync_options_json), **incoming})
    if "is_active" in payload:
        row.is_active = bool(payload.get("is_active"))
    row.updated_by = current_user.id
    await db.flush()
    await check_intake_config(db, row)
    await sync_jira_work_item_scheduler(db, config=row, current_user=current_user)
    return serialize_sync_config(row)


async def get_jira_sync_config(db: AsyncSession, config_id: str) -> WorkItemSyncConfig:
    row = await db.get(WorkItemSyncConfig, config_id)
    if row is None or row.source_type != "jira":
        raise HTTPException(status_code=404, detail="Jira sync config not found")
    return row
