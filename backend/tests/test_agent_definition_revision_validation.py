"""Snapshot and fail-closed validation of Agent Definition revisions.

Covers the content half of the contract:
  - two consecutive drafts are immutable, monotonic, and checksum-stable
  - the snapshot holds ordered steps and no volatile or attribution fields
  - unknown tools, agent types, thinking levels, project/group/runtime
    references, and malformed step ordering cannot validate
  - validation issues carry typed codes and identifiers, never authored content
  - the shipped seed catalog carries no validation defect at all

The lifecycle half (numbering, publication, restore) lives in
``test_agent_definition_revision_lifecycle.py``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_revision_publish import validate_revision
from app.services.agent_definition_revision_store import load_definition_steps
from app.services.agent_definition_revisions import create_draft_revision
from app.services.agent_definition_validation import validate_definition_snapshot
from tests.agent_definition_revision_fixtures import (
    admin_user,
    first_runtime_target,
    make_definition,
    make_project,
    make_step,
)

# ---------------------------------------------------------------------------
# Validation fails closed
# ---------------------------------------------------------------------------


async def test_validation_accepts_a_clean_definition(db: AsyncSession):
    admin = await admin_user(db)
    project = await make_project(db)
    target = await first_runtime_target(db)
    definition = await make_definition(
        db, owner=admin, project_id=project.id, runtime_target_id=target.id
    )

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    assert result.ok, result.as_dict()
    assert revision.status == "draft"
    assert revision.validation == {"ok": True, "issues": []}


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("agent_type", "totally-unknown-mode", "unknown_agent_type"),
        ("thinking_level", "extreme", "unknown_thinking_level"),
        ("name", "", "missing_name"),
    ],
)
async def test_validation_rejects_unknown_header_values(
    db: AsyncSession, field: str, value: str, expected_code: str
):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)
    setattr(definition, field, value)
    await db.flush()

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    assert not result.ok
    assert expected_code in {issue.code for issue in result.issues}
    assert revision.status == "invalid"


async def test_validation_rejects_unknown_project_and_runtime_target(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(
        db,
        owner=admin,
        project_id=str(uuid.uuid4()),
        runtime_target_id=str(uuid.uuid4()),
    )

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    codes = {issue.code for issue in result.issues}
    assert not result.ok
    assert {"unknown_project", "unknown_runtime_target"} <= codes


async def test_validation_rejects_unknown_tool_identifier(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    await make_step(
        db,
        definition,
        position=1,
        name="Broken",
        allowed_tools=["knowledge_search", "definitely_not_a_tool"],
    )

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    assert not result.ok
    unknown = [issue for issue in result.issues if issue.code == "unknown_tool"]
    assert [issue.subject for issue in unknown] == ["definitely_not_a_tool"]


async def test_validation_accepts_enumerated_dynamic_tool_families(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    await make_step(
        db,
        definition,
        position=1,
        name="Dynamic",
        allowed_tools=["database_tool_customer_lookup", "mcp__graph__search", "run_flow_intake"],
    )

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    assert result.ok, result.as_dict()


async def test_validation_rejects_bare_dynamic_tool_prefix(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    await make_step(db, definition, position=1, name="Bare", allowed_tools=["mcp__"])

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    assert not result.ok
    assert {issue.code for issue in result.issues} == {"unknown_tool"}


async def test_validation_rejects_duplicate_step_positions(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    await make_step(db, definition, position=1, name="First")
    await make_step(db, definition, position=1, name="Duplicate")

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    assert not result.ok
    assert "duplicate_step_position" in {issue.code for issue in result.issues}


async def test_validation_rejects_non_contiguous_and_non_positive_positions(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    await make_step(db, definition, position=1, name="First")
    await make_step(db, definition, position=7, name="Gapped")
    gapped = await create_draft_revision(db, definition=definition, created_by=admin.id)
    gapped_result = await validate_revision(db, revision=gapped)
    assert "non_contiguous_step_positions" in {
        issue.code for issue in gapped_result.issues
    }

    for step in await load_definition_steps(db, definition.id):
        await db.delete(step)
    await db.flush()
    await make_step(db, definition, position=0, name="Zero")
    zeroed = await create_draft_revision(db, definition=definition, created_by=admin.id)
    zero_result = await validate_revision(db, revision=zeroed)
    assert "invalid_step_position" in {issue.code for issue in zero_result.issues}


async def test_validation_rejects_malformed_snapshot_shape(db: AsyncSession):
    assert not (await validate_definition_snapshot(db, {})).ok
    assert {
        issue.code for issue in (await validate_definition_snapshot(db, {})).issues
    } == {"malformed_snapshot"}
    broken = {"definition": {"name": "x"}, "steps": "not-a-list"}
    assert "malformed_snapshot" in {
        issue.code for issue in (await validate_definition_snapshot(db, broken)).issues
    }


async def test_validation_issues_carry_no_prompt_or_config_content(db: AsyncSession):
    admin = await admin_user(db)
    secret_prompt = "SENSITIVE-SYSTEM-PROMPT-MARKER"
    definition = await make_definition(db, owner=admin, agent_type="not-a-mode", steps=0)
    definition.system_prompt = secret_prompt
    await db.flush()
    await make_step(db, definition, position=1, name="S", allowed_tools=["nope_tool"])

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    result = await validate_revision(db, revision=revision)

    rendered = str(result.as_dict())
    assert secret_prompt not in rendered
    assert set(result.as_dict()["issues"][0]) == {"code", "field", "subject"}
