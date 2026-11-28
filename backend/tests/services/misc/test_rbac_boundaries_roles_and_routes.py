"""Project roles, resource ownership with its admin bypass, and the project boundary on agent-chain, task and knowledge routes."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services.access_control import assert_user_owns_resource, get_project_role_for_user, require_project_access
from tests.services.misc.rbac_boundaries_support import _grant_project_membership, _make_project, _make_user, _uid


@pytest.mark.asyncio
async def test_get_project_role_returns_correct_role(db: AsyncSession):
    project = await _make_project(db)
    user = await _make_user(db)
    await _grant_project_membership(db, user.id, project.id, role="owner")

    role = await get_project_role_for_user(db, user.id, project.id)
    assert role == "owner"


@pytest.mark.asyncio
async def test_get_project_role_returns_none_for_non_member(db: AsyncSession):
    project = await _make_project(db)
    user = await _make_user(db)

    role = await get_project_role_for_user(db, user.id, project.id)
    assert role is None


@pytest.mark.asyncio
async def test_get_project_role_admin_returns_admin(db: AsyncSession, auth_user: User):
    project = await _make_project(db)
    role = await get_project_role_for_user(db, auth_user.id, project.id)
    assert role == "admin"


@pytest.mark.asyncio
async def test_assert_owns_resource_passes_for_owner(db: AsyncSession):
    user_id = _uid()
    await assert_user_owns_resource(user_id, user_id, db)


@pytest.mark.asyncio
async def test_assert_owns_resource_denied_for_non_owner(db: AsyncSession):
    owner_id = _uid()
    other_user = await _make_user(db)

    with pytest.raises(HTTPException) as exc_info:
        await assert_user_owns_resource(owner_id, other_user.id, db)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_assert_owns_resource_admin_bypasses_ownership(db: AsyncSession, auth_user: User):
    owner_id = _uid()
    await assert_user_owns_resource(owner_id, auth_user.id, db)


@pytest.mark.asyncio
async def test_agent_chain_list_templates_denies_non_member_project(
    db: AsyncSession,
):
    project = await _make_project(db)
    user = await _make_user(db)

    with pytest.raises(HTTPException) as exc_info:
        await require_project_access(db, user.id, project.id)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_task_create_denied_for_foreign_project(db: AsyncSession):
    project = await _make_project(db)
    attacker = await _make_user(db)

    with pytest.raises(HTTPException) as exc_info:
        await require_project_access(db, attacker.id, project.id)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_task_create_allowed_for_member(db: AsyncSession):
    project = await _make_project(db)
    user = await _make_user(db)
    await _grant_project_membership(db, user.id, project.id)

    await require_project_access(db, user.id, project.id)


@pytest.mark.asyncio
async def test_knowledge_list_denied_for_foreign_project(db: AsyncSession):
    project = await _make_project(db)
    attacker = await _make_user(db)

    with pytest.raises(HTTPException) as exc_info:
        await require_project_access(db, attacker.id, project.id)
    assert exc_info.value.status_code == 404
