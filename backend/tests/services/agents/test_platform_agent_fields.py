"""The platform agent fields and the four-eyes publish of a platform agent revision."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from app.models import AuditLog
from app.services.agent_definition_payload import payload_from_snapshot, serialize_agent_definition_payload
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revision_store import load_definition_steps
from app.services.agent_definition_revisions import create_draft_revision
from app.services.agent_definition_snapshot import build_definition_snapshot, compute_snapshot_checksum
from app.services.platform_agents.publish_governance import REFUSAL_ADMIN_REQUIRED, REFUSAL_FOUR_EYES
from tests.agent_definition_revision_fixtures import admin_user, make_definition, make_user
from tests.prompt_catalog_publish_support import second_admin


@pytest.fixture(autouse=True)
def _no_self_approval(monkeypatch):
    import app.services.governance.four_eyes as four_eyes

    async def none(_db):
        return None

    monkeypatch.setattr(four_eyes, "self_approval_source", none)
    monkeypatch.setattr(four_eyes, "dev_self_approval_permitted", lambda settings=None: False)


async def _platform_revision(db, *, key: str = "engineer"):
    from sqlalchemy import select

    from app.models import AgentDefinition

    admin = await admin_user(db)
    definition = (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == key))).scalar_one()
    definition.description = "Edited for review."
    await db.flush()
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    return admin, definition, revision


@pytest.mark.asyncio
async def test_the_author_cannot_publish_a_platform_agent_alone(db):
    admin, _definition, revision = await _platform_revision(db)
    with pytest.raises(HTTPException) as refused:
        await publish_revision(db, revision=revision, published_by=admin.id)
    assert refused.value.status_code == 403
    assert refused.value.detail["code"] == REFUSAL_FOUR_EYES
    assert revision.status != "published" and revision.approved_by is None


@pytest.mark.asyncio
async def test_a_non_admin_cannot_publish_a_platform_agent(db):
    _admin, _definition, revision = await _platform_revision(db, key="assistant")
    member = await make_user(db, label="member")
    with pytest.raises(HTTPException) as refused:
        await publish_revision(db, revision=revision, published_by=member.id)
    assert refused.value.detail["code"] == REFUSAL_ADMIN_REQUIRED


@pytest.mark.asyncio
async def test_a_second_admin_publishes_and_is_recorded_as_approver(db):
    _admin, _definition, revision = await _platform_revision(db, key="reviewer")
    reviewer = await second_admin(db)
    published = await publish_revision(db, revision=revision, published_by=reviewer.id)
    assert published.status == "published"
    assert published.approved_by == reviewer.id and published.approved_at is not None


@pytest.mark.asyncio
async def test_self_approval_under_the_platform_rule_is_audited(db, monkeypatch):
    import app.services.governance.four_eyes as four_eyes

    async def rule(_db):
        return four_eyes.SELF_APPROVAL_SOURCE_RULE

    monkeypatch.setattr(four_eyes, "self_approval_source", rule)
    admin, _definition, revision = await _platform_revision(db)
    await publish_revision(db, revision=revision, published_by=admin.id)
    assert revision.approved_by == admin.id
    audit = (await db.execute(sa.select(AuditLog).where(AuditLog.resource_id == revision.id))).scalars().all()
    assert [row.action for row in audit] == [four_eyes.SELF_APPROVAL_AUDIT_ACTION]


@pytest.mark.asyncio
async def test_other_agents_keep_the_existing_publish_rule(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    published = await publish_revision(db, revision=revision, published_by=admin.id)
    assert published.status == "published" and published.approved_by is None


@pytest.mark.asyncio
async def test_new_fields_are_snapshotted_only_when_set(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin)
    steps = await load_definition_steps(db, definition.id)
    before = compute_snapshot_checksum(build_definition_snapshot(definition, steps))
    definition.chat_selectable = False
    assert compute_snapshot_checksum(build_definition_snapshot(definition, steps)) == before

    definition.runtime_preference = "coding"
    definition.chat_selectable = True
    definition.tools_deny_json = '["run_bash"]'
    snapshot = build_definition_snapshot(definition, steps)
    assert compute_snapshot_checksum(snapshot) != before
    payload = payload_from_snapshot(snapshot["definition"], snapshot["steps"], definition_id=definition.id)
    assert (payload["runtimePreference"], payload["chatSelectable"], payload["toolsDeny"]) == (
        "coding", True, ["run_bash"])
    await db.refresh(definition, ["group", "steps"])
    live = serialize_agent_definition_payload(definition)
    assert live["runtimePreference"] == "coding" and live["chatSelectable"] is True
