"""The bootstrap writer class, explicitly.

Bootstrap is the one writer class the governed boundary *publishes* for: the
content is a repository constant proven publishable by
``tests/test_agent_definition_revision_validation.py``. Without that, ``published``
execution mode would deny every shipped agent and the mode would be unusable.

These tests pin the three properties that make it safe: the seeded catalog really
is published after bootstrap, re-running bootstrap appends nothing, and a seed
that fails validation is recorded ``invalid`` and left unpublished rather than
failing application start.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDefinition, AgentDefinitionRevision, AuditLog
from app.services.agent_builtins import ensure_builtin_agents
from app.services.agent_definition_authoring import (
    AUDIT_ACTION,
    OUTCOME_INVALID,
    OUTCOME_PUBLISHED,
    OUTCOME_UNCHANGED,
    governed_agent_definition_write,
)
from app.services.agent_definition_revision_store import get_published_revision
from app.services.agent_definition_snapshot import (
    build_definition_snapshot,
    compute_snapshot_checksum,
)
from app.services.agent_definition_writers import AgentDefinitionWriter
from tests.agent_definition_revision_fixtures import admin_user, make_definition

BOOTSTRAP_WRITERS = {
    AgentDefinitionWriter.BOOTSTRAP_BUILTIN_AGENTS.value,
    AgentDefinitionWriter.BOOTSTRAP_SAMPLE_WORKSPACE.value,
    AgentDefinitionWriter.BOOTSTRAP_PLATFORM_AGENTS.value,
}


async def _seeded_definitions(db: AsyncSession) -> list[AgentDefinition]:
    return list((await db.execute(select(AgentDefinition))).scalars().all())


async def _governed_audit_rows(db: AsyncSession) -> list[AuditLog]:
    return list(
        (await db.execute(select(AuditLog).where(AuditLog.action == AUDIT_ACTION)))
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_every_seeded_definition_is_published_by_bootstrap(db: AsyncSession):
    """Every revision a bootstrap writer records for a valid seed is published.

    Each seeded row (the built-in Coding agent, A3, and the Acme Orders test definitions) gets
    Each seeded row (the built-in Coding agent and the Acme Orders test definitions) gets
    """
    definitions = await _seeded_definitions(db)
    assert definitions, "expected the seeded agent catalog to be present"

    for definition in definitions:
        revisions = list(
            (
                await db.execute(
                    select(AgentDefinitionRevision)
                    .where(AgentDefinitionRevision.definition_id == definition.id)
                    .order_by(AgentDefinitionRevision.revision_number.asc())
                )
            )
            .scalars()
            .all()
        )
        assert revisions, definition.name
        assert [row.revision_number for row in revisions] == list(
            range(1, len(revisions) + 1)
        ), definition.name
        checksums = {row.checksum for row in revisions}
        assert len(checksums) == len(revisions), (
            f"{definition.name}: bootstrap appended a revision without a content change"
        )
        for revision in revisions:
            assert revision.status == "published", definition.name
            assert revision.published_by == revision.created_by
            assert revision.published_at is not None
            assert revision.validation == {"ok": True, "issues": []}


@pytest.mark.asyncio
async def test_the_published_seed_matches_the_live_row_exactly(db: AsyncSession):
    """No drift at bootstrap: publishing and seeding produce the same content."""
    from app.services.agent_definition_revision_store import load_definition_steps

    for definition in await _seeded_definitions(db):
        revision = await get_published_revision(db, definition.id)
        assert revision is not None, definition.name
        steps = await load_definition_steps(db, definition.id)
        live_checksum = compute_snapshot_checksum(
            build_definition_snapshot(definition, steps)
        )
        assert revision.checksum == live_checksum, definition.name


@pytest.mark.asyncio
async def test_bootstrap_audit_rows_name_a_bootstrap_writer(db: AsyncSession):
    rows = await _governed_audit_rows(db)
    assert rows, "expected bootstrap to have recorded governed writes"
    outcomes = {row.details["outcome"] for row in rows}
    for row in rows:
        assert row.details["writer"] in BOOTSTRAP_WRITERS
        assert row.details["writer_class"] == "bootstrap"
        # Two bootstrap writers legitimately re-assert the same row; the second one
        # finds identical content and records the explicit ``unchanged`` outcome.
        assert row.details["outcome"] in {OUTCOME_PUBLISHED, OUTCOME_UNCHANGED}
    assert OUTCOME_PUBLISHED in outcomes


@pytest.mark.asyncio
async def test_rerunning_bootstrap_appends_no_revision(db: AsyncSession):
    """Bootstrap runs on every application start; it must stay idempotent.

    Idempotent means the *lineage* does not grow. The audit log does: every
    re-asserted definition records the explicit ``unchanged`` outcome, which is what
    distinguishes a governed no-op from a write that never reached the boundary.
    """
    admin = await admin_user(db)
    before = {
        row.id
        for row in (await db.execute(select(AgentDefinitionRevision))).scalars().all()
    }
    audit_before = {row.id for row in await _governed_audit_rows(db)}

    await ensure_builtin_agents(db, admin_user=admin)
    await db.commit()

    after = {
        row.id
        for row in (await db.execute(select(AgentDefinitionRevision))).scalars().all()
    }
    assert after == before

    # The built-in exists already: the governed re-run changes nothing and records no new outcome.
    new_rows = [row for row in await _governed_audit_rows(db) if row.id not in audit_before]
    assert {row.details["outcome"] for row in new_rows} <= {OUTCOME_UNCHANGED}


@pytest.mark.asyncio
async def test_an_invalid_seed_is_recorded_unpublished_and_does_not_raise(
    db: AsyncSession,
):
    """A bootstrap write never fails the application because content is invalid.

    The shipped seeds are gated before they are written, so this can only
    happen to pre-existing tenant rows that a seed writer touches. The explicit
    outcome is an ``invalid`` revision that publication — and therefore
    published-mode execution — refuses.
    """
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    await db.commit()

    async with governed_agent_definition_write(
        db,
        writer=AgentDefinitionWriter.BOOTSTRAP_BUILTIN_AGENTS,
        actor_id=admin.id,
    ) as scope:
        definition.agent_type = "not_a_real_mode"
        await db.flush()

    record = scope.record_for(definition.id)
    assert record is not None
    assert record.outcome == OUTCOME_INVALID
    assert record.issue_codes == ("unknown_agent_type",)

    revision = (
        await db.execute(
            select(AgentDefinitionRevision).where(
                AgentDefinitionRevision.definition_id == definition.id
            )
        )
    ).scalars().one()
    assert revision.status == "invalid"
    assert revision.published_at is None
    assert await get_published_revision(db, definition.id) is None
