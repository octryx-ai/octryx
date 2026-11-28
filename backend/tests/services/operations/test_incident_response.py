from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import ValidationError
from app.models import KillSwitchLog
from app.models.runtime.incident_response import ACTION_SAFE_MODE_OFF, SAFE_MODE_ACTIVE, SAFE_MODE_OFF
from app.services.incident_response.safe_mode import (
    deactivate_safe_mode,
    get_safe_mode_status,
    is_blocked_by_safe_mode,
)
from tests.services.operations.incident_response_support import _activate, _make_project


@pytest.mark.asyncio
async def test_get_safe_mode_status_default_off(db: AsyncSession):
    status = await get_safe_mode_status(db, project_id=None)
    assert status["state"] == SAFE_MODE_OFF


@pytest.mark.asyncio
async def test_get_safe_mode_status_reports_the_active_project_scope_only(db: AsyncSession, auth_user):
    project = await _make_project(db)
    await _activate(db, user_id=str(auth_user.id), reason="Project incident", project_id=project.id,
                    incident_id="INC-001")

    status = await get_safe_mode_status(db, project_id=project.id)
    assert status["state"] == SAFE_MODE_ACTIVE
    assert status["incident_id"] == "INC-001"
    assert (await get_safe_mode_status(db, project_id=None))["state"] == SAFE_MODE_OFF


@pytest.mark.asyncio
async def test_deactivate_safe_mode_logs_the_reason(db: AsyncSession, auth_user):
    await _activate(db, user_id=str(auth_user.id), reason="Test", incident_id="INC-002")

    result = await deactivate_safe_mode(db, user_id=str(auth_user.id), reason="Resolved")

    assert result["state"] == SAFE_MODE_OFF
    assert result["deactivated_by"] == str(auth_user.id)
    log = (await db.execute(select(KillSwitchLog).where(KillSwitchLog.id == result["kill_switch_log_id"]))).scalar_one()
    assert (log.action, log.reason, log.incident_id) == (ACTION_SAFE_MODE_OFF, "Resolved", "INC-002")


@pytest.mark.asyncio
async def test_deactivate_safe_mode_not_active_raises(db: AsyncSession, auth_user):
    with pytest.raises(ValidationError, match="not active"):
        await deactivate_safe_mode(db, user_id=str(auth_user.id))


@pytest.mark.asyncio
async def test_is_blocked_by_safe_mode_when_active(db: AsyncSession, auth_user):
    await _activate(db, user_id=str(auth_user.id), reason="Blocked")
    blocked, reason = await is_blocked_by_safe_mode(db)
    assert blocked is True
    assert reason == "Blocked"


@pytest.mark.asyncio
async def test_is_blocked_by_safe_mode_when_off(db: AsyncSession):
    blocked, reason = await is_blocked_by_safe_mode(db)
    assert blocked is False
    assert reason is None


@pytest.mark.asyncio
async def test_is_blocked_by_project_safe_mode(db: AsyncSession, auth_user):
    project = await _make_project(db)
    await _activate(db, user_id=str(auth_user.id), reason="Project block", project_id=project.id)

    blocked, reason = await is_blocked_by_safe_mode(db, project_id=project.id)
    assert blocked is True
    assert reason == "Project block"

    other = await _make_project(db, name="other")
    blocked, reason = await is_blocked_by_safe_mode(db, project_id=other.id)
    assert blocked is False
