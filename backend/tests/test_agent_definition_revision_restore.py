"""Restoring a revision: it rebuilds steps, header and lineage, requires a published revision, re-authorizes the target Workspace, never moves ownership and leaves everything untouched when it fails."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDefinition
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revision_store import (
    REVISION_NUMBER_CONFLICT_DETAIL,
    list_agent_definition_revisions,
    load_definition_steps,
)
from app.services.agent_definition_revisions import create_draft_revision, restore_revision
from tests.agent_definition_revision_fixtures import (
    DEFINITION_GOAL,
    DEFINITION_NAME,
    admin_user,
    make_definition,
    make_project,
    make_step,
    make_user,
)
from tests.agent_definition_revision_lifecycle_support import _force_revision_number

# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


async def test_restore_rebuilds_steps_header_and_lineage(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=2)
    source = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=source, published_by=admin.id)

    # Drift the live aggregate: rename, drop step 2, append a third step.
    definition.name = "Renamed after publication"
    definition.goal = "Drifted goal"
    live_steps = await load_definition_steps(db, definition.id)
    await db.delete(live_steps[1])
    await db.flush()
    await make_step(db, definition, position=2, name="Added later")
    await make_step(db, definition, position=3, name="Also added later")

    restored = await restore_revision(
        db, revision=source, definition=definition, current_user=admin
    )

    assert definition.name == DEFINITION_NAME
    assert definition.goal == DEFINITION_GOAL
    steps_after = await load_definition_steps(db, definition.id)
    assert [(step.position, step.name) for step in steps_after] == [
        (1, "Step 1"),
        (2, "Step 2"),
    ]
    assert restored.restored_from_revision_id == source.id
    assert restored.status == "published"
    assert restored.checksum == source.checksum
    assert restored.revision_number == source.revision_number + 1
    assert restored.created_by == admin.id and restored.published_by == admin.id


async def test_restore_recreates_a_step_deleted_from_the_middle(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=3)
    source = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=source, published_by=admin.id)

    live_steps = await load_definition_steps(db, definition.id)
    await db.delete(live_steps[1])
    await db.flush()
    assert len(await load_definition_steps(db, definition.id)) == 2

    await restore_revision(
        db, revision=source, definition=definition, current_user=admin
    )

    assert [
        (step.position, step.name, step.allowed_tools)
        for step in await load_definition_steps(db, definition.id)
    ] == [
        (1, "Step 1", ["knowledge_search"]),
        (2, "Step 2", ["knowledge_search"]),
        (3, "Step 3", ["knowledge_search"]),
    ]


async def test_restore_removes_duplicate_live_positions(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    source = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=source, published_by=admin.id)
    await make_step(db, definition, position=1, name="Duplicate position")

    await restore_revision(
        db, revision=source, definition=definition, current_user=admin
    )

    assert [
        (step.position, step.name)
        for step in await load_definition_steps(db, definition.id)
    ] == [(1, "Step 1")]


async def test_restore_requires_a_published_revision(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)
    draft = await create_draft_revision(db, definition=definition, created_by=admin.id)

    with pytest.raises(HTTPException) as excinfo:
        await restore_revision(
            db, revision=draft, definition=definition, current_user=admin
        )
    assert excinfo.value.status_code == 409


async def test_restore_refuses_and_changes_nothing_when_a_reference_vanished(
    db: AsyncSession,
):
    admin = await admin_user(db)
    project = await make_project(db)
    definition = await make_definition(db, owner=admin, project_id=project.id)
    source = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=source, published_by=admin.id)

    definition.name = "Drifted name"
    definition.project_id = None
    await db.flush()
    await db.delete(project)
    await db.flush()

    with pytest.raises(HTTPException) as excinfo:
        await restore_revision(
            db, revision=source, definition=definition, current_user=admin
        )

    assert excinfo.value.status_code == 422
    assert "unknown_project" in {issue["code"] for issue in excinfo.value.detail["issues"]}
    assert definition.name == "Drifted name"
    assert len(await list_agent_definition_revisions(db, definition.id)) == 1


async def test_restore_does_not_move_definition_ownership(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)
    source = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=source, published_by=admin.id)

    restorer = await make_user(db, label="restorer")
    restored = await restore_revision(
        db, revision=source, definition=definition, current_user=restorer
    )

    assert definition.owner_id == admin.id
    assert restored.created_by == restorer.id


async def test_restore_target_authorization_is_enforced_by_the_service(
    db: AsyncSession,
):
    """The target-Workspace rule lives in the writer, not only in the route.

    The snapshot was taken while the definition belonged to a Workspace the
    caller has no role in. Calling the service directly — as any alternate caller
    would — must still be refused, and nothing may be written.
    """
    holder = await make_user(db, label="holder")
    other_workspace = await make_project(db)
    definition = await make_definition(
        db, owner=holder, project_id=other_workspace.id
    )
    source = await create_draft_revision(db, definition=definition, created_by=holder.id)
    await publish_revision(db, revision=source, published_by=holder.id)

    # The Workspace assignment is removed from the live row after the snapshot.
    definition.name = "Drifted while unassigned"
    definition.project_id = None
    await db.flush()

    with pytest.raises(HTTPException) as excinfo:
        await restore_revision(
            db, revision=source, definition=definition, current_user=holder
        )

    assert excinfo.value.status_code == 403
    assert "target Workspace" in excinfo.value.detail
    assert definition.project_id is None
    assert definition.name == "Drifted while unassigned"
    assert len(await list_agent_definition_revisions(db, definition.id)) == 1


async def test_restore_collision_leaves_the_live_aggregate_untouched(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """A restore that loses the numbering race must be all-or-nothing.

    ``restore_revision`` rewrites the header and the steps *before* appending its
    revision row, so the 409 is raised with the live aggregate already rewritten
    in the session. Atomicity comes from the production transaction pattern:
    ``app.db.get_db`` rolls the whole request back on any exception. This test
    commits the drifted state first, so the rollback has a baseline to return to,
    then asserts the drift survived and no revision was appended.
    """
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=2)
    source = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=source, published_by=admin.id)

    # Drift both halves of the aggregate: header fields and the step set.
    definition.name = "Drifted before the collision"
    definition.goal = "Goal drifted before the collision"
    live_steps = await load_definition_steps(db, definition.id)
    await db.delete(live_steps[1])
    await db.flush()
    await make_step(db, definition, position=2, name="Added after publication")
    await make_step(db, definition, position=3, name="Also added after publication")
    await db.commit()

    # Identifiers are read before the failing call: a rollback expires every
    # loaded attribute, and a lazy refresh from an assertion would be sync IO.
    definition_id = definition.id
    drifted_steps = [
        (step.position, step.name)
        for step in await load_definition_steps(db, definition_id)
    ]
    revisions_before = {
        revision.id
        for revision in await list_agent_definition_revisions(db, definition_id)
    }

    _force_revision_number(monkeypatch, int(source.revision_number))

    with pytest.raises(HTTPException) as excinfo:
        await restore_revision(
            db, revision=source, definition=definition, current_user=admin
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == REVISION_NUMBER_CONFLICT_DETAIL

    # The production pattern: get_db rolls back the request on any exception.
    await db.rollback()

    reloaded = await db.get(AgentDefinition, definition_id)
    assert reloaded is not None
    assert reloaded.name == "Drifted before the collision"
    assert reloaded.goal == "Goal drifted before the collision"
    assert [
        (step.position, step.name)
        for step in await load_definition_steps(db, definition_id)
    ] == drifted_steps
    assert {
        revision.id
        for revision in await list_agent_definition_revisions(db, definition_id)
    } == revisions_before
