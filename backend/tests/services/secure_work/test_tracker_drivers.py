"""Tracker write-back dispatch: explicit driver per source type, no guessing."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project
from app.services.secure_work.platform_items import create_platform_work_item
from app.services.secure_work.tracker_drivers import (
    TRACKER_STATE_SYNC_DRIVERS,
    execute_tracker_state_sync,
)


class _ExecuteWorkflow:
    sync_policy_json = {"sync_mode": "execute"}


_PREVIEW = {"jira_sync_preview": {"sync_back": True, "transition": "Start Progress"}}


@pytest.mark.asyncio
async def test_platform_items_are_local_only(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    item = await create_platform_work_item(db, current_user=auth_user, project_id=project.id, title="local")
    result = await execute_tracker_state_sync(db, item=item, workflow=_ExecuteWorkflow(), preview=_PREVIEW)
    assert result is None


@pytest.mark.asyncio
async def test_unknown_source_type_is_an_explicit_no_driver_result(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    item = await create_platform_work_item(db, current_user=auth_user, project_id=project.id, title="x")
    item.source_type = "servicenow"  # no driver registered yet
    result = await execute_tracker_state_sync(db, item=item, workflow=_ExecuteWorkflow(), preview=_PREVIEW)
    assert result == {"status": "no_driver", "source_type": "servicenow"}


def test_driver_registry_covers_known_source_types():
    assert set(TRACKER_STATE_SYNC_DRIVERS) == {"jira", "platform"}
