"""Pausing and resuming flows, agent chains and tasks, and listing paused entities and kill-switch logs."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runtime.incident_response import TARGET_AGENT_CHAIN, TARGET_FLOW, TARGET_TASK
from app.services.incident_response.entities import pause_entity, resume_entity
from app.services.incident_response.queries import list_kill_switch_logs, list_paused_entities
from app.services.incident_response.safe_mode import activate_safe_mode, deactivate_safe_mode
from tests.incident_response_support import _make_agent_chain, _make_flow, _make_project, _make_task

# ── Pause / Resume Entity Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pause_entity_flow(db: AsyncSession, auth_user):
    project = await _make_project(db)
    flow = await _make_flow(db, project_id=project.id)
    assert flow.is_active is True

    result = await pause_entity(
        db, target_type=TARGET_FLOW, target_id=flow.id,
        user_id=str(auth_user.id), reason="Investigating issue",
    )
    assert result["status"] == "paused"
    assert result["paused_entity_id"] is not None

    # Verify flow is now inactive
    await db.refresh(flow)
    assert flow.is_active is False


@pytest.mark.asyncio
async def test_pause_entity_already_paused(db: AsyncSession, auth_user):
    project = await _make_project(db)
    flow = await _make_flow(db, project_id=project.id)
    await pause_entity(db, target_type=TARGET_FLOW, target_id=flow.id, user_id=str(auth_user.id))
    result = await pause_entity(db, target_type=TARGET_FLOW, target_id=flow.id, user_id=str(auth_user.id))
    assert result["status"] == "already_paused"


@pytest.mark.asyncio
async def test_resume_entity(db: AsyncSession, auth_user):
    project = await _make_project(db)
    flow = await _make_flow(db, project_id=project.id)
    await pause_entity(db, target_type=TARGET_FLOW, target_id=flow.id, user_id=str(auth_user.id))

    result = await resume_entity(db, target_type=TARGET_FLOW, target_id=flow.id, user_id=str(auth_user.id))
    assert result["status"] == "resumed"
    assert result["restored_is_active"] is True

    await db.refresh(flow)
    assert flow.is_active is True


@pytest.mark.asyncio
async def test_pause_agent_chain(db: AsyncSession, auth_user):
    project = await _make_project(db)
    chain = await _make_agent_chain(db, project_id=project.id)
    await pause_entity(db, target_type=TARGET_AGENT_CHAIN, target_id=chain.id, user_id=str(auth_user.id))
    await db.refresh(chain)
    assert chain.is_active is False


@pytest.mark.asyncio
async def test_pause_task(db: AsyncSession, auth_user):
    project = await _make_project(db)
    task = await _make_task(db, project_id=project.id)
    await pause_entity(db, target_type=TARGET_TASK, target_id=task.id, user_id=str(auth_user.id))
    await db.refresh(task)
    assert task.is_active is False


# ── List / Query Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_paused_entities(db: AsyncSession, auth_user):
    project = await _make_project(db)
    flow = await _make_flow(db, project_id=project.id)
    await pause_entity(db, target_type=TARGET_FLOW, target_id=flow.id, user_id=str(auth_user.id))

    paused = await list_paused_entities(db, project_id=project.id)
    assert len(paused) == 1
    assert paused[0]["entity_type"] == TARGET_FLOW
    assert paused[0]["entity_id"] == flow.id


@pytest.mark.asyncio
async def test_list_kill_switch_logs(db: AsyncSession, auth_user):
    await activate_safe_mode(db, user_id=str(auth_user.id), reason="Test")
    await deactivate_safe_mode(db, user_id=str(auth_user.id))

    logs = await list_kill_switch_logs(db)
    assert len(logs) >= 2
    actions = {log["action"] for log in logs}
    assert "safe_mode_on" in actions
    assert "safe_mode_off" in actions


@pytest.mark.asyncio
async def test_list_paused_entities_excludes_resumed(db: AsyncSession, auth_user):
    project = await _make_project(db)
    flow = await _make_flow(db, project_id=project.id)
    await pause_entity(db, target_type=TARGET_FLOW, target_id=flow.id, user_id=str(auth_user.id))
    await resume_entity(db, target_type=TARGET_FLOW, target_id=flow.id, user_id=str(auth_user.id))

    paused = await list_paused_entities(db, project_id=project.id, include_resumed=False)
    assert len(paused) == 0

    paused_all = await list_paused_entities(db, project_id=project.id, include_resumed=True)
    assert len(paused_all) == 1
