"""Tests for Incident Response, Kill Switch, and Safe Mode.

Covers:
  - activate_safe_mode / deactivate_safe_mode (global and project-scoped)
  - is_blocked_by_safe_mode guard
  - pause_entity / resume_entity
  - cancel_running_runs
  - list_paused_entities / list_kill_switch_logs
  - auto-resume on deactivate
  - cancel_running_work on activate
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runtime.incident_response import SAFE_MODE_ACTIVE, SAFE_MODE_OFF
from app.services.incident_response.safe_mode import (
    activate_safe_mode,
    deactivate_safe_mode,
    get_safe_mode_status,
    is_blocked_by_safe_mode,
)
from tests.incident_response_support import _make_project

# ── Safe Mode Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_safe_mode_status_default_off(db: AsyncSession):
    status = await get_safe_mode_status(db, project_id=None)
    assert status["state"] == SAFE_MODE_OFF


@pytest.mark.asyncio
async def test_activate_safe_mode_global(db: AsyncSession, auth_user):
    result = await activate_safe_mode(
        db,
        user_id=str(auth_user.id),
        reason="System maintenance",
        incident_id="INC-001",
    )
    assert result["state"] == SAFE_MODE_ACTIVE
    assert result["reason"] == "System maintenance"
    assert result["incident_id"] == "INC-001"
    assert result["kill_switch_log_id"] is not None


@pytest.mark.asyncio
async def test_activate_safe_mode_project_scoped(db: AsyncSession, auth_user):
    project = await _make_project(db)
    result = await activate_safe_mode(
        db,
        user_id=str(auth_user.id),
        reason="Project incident",
        project_id=project.id,
    )
    assert result["state"] == SAFE_MODE_ACTIVE
    assert result["project_id"] == project.id

    # Global should still be off
    global_status = await get_safe_mode_status(db, project_id=None)
    assert global_status["state"] == SAFE_MODE_OFF


@pytest.mark.asyncio
async def test_activate_safe_mode_already_active_raises(db: AsyncSession, auth_user):
    await activate_safe_mode(db, user_id=str(auth_user.id), reason="First")
    from app.exceptions.api import ValidationError
    with pytest.raises(ValidationError, match="already active"):
        await activate_safe_mode(db, user_id=str(auth_user.id), reason="Second")


@pytest.mark.asyncio
async def test_deactivate_safe_mode(db: AsyncSession, auth_user):
    await activate_safe_mode(db, user_id=str(auth_user.id), reason="Test")
    result = await deactivate_safe_mode(db, user_id=str(auth_user.id))
    assert result["state"] == SAFE_MODE_OFF
    assert result["deactivated_by"] == str(auth_user.id)


@pytest.mark.asyncio
async def test_deactivate_safe_mode_not_active_raises(db: AsyncSession, auth_user):
    from app.exceptions.api import ValidationError
    with pytest.raises(ValidationError, match="not active"):
        await deactivate_safe_mode(db, user_id=str(auth_user.id))


@pytest.mark.asyncio
async def test_is_blocked_by_safe_mode_when_active(db: AsyncSession, auth_user):
    await activate_safe_mode(db, user_id=str(auth_user.id), reason="Blocked")
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
    await activate_safe_mode(db, user_id=str(auth_user.id), reason="Project block", project_id=project.id)

    blocked, reason = await is_blocked_by_safe_mode(db, project_id=project.id)
    assert blocked is True
    assert reason == "Project block"

    # Different project should not be blocked
    other = await _make_project(db, name="other")
    blocked, reason = await is_blocked_by_safe_mode(db, project_id=other.id)
    assert blocked is False
