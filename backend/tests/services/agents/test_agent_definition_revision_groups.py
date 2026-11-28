"""Validation accepts a group of the definition's workspace or an unassigned group for an owner-scope definition, and rejects foreign, unassigned or unknown groups otherwise."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_revision_publish import validate_revision
from app.services.agent_definition_revisions import create_draft_revision
from tests.agent_definition_revision_fixtures import admin_user, make_definition, make_group, make_project


async def test_validation_accepts_a_group_in_the_definition_workspace(db: AsyncSession):
    admin = await admin_user(db)
    project = await make_project(db)
    group = await make_group(db, owner=admin, project_id=project.id)
    definition = await make_definition(db, owner=admin, project_id=project.id)
    definition.group_id = group.id
    await db.flush()

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    assert result.ok, result.as_dict()


async def test_validation_rejects_a_group_from_another_workspace(db: AsyncSession):
    admin = await admin_user(db)
    project = await make_project(db)
    other_project = await make_project(db)
    group = await make_group(db, owner=admin, project_id=other_project.id)
    definition = await make_definition(db, owner=admin, project_id=project.id)
    definition.group_id = group.id
    await db.flush()

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    assert not result.ok
    mismatch = [issue for issue in result.issues if issue.code == "group_project_mismatch"]
    assert [issue.subject for issue in mismatch] == [group.id]
    assert "unknown_group" not in {issue.code for issue in result.issues}


async def test_validation_rejects_an_unassigned_group_for_a_workspace_definition(db: AsyncSession):
    admin = await admin_user(db)
    project = await make_project(db)
    group = await make_group(db, owner=admin, project_id=None)
    definition = await make_definition(db, owner=admin, project_id=project.id)
    definition.group_id = group.id
    await db.flush()

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    assert not result.ok
    assert "group_project_mismatch" in {issue.code for issue in result.issues}


async def test_validation_accepts_an_unassigned_group_for_an_owner_scope_definition(db: AsyncSession):
    admin = await admin_user(db)
    group = await make_group(db, owner=admin, project_id=None)
    definition = await make_definition(db, owner=admin)
    definition.group_id = group.id
    await db.flush()

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    assert result.ok, result.as_dict()


async def test_validation_rejects_an_unknown_group(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)
    definition.group_id = str(uuid.uuid4())
    await db.flush()

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    assert not result.ok
    assert "unknown_group" in {issue.code for issue in result.issues}
