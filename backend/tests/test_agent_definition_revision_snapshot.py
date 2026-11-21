"""Consecutive drafts are immutable, monotonic and checksum-stable, their snapshots hold ordered steps without volatile fields, and the shipped seed catalog carries no validation defect."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDefinition
from app.services.agent_definition_revision_store import load_definition_steps
from app.services.agent_definition_revisions import create_draft_revision
from app.services.agent_definition_snapshot import (
    build_definition_snapshot,
    compute_snapshot_checksum,
)
from app.services.agent_definition_validation import validate_definition_snapshot
from tests.agent_definition_revision_fixtures import DEFINITION_GOAL, admin_user, make_definition

# ---------------------------------------------------------------------------
# Seeded content: what fail-closed validation says about the shipped catalog
# ---------------------------------------------------------------------------

#: The seeded catalog carried five validation defects when fail-closed validation
#: landed: the four stale short tool names — the registry calls them
#: ``grep_workspace``, ``edit_workspace_file``, ``multi_edit_workspace_file``, and
#: ``apply_patch_workspace`` — plus ``agent_type="self_review"``, a step type used
#: as an agent mode. The seed content is repaired, so the expected set is
#: empty and any regression in shipped content fails this test with the exact
#: offending code and identifier.
KNOWN_SEEDED_DEFECTS: set[tuple[str, str]] = set()


# ---------------------------------------------------------------------------
# Draft creation, immutability, checksum stability
# ---------------------------------------------------------------------------


async def test_two_consecutive_drafts_are_monotonic_with_stable_checksums(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)

    first = await create_draft_revision(db, definition=definition, created_by=admin.id)
    second = await create_draft_revision(db, definition=definition, created_by=admin.id)

    assert (first.revision_number, second.revision_number) == (1, 2)
    assert first.id != second.id
    # Unchanged authored content hashes identically, which is what makes content
    # drift between revisions detectable.
    assert first.checksum == second.checksum
    assert len(first.checksum) == 64
    assert first.created_by == admin.id
    assert first.status == "draft"
    assert first.validation is None
    assert first.published_at is None


async def test_draft_checksum_changes_when_authored_content_changes(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)
    first = await create_draft_revision(db, definition=definition, created_by=admin.id)

    definition.goal = "A different goal"
    await db.flush()
    second = await create_draft_revision(db, definition=definition, created_by=admin.id)

    assert second.checksum != first.checksum
    assert first.snapshot["definition"]["goal"] == DEFINITION_GOAL


async def test_draft_snapshot_holds_ordered_steps_and_no_volatile_fields(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=3)

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    snapshot = revision.snapshot

    assert [step["position"] for step in snapshot["steps"]] == [1, 2, 3]
    assert [step["name"] for step in snapshot["steps"]] == ["Step 1", "Step 2", "Step 3"]
    assert snapshot["steps"][0]["allowed_tools"] == ["knowledge_search"]
    # Volatile/attribution fields must stay out so the checksum is content-only
    # and a restore can never move ownership.
    assert "id" not in snapshot["definition"]
    assert "owner_id" not in snapshot["definition"]
    assert "created_at" not in snapshot["definition"]
    assert all("id" not in step for step in snapshot["steps"])


async def test_snapshot_checksum_is_order_independent_over_dict_keys(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    steps = await load_definition_steps(db, definition.id)

    snapshot = build_definition_snapshot(definition, steps)
    reordered = {
        "steps": snapshot["steps"],
        "definition": dict(reversed(list(snapshot["definition"].items()))),
    }
    assert compute_snapshot_checksum(snapshot) == compute_snapshot_checksum(reordered)


async def test_seeded_definitions_carry_no_validation_defects(db: AsyncSession):
    """Every shipped seeded definition must be publishable as seeded.

    ``tests/test_agent_seed_definition_contract.py`` proves the publication half
    (draft -> validate -> publish); this keeps the whole catalog under the
    validator so a newly seeded agent cannot introduce an unresolvable reference.
    """
    definitions = (await db.execute(select(AgentDefinition))).scalars().all()
    assert definitions, "expected the seeded agent catalog to be present"

    observed: set[tuple[str, str]] = set()
    for definition in definitions:
        steps = await load_definition_steps(db, definition.id)
        result = await validate_definition_snapshot(
            db, build_definition_snapshot(definition, steps)
        )
        observed.update((issue.code, issue.subject) for issue in result.issues)

    assert observed == KNOWN_SEEDED_DEFECTS, observed - KNOWN_SEEDED_DEFECTS
