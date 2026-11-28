"""Agent Definition revision lifecycle tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.agent_definition_revisions as revisions_module
from app.models import AgentDefinitionRevision
from app.services.agent_definition_revision_publish import publish_revision, validate_revision
from app.services.agent_definition_revision_store import (
    REVISION_NUMBER_CONFLICT_DETAIL,
    REVISION_STORAGE_INTEGRITY_DETAIL,
    get_published_revision,
    list_agent_definition_revisions,
    load_definition_steps,
    serialize_revision,
)
from app.services.agent_definition_revisions import create_draft_revision
from tests.agent_definition_revision_fixtures import (
    DEFINITION_NAME,
    admin_user,
    make_definition,
    make_project,
    make_step,
)
from tests.services.agents.agent_definition_revision_lifecycle_support import _force_revision_number


async def test_colliding_revision_number_is_an_explicit_conflict(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)
    first = await create_draft_revision(db, definition=definition, created_by=admin.id)

    _force_revision_number(monkeypatch, int(first.revision_number))

    with pytest.raises(HTTPException) as excinfo:
        await create_draft_revision(db, definition=definition, created_by=admin.id)
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == REVISION_NUMBER_CONFLICT_DETAIL
    await db.rollback()


async def test_other_integrity_failures_get_a_distinct_state_without_db_detail(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)
    monkeypatch.setattr(
        revisions_module, "compute_snapshot_checksum", lambda _snapshot: None
    )

    with pytest.raises(HTTPException) as excinfo:
        await create_draft_revision(db, definition=definition, created_by=admin.id)

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == REVISION_STORAGE_INTEGRITY_DETAIL
    rendered = str(excinfo.value.detail).lower()
    assert "constraint" not in rendered
    assert "agent_definition_revisions" not in rendered
    await db.rollback()


async def test_publish_records_attribution_and_keeps_history(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)
    first = await create_draft_revision(db, definition=definition, created_by=admin.id)
    published = await publish_revision(db, revision=first, published_by=admin.id)

    assert published.status == "published"
    assert published.published_by == admin.id
    assert published.published_at is not None
    assert published.validation == {"ok": True, "issues": []}

    second = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=second, published_by=admin.id)
    # Earlier published revisions stay published so restore has a history.
    assert first.status == "published"
    current = await get_published_revision(db, definition.id)
    assert current is not None and current.id == second.id


async def test_publish_refuses_invalid_revision(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    await make_step(db, definition, position=1, name="Broken", allowed_tools=["nope_tool"])
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)

    with pytest.raises(HTTPException) as excinfo:
        await publish_revision(db, revision=revision, published_by=admin.id)

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["ok"] is False
    assert "unknown_tool" in {issue["code"] for issue in excinfo.value.detail["issues"]}
    assert revision.status != "published"


async def test_publish_revalidates_instead_of_trusting_stored_verdict(db: AsyncSession):
    admin = await admin_user(db)
    project = await make_project(db)
    definition = await make_definition(db, owner=admin, project_id=project.id)
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    assert (await validate_revision(db, revision=revision)).ok

    await db.delete(project)
    await db.flush()

    with pytest.raises(HTTPException) as excinfo:
        await publish_revision(db, revision=revision, published_by=admin.id)
    assert excinfo.value.status_code == 422
    assert "unknown_project" in {issue["code"] for issue in excinfo.value.detail["issues"]}


async def test_publish_rejects_an_already_published_revision(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=revision, published_by=admin.id)

    with pytest.raises(HTTPException) as excinfo:
        await publish_revision(db, revision=revision, published_by=admin.id)
    assert excinfo.value.status_code == 409


async def test_validate_does_not_mutate_a_published_revision(db: AsyncSession):
    admin = await admin_user(db)
    project = await make_project(db)
    definition = await make_definition(db, owner=admin, project_id=project.id)
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=revision, published_by=admin.id)

    await db.delete(project)
    await db.flush()
    result = await validate_revision(db, revision=revision)

    assert not result.ok
    assert revision.status == "published"
    assert revision.validation == {"ok": True, "issues": []}


async def test_definition_without_revisions_stays_untouched(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=2)

    assert await list_agent_definition_revisions(db, definition.id) == []
    assert await get_published_revision(db, definition.id) is None
    assert definition.name == DEFINITION_NAME
    assert len(await load_definition_steps(db, definition.id)) == 2
    assert (
        await db.execute(
            select(AgentDefinitionRevision).where(
                AgentDefinitionRevision.definition_id == definition.id
            )
        )
    ).scalars().all() == []


async def test_serialize_revision_exposes_the_documented_contract(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)

    payload = serialize_revision(revision)

    assert set(payload) == {
        "id",
        "definition_id",
        "revision_number",
        "status",
        "checksum",
        "snapshot",
        "validation",
        "restored_from_revision_id",
        "created_by",
        "created_at",
        "published_by",
        "published_at",
        "approved_by",
        "approved_at",
    }
    assert payload["snapshot"]["definition"]["name"] == DEFINITION_NAME
