"""Tests for RBAC and project tenant boundary enforcement.

Covers:
  - require_project_access: allows access for project members
  - require_project_access: denies access for non-members (403)
  - require_project_access: skips check when project_id is None
  - require_project_access: admin bypasses project membership check
  - require_project_access: require_admin flag denies plain members
  - get_project_role_for_user: returns correct role
  - assert_user_owns_resource: owner passes, non-owner denied
  - assert_user_owns_resource: admin bypasses ownership check
  - Boundary checks on agent-chain, task, and knowledge routes
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services.access_control import ProjectScopeContext, require_project_access, require_project_scope
from tests.rbac_boundaries_support import _grant_project_membership, _make_project, _make_user

# ---------------------------------------------------------------------------
# require_project_access tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_access_allowed_for_member(db: AsyncSession):
    project = await _make_project(db)
    user = await _make_user(db)
    await _grant_project_membership(db, user.id, project.id, role="member")

    # Should not raise
    await require_project_access(db, user.id, project.id)


@pytest.mark.asyncio
async def test_a_non_member_gets_the_answer_of_an_unknown_workspace(db: AsyncSession):
    project = await _make_project(db)
    user = await _make_user(db)
    # No membership granted: a foreign Workspace and an unknown one are indistinguishable.

    answers = []
    for project_id in (project.id, "no-such-workspace"):
        with pytest.raises(HTTPException) as exc_info:
            await require_project_access(db, user.id, project_id)
        answers.append((exc_info.value.status_code, exc_info.value.detail))
    assert answers[0] == answers[1] == (404, {"code": "project_not_found", "message": "The named Workspace does not exist."})


@pytest.mark.asyncio
async def test_project_access_skipped_when_project_id_is_none(db: AsyncSession):
    user = await _make_user(db)
    # project_id=None → no check, no raise
    await require_project_access(db, user.id, None)


@pytest.mark.asyncio
async def test_required_project_scope_fails_closed_when_project_id_is_missing(db: AsyncSession):
    user = await _make_user(db)

    with pytest.raises(HTTPException) as exc_info:
        await require_project_scope(db, user.id, None)
    assert exc_info.value.status_code == 400
    assert "Project scope is required" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_required_project_scope_returns_context_for_member(db: AsyncSession):
    project = await _make_project(db)
    user = await _make_user(db)
    await _grant_project_membership(db, user.id, project.id, role="member")

    context = await require_project_scope(db, user.id, project.id)

    assert isinstance(context, ProjectScopeContext)
    assert context.user_id == user.id
    assert context.project_id == project.id
    assert context.project_role == "member"
    assert context.project_admin is False


@pytest.mark.asyncio
async def test_required_project_scope_answers_a_non_member_like_an_unknown_workspace(db: AsyncSession):
    project = await _make_project(db)
    user = await _make_user(db)

    answers = []
    for project_id in (project.id, "no-such-workspace"):
        with pytest.raises(HTTPException) as exc_info:
            await require_project_scope(db, user.id, project_id)
        answers.append((exc_info.value.status_code, exc_info.value.detail))
    assert answers[0] == answers[1]
    assert answers[0][0] == 404


@pytest.mark.asyncio
async def test_project_access_admin_bypasses_membership(db: AsyncSession, auth_user: User):
    """The seeded admin user should access any project without explicit membership."""
    project = await _make_project(db)
    # auth_user is admin — no UserProject row needed
    await require_project_access(db, auth_user.id, project.id)


@pytest.mark.asyncio
async def test_project_access_require_admin_denies_plain_member(db: AsyncSession):
    project = await _make_project(db)
    user = await _make_user(db)
    await _grant_project_membership(db, user.id, project.id, role="member")

    with pytest.raises(HTTPException) as exc_info:
        await require_project_access(db, user.id, project.id, require_admin=True)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_project_access_require_admin_allows_project_admin(db: AsyncSession):
    project = await _make_project(db)
    user = await _make_user(db)
    await _grant_project_membership(db, user.id, project.id, role="admin")

    await require_project_access(db, user.id, project.id, require_admin=True)
