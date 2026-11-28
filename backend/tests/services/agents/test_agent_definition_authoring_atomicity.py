"""The boundary owns the transaction: commit order, failed finalization, restored commit and staged writes."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.agent_definition_authoring as authoring
from app.models import AgentDefinition
from app.services.admin.governance import admin_agent_service
from app.services.agent_definition_authoring import OUTCOME_DELETED, OUTCOME_RECORDED, governed_agent_definition_write
from app.services.agent_definition_payload import serialize_agent_definition_payload
from app.services.agent_definition_writers import AgentDefinitionWriter
from tests.agent_definition_revision_fixtures import admin_user, make_definition, make_project
from tests.support.agent_definition_authoring_boundary_support import _audit_rows, _revisions


@pytest.mark.asyncio
async def test_a_writer_internal_commit_lands_after_the_revision_and_audit_row(
    db: AsyncSession,
):
    admin = await admin_user(db)
    events: list[str] = []
    real_finalize = authoring._finalize

    def _record_commit(_session: object) -> None:
        events.append("commit")

    async def _watch(db_, *, scope, touched):
        events.append("finalize")
        assert "commit" not in events, "the writer's commit was not deferred"
        return await real_finalize(db_, scope=scope, touched=touched)

    event.listen(db.sync_session, "after_commit", _record_commit)
    try:
        with patch.object(authoring, "_finalize", _watch):
            created = await admin_agent_service.create_agent(
                db,
                user_id=admin.id,
                payload={
                    "name": "Atomic Agent",
                    "goal": "Commit once",
                    "agent_type": "diagnosis",
                    "thinking_level": "light",
                },
                thinking_levels=["light"],
                serialize_agent_definition=serialize_agent_definition_payload,
            )
    finally:
        event.remove(db.sync_session, "after_commit", _record_commit)

    assert events == ["finalize", "commit"]
    assert len(await _revisions(db, created["id"])) == 1
    assert len(await _audit_rows(db, created["id"])) == 1


@pytest.mark.asyncio
async def test_a_failure_during_finalization_commits_nothing(db: AsyncSession):
    admin = await admin_user(db)
    events: list[str] = []

    def _record_commit(_session: object) -> None:
        events.append("commit")

    async def _explode(db_, *, scope, touched):
        raise RuntimeError("finalization failed")

    event.listen(db.sync_session, "after_commit", _record_commit)
    try:
        with patch.object(authoring, "_finalize", _explode):
            with pytest.raises(RuntimeError):
                await admin_agent_service.create_agent(
                    db,
                    user_id=admin.id,
                    payload={
                        "name": "Never Persisted Agent",
                        "goal": "Roll back",
                        "agent_type": "diagnosis",
                        "thinking_level": "light",
                    },
                    thinking_levels=["light"],
                    serialize_agent_definition=serialize_agent_definition_payload,
                )
    finally:
        event.remove(db.sync_session, "after_commit", _record_commit)

    assert events == []
    await db.rollback()
    remaining = (
        await db.execute(
            select(AgentDefinition.id).where(
                AgentDefinition.name == "Never Persisted Agent"
            )
        )
    ).scalars().all()
    assert list(remaining) == []


@pytest.mark.asyncio
async def test_commit_is_restored_after_the_scope_closes(db: AsyncSession):
    admin = await admin_user(db)
    original = type(db).commit

    async with governed_agent_definition_write(
        db, writer=AgentDefinitionWriter.BOOTSTRAP_PLATFORM_AGENTS, actor_id=admin.id
    ):
        assert db.commit.__func__ is not original
        async with governed_agent_definition_write(
            db, writer=AgentDefinitionWriter.BOOTSTRAP_PLATFORM_AGENTS, actor_id=admin.id
        ):
            pass
        # The inner scope must not hand the session back early.
        assert db.commit.__func__ is not original

    assert db.commit.__func__ is original


@pytest.mark.asyncio
async def test_a_staged_write_that_never_flushed_is_still_governed(db: AsyncSession):
    admin = await admin_user(db)
    definition_id = str(uuid.uuid4())

    async with governed_agent_definition_write(
        db, writer=AgentDefinitionWriter.PACKAGE_IMPORT, actor_id=admin.id
    ) as scope:
        definition = AgentDefinition(
            id=definition_id,
            owner_id=admin.id,
            name="Never Flushed Agent",
            description="Staged only",
            goal="Prove collection does not need the writer to flush",
            agent_type="diagnosis",
            thinking_level="light",
            branch_prefix="octryx",
            system_prompt="Be precise.",
            output_prompt="Report findings.",
            is_active=True,
        )
        definition.skill_preferences = {}
        db.add(definition)

    record = scope.record_for(definition_id)
    assert record is not None
    assert record.outcome == OUTCOME_RECORDED
    assert len(await _revisions(db, definition_id)) == 1
    assert len(await _audit_rows(db, definition_id)) == 1


@pytest.mark.asyncio
async def test_a_deletion_keeps_its_workspace_attribution(db: AsyncSession):
    admin = await admin_user(db)
    project = await make_project(db)
    definition = await make_definition(db, owner=admin, project_id=project.id, steps=1)
    await db.commit()
    definition_id = definition.id

    await admin_agent_service.delete_agent(db, user_id=admin.id, agent_id=definition_id)

    audit = await _audit_rows(db, definition_id)
    assert len(audit) == 1
    details = audit[0].details
    assert details["outcome"] == OUTCOME_DELETED
    assert details["project_id"] == project.id
    assert details["definition_id"] == definition_id
