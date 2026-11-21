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
from tests.agent_definition_authoring_boundary_support import _audit_rows, _revisions
from tests.agent_definition_revision_fixtures import admin_user, make_definition, make_project

# ---------------------------------------------------------------------------
# Atomicity: the boundary is the single transaction owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_writer_internal_commit_lands_after_the_revision_and_audit_row(
    db: AsyncSession,
):
    """The governed write is one transaction, revision and audit row included.

    Panel CRUD commits inside its own body. If that commit ended the transaction,
    the authored row would be durable while validation, the immutable revision, and
    the audit entry were still pending — and a failure in between would leave an
    authored row with no lineage and no evidence. The boundary therefore defers the
    writer's commit until finalization is in the same transaction, which is exactly
    the ordering asserted here.
    """
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
    """A failed governed write never committed the authored row on its way there."""
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
    """The deferral lasts exactly as long as the scope, nested scopes included."""
    admin = await admin_user(db)
    original = type(db).commit

    async with governed_agent_definition_write(
        db, writer=AgentDefinitionWriter.BOOTSTRAP_SAMPLE_WORKSPACE, actor_id=admin.id
    ):
        assert db.commit.__func__ is not original
        async with governed_agent_definition_write(
            db, writer=AgentDefinitionWriter.BOOTSTRAP_BUILTIN_AGENTS, actor_id=admin.id
        ):
            pass
        # The inner scope must not hand the session back early.
        assert db.commit.__func__ is not original

    assert db.commit.__func__ is original


@pytest.mark.asyncio
async def test_a_staged_write_that_never_flushed_is_still_governed(db: AsyncSession):
    """Collection cannot depend on the writer happening to flush.

    A writer that only ``add``s its rows and returns produces no ``before_flush``
    event at all, so without the scope's own final flush the boundary would see nothing
    and the live row would reach the database through the request-level commit with no
    revision and no audit entry.
    """
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
    """A deletion audit row must still say which Workspace lost the definition."""
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
